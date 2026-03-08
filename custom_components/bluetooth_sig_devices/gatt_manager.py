"""GATT connection management for Bluetooth SIG Devices integration.

Encapsulates GATT probing and on-demand characteristic reading.
The ``GATTManager`` class owns the semaphore that limits concurrent
BLE connections and the background tasks for GATT probing.

Periodic GATT polling is handled by the HA-native
``ActiveBluetoothProcessorCoordinator`` which calls back into
``async_poll_gatt_with_semaphore()`` via the coordinator's
``poll_method`` closure.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.types.gatt_enums import CharacteristicRole
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.entity import EntityDescription

from .const import (
    DEFAULT_CONNECTION_TIMEOUT,
    DOMAIN,
    MAX_PROBE_FAILURES,
    BLEAddress,
    CharacteristicSource,
    DiscoveredCharacteristic,
    DiscoveryData,
)
from .device_adapter import HomeAssistantBluetoothAdapter
from .device_validator import GATTProbeResult
from .entity_builder import (
    DIAGNOSTIC_ROLES,
    SKIP_ROLES,
    add_simple_entity,
    add_struct_entities,
    to_ha_state,
)
from .support_detector import SupportDetector

if TYPE_CHECKING:
    from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)


class GATTManager:
    """Manages GATT probing and characteristic reading for BLE devices.

    Owns:

    - Probe results cache
    - Probe failure tracking
    - Pending probe set
    - Concurrency semaphore
    - In-flight probe tasks

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
    ) -> None:
        """Initialise the GATT manager.

        Args:
            hass: Home Assistant instance.
            coordinator: Parent coordinator (for device instances, config checks).
            max_concurrent_probes: Max simultaneous BLE connections for probing.

        """
        self._hass = hass
        self._coordinator = coordinator

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

        # Check if we've already probed this device
        if address in self.probe_results:
            return self.probe_results[address]

        # Check if we've hit the failure limit
        if self.probe_failures.get(address, 0) >= MAX_PROBE_FAILURES:
            _LOGGER.debug(
                "Skipping probe for %s - exceeded failure limit",
                address,
            )
            return None

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
                service_uuid = BluetoothUUID(service.uuid)
                if service_uuid.short_form.upper() in excluded_svc:
                    _LOGGER.debug(
                        "Device %s: skipping excluded service %s",
                        address,
                        service_uuid.short_form,
                    )
                    continue

                for char_uuid_str, char_instance in service.characteristics.items():
                    char_uuid = BluetoothUUID(char_uuid_str)

                    if char_uuid.short_form.upper() in excluded_char:
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
                supported_char_uuids=supported_uuids,
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
                MAX_PROBE_FAILURES,
                err,
            )
            return None

        finally:
            with contextlib.suppress(Exception):
                await device.disconnect()

    async def async_probe_and_setup(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Probe a connectable device and set up processor if successful.

        Called as a background task for connectable devices that don't have
        interpretable advertisement data. Uses a semaphore to limit
        concurrent probes since the BLE adapter has limited slots.
        """
        address = service_info.address
        probe_timeout = DEFAULT_CONNECTION_TIMEOUT + 15.0

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

                    coord = self._coordinator

                    # Trigger an immediate poll so cached GATT data reaches
                    # entities without waiting for a new advertisement.
                    coord.notify_probe_complete(address)

                    if not coord.has_config_entry(address):
                        coord.discovery_tracker.mark_discovery_triggered(address)

                        # Build DiscoveredCharacteristic list from probe
                        supported: list[DiscoveredCharacteristic] = []
                        for char_uuid in result.supported_char_uuids:
                            instance = SupportDetector._resolve_characteristic_by_uuid(
                                char_uuid,
                                fallback_name=char_uuid.short_form,
                            )
                            supported.append(
                                DiscoveredCharacteristic(
                                    characteristic=instance,
                                    source=CharacteristicSource.GATT,
                                )
                            )

                        characteristics_str = (
                            coord.support_detector.build_characteristics_summary(
                                address,
                                supported,
                                coord.known_characteristics,
                            )
                        )

                        discovery_flow.async_create_flow(
                            self._hass,
                            DOMAIN,
                            context={"source": "integration_discovery"},
                            data=DiscoveryData(
                                address=address,
                                name=service_info.name
                                or f"Bluetooth Device {address[-8:]}",
                                characteristics=characteristics_str,
                                manufacturer="",
                            ),
                        )
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
                    MAX_PROBE_FAILURES,
                )
            except Exception as err:
                self.probe_failures[address] = self.probe_failures.get(address, 0) + 1
                _LOGGER.warning(
                    "GATT probe failed for %s: %s (attempt %d/%d)",
                    address,
                    err,
                    self.probe_failures[address],
                    MAX_PROBE_FAILURES,
                )
            finally:
                self.pending_probes.discard(address)
                self._probe_tasks.pop(address, None)

            # Surface a single warning when a device exhausts all retries
            if self.probe_failures.get(address, 0) >= MAX_PROBE_FAILURES:
                _LOGGER.warning(
                    "All %d GATT probe attempts failed for %s — "
                    "device cannot be auto-discovered via GATT",
                    MAX_PROBE_FAILURES,
                    address,
                )

            # Brief delay between probes to let BLE adapter recover
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _read_chars_connected(
        self,
        address: BLEAddress,
        device: object,
        probe_result: GATTProbeResult,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Read characteristic values using an already-open BLE connection.

        Called inside ``async_probe_device`` while the connection is still
        live. Returns ``None`` if no entities could be built (e.g. all
        reads failed).
        """
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
        entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

        for char_uuid in probe_result.supported_char_uuids:
            try:
                parsed_value = await device.read(str(char_uuid))  # type: ignore[attr-defined]
                if parsed_value is None:
                    continue

                char_class: type[BaseCharacteristic[Any]] | None = (
                    CharacteristicRegistry.get_characteristic_class_by_uuid(char_uuid)
                )
                if not char_class:
                    continue

                char_instance: BaseCharacteristic[Any] = char_class()
                char_name: str = char_instance.name
                char_unit: str = char_instance.unit

                role: CharacteristicRole = char_instance.role
                if role in SKIP_ROLES:
                    _LOGGER.debug(
                        "Skipping GATT %s (role=%s) from %s",
                        char_name,
                        role.value,
                        address,
                    )
                    continue

                is_diagnostic = role in DIAGNOSTIC_ROLES

                if hasattr(parsed_value, "__struct_fields__"):
                    add_struct_entities(
                        None,
                        f"gatt_{char_uuid.short_form}",
                        char_name,
                        parsed_value,
                        char_unit,
                        is_diagnostic,
                        entity_descriptions,
                        entity_names,
                        entity_data,
                        spec=char_instance.spec,
                    )
                else:
                    add_simple_entity(
                        None,
                        f"gatt_{char_uuid.short_form}",
                        char_name,
                        to_ha_state(parsed_value),
                        char_unit,
                        is_diagnostic,
                        entity_descriptions,
                        entity_names,
                        entity_data,
                    )

            except Exception as err:
                _LOGGER.warning(
                    "Failed to read characteristic %s from %s during probe: %s",
                    char_uuid.short_form,
                    address,
                    err,
                )

        if not entity_data:
            return None

        return PassiveBluetoothDataUpdate(
            devices={},
            entity_descriptions=entity_descriptions,
            entity_names=entity_names,
            entity_data=entity_data,
        )

    async def async_poll_gatt_characteristics(
        self,
        address: BLEAddress,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Poll GATT characteristics from a connectable device.

        Connects, reads all known parseable characteristics, and returns
        a ``PassiveBluetoothDataUpdate`` with the data.
        """
        probe_result = self.probe_results.get(address)
        if not probe_result or not probe_result.has_support():
            _LOGGER.debug("No GATT support for device %s", address)
            return None

        coord = self._coordinator
        device = coord.devices.get(address)
        if not device:
            _LOGGER.warning("No device instance for %s — cannot poll", address)
            return None

        try:
            await device.connect()

            entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
            entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
            entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

            for char_uuid in probe_result.supported_char_uuids:
                try:
                    parsed_value = await device.read(str(char_uuid))
                    if parsed_value is None:
                        continue

                    char_class: type[BaseCharacteristic[Any]] | None = (
                        CharacteristicRegistry.get_characteristic_class_by_uuid(
                            char_uuid
                        )
                    )
                    if not char_class:
                        continue

                    char_instance: BaseCharacteristic[Any] = char_class()
                    char_name: str = char_instance.name
                    char_unit: str = char_instance.unit

                    role: CharacteristicRole = char_instance.role
                    if role in SKIP_ROLES:
                        _LOGGER.debug(
                            "Skipping GATT %s (role=%s) from %s",
                            char_name,
                            role.value,
                            address,
                        )
                        continue

                    is_diagnostic = role in DIAGNOSTIC_ROLES

                    if hasattr(parsed_value, "__struct_fields__"):
                        add_struct_entities(
                            None,
                            f"gatt_{char_uuid.short_form}",
                            char_name,
                            parsed_value,
                            char_unit,
                            is_diagnostic,
                            entity_descriptions,
                            entity_names,
                            entity_data,
                            spec=char_instance.spec,
                        )
                    else:
                        add_simple_entity(
                            None,
                            f"gatt_{char_uuid.short_form}",
                            char_name,
                            to_ha_state(parsed_value),
                            char_unit,
                            is_diagnostic,
                            entity_descriptions,
                            entity_names,
                            entity_data,
                        )

                except Exception as err:
                    _LOGGER.warning(
                        "Failed to read characteristic %s from %s: %s",
                        char_uuid.short_form,
                        address,
                        err,
                    )

            if not entity_data:
                return None

            return PassiveBluetoothDataUpdate(
                devices={},
                entity_descriptions=entity_descriptions,
                entity_names=entity_names,
                entity_data=entity_data,
            )

        except Exception as err:
            _LOGGER.warning("Failed to poll GATT from %s: %s", address, err)
            return None

        finally:
            with contextlib.suppress(Exception):
                await device.disconnect()

    async def async_poll_gatt_with_semaphore(
        self,
        address: BLEAddress,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Poll GATT characteristics with concurrency control.

        On the first call after a successful probe, returns the cached
        initial read (populated during ``async_probe_and_setup``)
        without acquiring the semaphore or opening a BLE connection.

        Subsequent calls acquire the probe semaphore and perform a
        live GATT read.
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

    def schedule_probe(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Schedule a GATT probe for a connectable device.

        Guards against duplicate probes and exceeded failure limits.
        """
        address = service_info.address
        if (
            address in self.probe_results
            or address in self.pending_probes
            or self.probe_failures.get(address, 0) >= MAX_PROBE_FAILURES
        ):
            return

        self.pending_probes.add(address)
        task = self._hass.async_create_task(
            self.async_probe_and_setup(service_info),
            f"bluetooth_sig_probe_{address}",
        )
        self._probe_tasks[address] = task

    def can_probe(self, address: BLEAddress, connectable: bool) -> bool:
        """Return True if a GATT probe is possible for this address."""
        return (
            connectable
            and address not in self.probe_results
            and address not in self.pending_probes
            and self.probe_failures.get(address, 0) < MAX_PROBE_FAILURES
        )

    def is_probes_exhausted(self, address: BLEAddress) -> bool:
        """Return True if all probe attempts have been used."""
        return (
            self.probe_failures.get(address, 0) >= MAX_PROBE_FAILURES
            or address in self.probe_results
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def remove_device(self, address: BLEAddress) -> None:
        """Clean up GATT state for a removed device."""
        self.probe_results.pop(address, None)
        self.probe_failures.pop(address, None)
        self._initial_gatt_cache.pop(address, None)

    async def async_stop(self) -> None:
        """Cancel all in-flight probe tasks."""
        for address, task in self._probe_tasks.items():
            task.cancel()
            _LOGGER.debug("Cancelled GATT probe task for %s", address)
        self._probe_tasks.clear()
        self.pending_probes.clear()
