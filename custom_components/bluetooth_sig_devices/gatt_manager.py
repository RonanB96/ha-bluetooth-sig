"""GATT probe scheduling and lifecycle for Bluetooth SIG Devices.

Owns the GATT probe workflow: connecting to BLE devices, discovering
services, classifying characteristics, and notifying the coordinator.

Polling (reading characteristics from already-probed devices) is
delegated to ``gatt_poller`` — this module only manages probe
scheduling, failure tracking, and concurrency.

Periodic GATT polling is handled by the HA-native
``ActiveBluetoothProcessorCoordinator`` which calls back into
``async_poll_gatt_with_semaphore()`` via the coordinator's
``poll_method`` closure.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from bluetooth_sig.device.device import Device
from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONFIRMED_DEVICE_PROBE_BACKOFF,
    DEFAULT_CONNECTION_TIMEOUT,
    MAX_PROBE_FAILURES,
    BLEAddress,
)
from .device_adapter import HomeAssistantBluetoothAdapter
from .device_validator import GATTProbeResult
from .gatt_poller import (
    poll_gatt_characteristics,
    read_chars_connected,
)

if TYPE_CHECKING:
    from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)

# Callback type for probe result notifications.
# Called with (address, result, service_info) on success,
# (address, service_info) on failure.
type ProbeSuccessCallback = Callable[
    [BLEAddress, GATTProbeResult, BluetoothServiceInfoBleak], None
]
type ProbeFailureCallback = Callable[[BLEAddress, BluetoothServiceInfoBleak], None]


class GATTManager:
    """Manages GATT probing and characteristic reading for BLE devices.

    Owns:

    - Probe results cache
    - Probe failure tracking
    - Pending probe set
    - Concurrency semaphore
    - In-flight probe tasks

    Discovery decisions (rejection, discovery flow firing) are NOT
    owned by this class — they are handled via callbacks to the
    coordinator.

    Periodic GATT polling is scheduled externally by the
    ``ActiveBluetoothProcessorCoordinator``; the manager exposes
    ``async_poll_gatt_with_semaphore()`` for that purpose.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: BluetoothSIGCoordinator,
        *,
        max_concurrent_probes: int = 2,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        max_probe_retries: int = MAX_PROBE_FAILURES,
        on_probe_success: ProbeSuccessCallback | None = None,
        on_probe_failure: ProbeFailureCallback | None = None,
    ) -> None:
        """Initialise the GATT manager.

        Args:
            hass: Home Assistant instance.
            coordinator: Parent coordinator (for device instances, config checks).
            max_concurrent_probes: Max simultaneous BLE connections for probing.
            connection_timeout: Timeout in seconds for establishing a BLE connection.
            max_probe_retries: Maximum probe attempts before giving up on a device.
            on_probe_success: Callback invoked when a probe finds parseable
                characteristics.
            on_probe_failure: Callback invoked when a probe attempt fails.

        """
        self._hass = hass
        self._coordinator = coordinator
        self._connection_timeout = connection_timeout
        self._max_probe_retries = max_probe_retries
        self._on_probe_success = on_probe_success
        self._on_probe_failure = on_probe_failure

        # GATT probe results cache
        self.probe_results: dict[BLEAddress, GATTProbeResult] = {}
        # Addresses that failed probing (to avoid repeated attempts)
        self.probe_failures: dict[BLEAddress, int] = {}
        # Addresses currently being probed (to avoid duplicate probe attempts)
        self.pending_probes: set[BLEAddress] = set()
        # Semaphore to limit concurrent GATT probes
        self._probe_semaphore = asyncio.Semaphore(max_concurrent_probes)
        # In-flight GATT probe tasks keyed by device address
        self._probe_tasks: dict[BLEAddress, asyncio.Task[None]] = {}
        # Initial GATT read cached during probe — consumed on first poll
        self._initial_gatt_cache: dict[
            BLEAddress, PassiveBluetoothDataUpdate[float | int | str | bool]
        ] = {}
        # Monotonic timestamp of last probe attempt for confirmed devices
        self._confirmed_probe_last_attempt: dict[BLEAddress, float] = {}

    # ------------------------------------------------------------------
    # Properties for diagnostics / external access
    # ------------------------------------------------------------------

    @property
    def probe_tasks(self) -> dict[BLEAddress, asyncio.Task[None]]:
        """Return the in-flight probe tasks."""
        return self._probe_tasks

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    async def async_probe_device(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> GATTProbeResult | None:
        """Probe a connectable device to discover its GATT characteristics.

        Uses the library's Device class to connect, discover services,
        and identify which characteristics we can parse.

        Returns:
            GATTProbeResult if successful, None if probe failed.

        """
        address = service_info.address

        # Already have a cached result
        if address in self.probe_results:
            return self.probe_results[address]

        _LOGGER.debug("Probing device %s for GATT capabilities", address)

        coord = self._coordinator
        excluded_svc = coord.excluded_service_uuids
        excluded_char = coord.excluded_char_uuids

        # Get or create device instance with GATT support
        if address not in coord.devices:
            ble_device = bluetooth.async_ble_device_from_address(
                self._hass, address, connectable=True
            )
            adapter = HomeAssistantBluetoothAdapter(
                address,
                service_info.name or "",
                hass=self._hass,
                ble_device=ble_device,
            )
            from bluetooth_sig.device.device import Device

            coord.devices[address] = Device(
                connection_manager=adapter,
                translator=coord.translator,
            )

        device = coord.devices[address]

        try:
            # Connect and discover services using library's Device class
            await device.connect()
            services = await device.connected.discover_services()

            # Count parseable characteristics
            supported_uuids: list[BluetoothUUID] = []
            parseable_count = 0

            for service in services:
                try:
                    service_uuid = BluetoothUUID(service.uuid)
                    service_short_form = service_uuid.short_form.upper()
                except Exception as err:
                    _LOGGER.debug(
                        "Device %s: skipping service with invalid UUID %r: %s",
                        address,
                        getattr(service, "uuid", None),
                        err,
                        exc_info=True,
                    )
                    continue

                if service_short_form in excluded_svc:
                    _LOGGER.debug(
                        "Device %s: skipping excluded service %s",
                        address,
                        service_uuid.short_form,
                    )
                    continue

                characteristics = getattr(service, "characteristics", None)
                if not isinstance(characteristics, dict):
                    _LOGGER.debug(
                        "Device %s: skipping service %s with non-mapping characteristics: %r",
                        address,
                        service_uuid.short_form,
                        type(characteristics),
                    )
                    continue

                for char_uuid_str, char_instance in characteristics.items():
                    try:
                        char_uuid = BluetoothUUID(char_uuid_str)
                        char_short_form = char_uuid.short_form.upper()
                    except Exception as err:
                        _LOGGER.debug(
                            "Device %s: skipping characteristic with invalid UUID %r in service %s: %s",
                            address,
                            char_uuid_str,
                            service_uuid.short_form,
                            err,
                            exc_info=True,
                        )
                        continue

                    if char_short_form in excluded_char:
                        _LOGGER.debug(
                            "Device %s: skipping excluded characteristic %s",
                            address,
                            char_uuid.short_form,
                        )
                        continue

                    char_class: type[BaseCharacteristic[Any]] | None = (
                        CharacteristicRegistry.get_characteristic_class_by_uuid(
                            char_uuid
                        )
                    )
                    if char_class is not None:
                        supported_uuids.append(char_uuid)
                        parseable_count += 1
                        _LOGGER.debug(
                            "Device %s has parseable SIG characteristic: %s",
                            address,
                            char_instance.name
                            if hasattr(char_instance, "name")
                            else char_uuid.short_form,
                        )

            result = GATTProbeResult(
                address=address,
                name=service_info.name,
                parseable_count=parseable_count,
                supported_char_uuids=tuple(supported_uuids),
            )

            self.probe_results[address] = result

            if parseable_count > 0:
                _LOGGER.debug(
                    "Device %s has %d parseable GATT characteristics",
                    address,
                    parseable_count,
                )

                # Read characteristic values while the connection is still
                # open — avoids a second BLE connection when the first poll
                # fires.  The result is cached and consumed by
                # ``async_poll_gatt_with_semaphore`` on its first call.
                initial_update = await self._read_chars_connected(
                    address, device, result
                )
                if initial_update is not None:
                    self._initial_gatt_cache[address] = initial_update
                    _LOGGER.debug(
                        "Cached initial GATT read for %s (%d entities)",
                        address,
                        len(initial_update.entity_data),
                    )
            else:
                _LOGGER.debug(
                    "Device %s has no parseable GATT characteristics",
                    address,
                )

            return result

        except Exception as err:
            self.probe_failures[address] = self.probe_failures.get(address, 0) + 1
            _LOGGER.warning(
                "Failed to probe device %s (attempt %d/%d): %s",
                address,
                self.probe_failures[address],
                self._max_probe_retries,
                err,
            )
            return None

        finally:
            try:
                await device.disconnect()
            except Exception as disc_err:
                _LOGGER.warning(
                    "Disconnect failed after probing %s: %s",
                    address,
                    disc_err,
                )

    async def async_probe_and_setup(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Probe a connectable device and notify the coordinator of the result.

        Called as a background task for connectable devices that don't have
        interpretable advertisement data.  Uses a semaphore to limit
        concurrent probes since the BLE adapter has limited slots.

        On success: invokes ``_on_probe_success`` callback so the
        coordinator can decide whether to fire a discovery flow or
        trigger an immediate poll.

        On failure: invokes ``_on_probe_failure`` callback so the
        coordinator can decide whether to reject the device.
        """
        address = service_info.address
        probe_timeout = self._connection_timeout + 15.0

        async with self._probe_semaphore:
            _LOGGER.debug(
                "Starting GATT probe for connectable device %s (%s)",
                address,
                service_info.name or "unknown",
            )

            try:
                result = await asyncio.wait_for(
                    self.async_probe_device(service_info),
                    timeout=probe_timeout,
                )

                if result and result.has_support():
                    _LOGGER.info(
                        "GATT probe successful for %s: %d parseable characteristics",
                        address,
                        result.parseable_count,
                    )
                    if self._on_probe_success is not None:
                        self._on_probe_success(address, result, service_info)
                else:
                    _LOGGER.info(
                        "GATT probe for %s found no parseable characteristics",
                        address,
                    )
            except TimeoutError:
                self.probe_failures[address] = self.probe_failures.get(address, 0) + 1
                _LOGGER.warning(
                    "GATT probe timed out for %s after %.0fs (attempt %d/%d)",
                    address,
                    probe_timeout,
                    self.probe_failures[address],
                    self._max_probe_retries,
                )
                if self._on_probe_failure is not None:
                    self._on_probe_failure(address, service_info)
            except Exception as err:
                self.probe_failures[address] = self.probe_failures.get(address, 0) + 1
                _LOGGER.warning(
                    "GATT probe failed for %s: %s (attempt %d/%d)",
                    address,
                    err,
                    self.probe_failures[address],
                    self._max_probe_retries,
                )
                if self._on_probe_failure is not None:
                    self._on_probe_failure(address, service_info)
            finally:
                self.pending_probes.discard(address)
                self._probe_tasks.pop(address, None)

            # Brief delay between probes to let BLE adapter recover
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # Polling — delegates to gatt_poller module functions
    # ------------------------------------------------------------------

    async def _read_chars_connected(
        self,
        address: BLEAddress,
        device: Device,
        probe_result: GATTProbeResult,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Read characteristic values using an already-open BLE connection."""
        return await read_chars_connected(address, device, probe_result)

    async def async_poll_gatt_characteristics(
        self,
        address: BLEAddress,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Poll GATT characteristics from a connectable device."""
        probe_result = self.probe_results.get(address)
        if not probe_result or not probe_result.has_support():
            _LOGGER.debug("No GATT support for device %s", address)
            return None

        device = self._coordinator.devices.get(address)
        if not device:
            _LOGGER.warning("No device instance for %s — cannot poll", address)
            return None

        return await poll_gatt_characteristics(address, probe_result, device)

    async def async_poll_gatt_with_semaphore(
        self,
        address: BLEAddress,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Poll GATT characteristics with concurrency control.

        On the first call after a successful probe, returns the cached
        initial read without acquiring the semaphore.
        """
        cached = self._initial_gatt_cache.pop(address, None)
        if cached is not None:
            _LOGGER.debug("Returning cached initial GATT data for %s", address)
            return cached
        async with self._probe_semaphore:
            return await self.async_poll_gatt_characteristics(address)

    # ------------------------------------------------------------------
    # Scheduling helpers (called by coordinator)
    # ------------------------------------------------------------------

    def _create_probe_task(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Create and track a GATT probe task.

        Shared by ``schedule_probe`` and
        ``schedule_probe_for_confirmed_device``.  The caller is
        responsible for all guard checks before calling this.
        """
        address = service_info.address
        self.pending_probes.add(address)
        task = self._hass.async_create_task(
            self.async_probe_and_setup(service_info),
            f"bluetooth_sig_probe_{address}",
        )
        self._probe_tasks[address] = task

    def schedule_probe(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Schedule a GATT probe for a connectable device.

        Only prevents duplicate probes (already probed or in-flight).
        Discovery rejection and confirmed-device backoff decisions are
        owned by the coordinator, not this class.
        """
        address = service_info.address
        if address in self.probe_results or address in self.pending_probes:
            return
        self._create_probe_task(service_info)

    def schedule_probe_for_confirmed_device(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Schedule a GATT probe for a device the user has already confirmed.

        Unlike ``schedule_probe``, this applies a backoff gate to avoid
        flooding the BLE adapter when a device is temporarily out of
        range.
        """
        address = service_info.address

        # Already have a successful probe result, or a probe is in flight.
        if address in self.probe_results or address in self.pending_probes:
            return

        # Backoff gate — only applies when there have been prior failures.
        failures = self.probe_failures.get(address, 0)
        if failures > 0:
            last_attempt = self._confirmed_probe_last_attempt.get(address, 0.0)
            if (time.monotonic() - last_attempt) < CONFIRMED_DEVICE_PROBE_BACKOFF:
                return

        self._confirmed_probe_last_attempt[address] = time.monotonic()
        self._create_probe_task(service_info)

    def is_failures_exhausted(self, address: BLEAddress) -> bool:
        """Return True if all probe failure attempts have been used.

        Only checks the failure counter against the maximum retry limit.
        Does NOT check whether a successful result exists — that is a
        separate concern (use ``probe_results`` directly).
        """
        return self.probe_failures.get(address, 0) >= self._max_probe_retries

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def remove_device(self, address: BLEAddress) -> None:
        """Clean up all GATT state for a device.

        Safe to call even if the address has no GATT state.
        Used by coordinator cleanup and config entry removal.
        """
        self.probe_results.pop(address, None)
        self.probe_failures.pop(address, None)
        self.pending_probes.discard(address)
        self._initial_gatt_cache.pop(address, None)
        self._confirmed_probe_last_attempt.pop(address, None)
        task = self._probe_tasks.pop(address, None)
        if task is not None:
            task.cancel()
            _LOGGER.debug("Cancelled in-flight probe task for %s", address)

    async def async_stop(self) -> None:
        """Cancel all in-flight probe tasks and await their completion."""
        tasks = list(self._probe_tasks.values())
        for address, task in self._probe_tasks.items():
            task.cancel()
            _LOGGER.debug("Cancelled GATT probe task for %s", address)
        self._probe_tasks.clear()
        self.pending_probes.clear()

        # Await cancelled tasks so they finish before HA proceeds to
        # the final shutdown stage.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
