"""Coordinator for Bluetooth SIG Devices integration.

Orchestrates BLE device discovery, processor lifecycle, and the
data-update pipeline.  Two independent data paths:

1. **Advertisements** (passive, event-driven) — ``update_device()``
2. **GATT polling** (active, timer-driven) — ``_poll_gatt()``

Both paths push ``PassiveBluetoothDataUpdate`` into the same
``ActiveBluetoothProcessorCoordinator``; the framework merges
entity keys from each path without interference.

Delegates to:

- ``entity_builder`` / ``entity_metadata`` — entity construction & metadata
- ``gatt_manager.GATTManager`` — GATT probing and characteristic reading
- ``discovery_tracker.DiscoveryTracker`` — seen/rejected/stale tracking
- ``advertisement_manager.AdvertisementManager`` — advertisement conversion & metadata
- ``support_detector.SupportDetector`` — support detection & characteristic tracking
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from bluetooth_sig import prewarm_registries as _lib_prewarm_registries
from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.device.device import Device
from bluetooth_sig.gatt.services.base import BaseGattService
from bluetooth_sig.gatt.services.registry import GattServiceRegistry
from bluetooth_sig.types.advertising import AdvertisementData
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.active_update_processor import (
    ActiveBluetoothProcessorCoordinator,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
)
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .advertisement_manager import AdvertisementManager
from .const import (
    CONF_DEVICE_POLL_INTERVAL,
    CONF_GATT_ENABLED,
    DOMAIN,
    EXCLUDED_SERVICE_NAMES,
    MAX_CONCURRENT_PROBES,
    BLEAddress,
    DeviceStatistics,
    DiagnosticsSnapshot,
    DiscoveryData,
    GATTProbeSnapshotData,
)
from .device_adapter import HomeAssistantBluetoothAdapter
from .device_validator import is_static_address
from .discovery_tracker import DiscoveryTracker
from .entity_builder import (
    add_interpreted_entities,
    add_service_data_entities,
)
from .gatt_manager import GATTManager
from .support_detector import SupportDetector

_LOGGER = logging.getLogger(__name__)


class BluetoothSIGCoordinator:
    """Coordinator for managing Bluetooth SIG devices.

    This coordinator implements continuous auto-discovery of ALL Bluetooth
    devices.  When a device advertises data that the bluetooth-sig-python
    library can parse, a discovery flow is fired so the device appears in
    the HA "Discovered" section.  Entities are only created after the user
    confirms the device via the standard config flow.

    For connectable devices, this coordinator can also probe GATT services
    to discover characteristics that can be parsed by the library.
    """

    _cached_excluded_uuids: tuple[frozenset[str], frozenset[str]] | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        poll_interval: int = 300,
        max_concurrent_probes: int = MAX_CONCURRENT_PROBES,
        connection_timeout: int = 30,
        max_probe_retries: int = 3,
        stale_device_timeout: int = 3600,
    ) -> None:
        """Initialise the coordinator."""
        self.hass = hass
        self.entry = entry
        self.poll_interval = poll_interval
        self.translator = BluetoothSIGTranslator()
        self.devices: dict[BLEAddress, Device] = {}

        # Per-device characteristic tracking: {address: {uuid_str: name}}
        self.known_characteristics: dict[BLEAddress, dict[str, str]] = {}

        # Retrieve excluded UUIDs built during prewarm_registries().
        if BluetoothSIGCoordinator._cached_excluded_uuids is not None:
            self._excluded_service_uuids, self._excluded_char_uuids = (
                BluetoothSIGCoordinator._cached_excluded_uuids
            )
        else:
            _LOGGER.warning("Excluded UUIDs not pre-warmed; building in event loop")
            self._excluded_service_uuids, self._excluded_char_uuids = (
                self._build_excluded_uuids()
            )

        # Per-device processor coordinators keyed by address
        self._processor_coordinators: dict[
            BLEAddress,
            ActiveBluetoothProcessorCoordinator[
                PassiveBluetoothDataUpdate[float | int | str | bool]
            ],
        ] = {}

        # Callback to unregister global discovery
        self._cancel_discovery: CALLBACK_TYPE | None = None

        # --- Sub-managers ---
        self._gatt_manager = GATTManager(
            hass,
            self,
            max_concurrent_probes=max_concurrent_probes,
            connection_timeout=float(connection_timeout),
            max_probe_retries=max_probe_retries,
        )
        self._discovery_tracker = DiscoveryTracker(
            hass, self, stale_device_timeout=stale_device_timeout
        )
        self._support_detector = SupportDetector(self.translator, self._gatt_manager)

    # ------------------------------------------------------------------
    # Public properties for sub-managers and diagnostics
    # ------------------------------------------------------------------

    @property
    def processor_coordinators(
        self,
    ) -> dict[
        BLEAddress,
        ActiveBluetoothProcessorCoordinator[
            PassiveBluetoothDataUpdate[float | int | str | bool]
        ],
    ]:
        """Return the per-device processor coordinators."""
        return self._processor_coordinators

    @property
    def gatt_manager(self) -> GATTManager:
        """Return the GATT manager."""
        return self._gatt_manager

    @property
    def discovery_tracker(self) -> DiscoveryTracker:
        """Return the discovery tracker."""
        return self._discovery_tracker

    @property
    def support_detector(self) -> SupportDetector:
        """Return the support detector."""
        return self._support_detector

    @property
    def excluded_service_uuids(self) -> frozenset[str]:
        """Return excluded service UUIDs."""
        return self._excluded_service_uuids

    @property
    def excluded_char_uuids(self) -> frozenset[str]:
        """Return excluded characteristic UUIDs."""
        return self._excluded_char_uuids

    # ------------------------------------------------------------------
    # Registry pre-warming (static)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_excluded_uuids() -> tuple[frozenset[str], frozenset[str]]:
        """Build sets of excluded service and characteristic UUIDs."""
        excluded_service_uuids: set[str] = set()
        excluded_char_uuids: set[str] = set()

        for svc_class in GattServiceRegistry.get_all_services():
            svc: BaseGattService = svc_class()
            if svc.name in EXCLUDED_SERVICE_NAMES:
                excluded_service_uuids.add(svc.uuid.short_form.upper())
                for char_uuid in svc.get_expected_characteristic_uuids():
                    excluded_char_uuids.add(
                        BluetoothUUID(str(char_uuid)).short_form.upper()
                    )

        _LOGGER.debug(
            "Excluded services: %s, excluded characteristics: %s",
            excluded_service_uuids,
            excluded_char_uuids,
        )
        return frozenset(excluded_service_uuids), frozenset(excluded_char_uuids)

    @staticmethod
    def prewarm_registries() -> None:
        """Eagerly load all bluetooth-sig YAML registries.

        Called via ``hass.async_add_executor_job`` so the synchronous
        file I/O happens outside the event loop.
        """
        _lib_prewarm_registries()

        BluetoothSIGCoordinator._cached_excluded_uuids = (
            BluetoothSIGCoordinator._build_excluded_uuids()
        )
        _LOGGER.debug("bluetooth-sig registries pre-warmed")

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    def _has_config_entry(self, address: BLEAddress) -> bool:
        """Check whether a confirmed config entry exists for *address*.

        This is the canonical implementation — ``has_config_entry`` delegates
        here so that tests can patch ``_has_config_entry`` on an instance and
        have all callers (including sub-managers) see the override.
        """
        return any(
            entry.unique_id == address
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.unique_id is not None
        )

    def has_config_entry(self, address: BLEAddress) -> bool:
        """Public alias — delegates to ``_has_config_entry``."""
        return self._has_config_entry(address)

    def _is_gatt_enabled(self, address: BLEAddress) -> bool:
        """Check whether GATT is enabled for the device at *address*.

        Returns ``True`` if no config entry exists (pre-confirmation devices
        should still be probed) or if the entry's ``gatt_enabled`` option
        is ``True`` (the default).
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == address:
                return bool(entry.options.get(CONF_GATT_ENABLED, True))
        return True

    # ------------------------------------------------------------------
    # Processor lifecycle
    # ------------------------------------------------------------------

    def create_device_processor(
        self,
        address: BLEAddress,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
        entity_class: type,
    ) -> None:
        """Create a processor coordinator for a confirmed device.

        Uses ``ActiveBluetoothProcessorCoordinator`` which natively
        supports two independent data paths:

        1. **Advertisements** — passive, event-driven via ``update_method``
        2. **GATT polling** — active, triggered by ``needs_poll_method`` /
           ``poll_method`` on each advertisement cycle

        The framework's built-in ``Debouncer`` (10 s cooldown,
        ``immediate=True``) ensures the first poll fires promptly after
        entity setup and subsequent polls are spaced by the configured
        ``poll_interval``.
        """
        if address in self._processor_coordinators:
            _LOGGER.debug("Processor already exists for %s — skipping", address)
            return

        _LOGGER.info("Creating processor coordinator for device %s", address)

        processor_coordinator: ActiveBluetoothProcessorCoordinator[
            PassiveBluetoothDataUpdate[float | int | str | bool]
        ] = ActiveBluetoothProcessorCoordinator(
            self.hass,
            _LOGGER,
            address=address,
            mode=BluetoothScanningMode.PASSIVE,
            update_method=self.update_device,
            needs_poll_method=self._needs_poll(address, entry),
            poll_method=self._poll_gatt(address, entry),
            connectable=False,
        )

        processor: PassiveBluetoothDataProcessor[
            float | int | str | bool,
            PassiveBluetoothDataUpdate[float | int | str | bool],
        ] = PassiveBluetoothDataProcessor(lambda x: x)

        entry.async_on_unload(
            processor.async_add_entities_listener(entity_class, async_add_entities)
        )
        entry.async_on_unload(
            processor_coordinator.async_register_processor(
                processor, SensorEntityDescription
            )
        )
        entry.async_on_unload(processor_coordinator.async_start())

        self._processor_coordinators[address] = processor_coordinator
        _LOGGER.info("Now tracking Bluetooth device %s", address)

    # ------------------------------------------------------------------
    # GATT poll callbacks (used by ActiveBluetoothProcessorCoordinator)
    # ------------------------------------------------------------------

    def _needs_poll(
        self, address: BLEAddress, entry: ConfigEntry
    ) -> Callable[[BluetoothServiceInfoBleak, float | None], bool]:
        """Return a ``needs_poll_method`` closure for *address*.

        Returns ``True`` when:

        - GATT is enabled for this device (``gatt_enabled`` option), AND
        - GATT probe results exist with parseable characteristics, AND
        - The device has never been polled, or the effective poll interval
          seconds have elapsed since the last poll.

        The effective poll interval is the device-level override if set
        (non-zero), otherwise the hub-level ``poll_interval``.
        """
        gatt = self._gatt_manager

        def _check(
            _service_info: BluetoothServiceInfoBleak,
            last_poll: float | None,
        ) -> bool:
            if not entry.options.get(CONF_GATT_ENABLED, True):
                return False
            probe = gatt.probe_results.get(address)
            if not probe or not probe.has_support():
                return False
            if last_poll is None:
                return True
            device_interval = entry.options.get(CONF_DEVICE_POLL_INTERVAL, 0)
            effective_interval = (
                device_interval if device_interval else self.poll_interval
            )
            return last_poll >= effective_interval

        return _check

    def _poll_gatt(
        self, address: BLEAddress, entry: ConfigEntry
    ) -> Callable[
        [BluetoothServiceInfoBleak],
        Coroutine[Any, Any, PassiveBluetoothDataUpdate[float | int | str | bool]],
    ]:
        """Return a ``poll_method`` closure for *address*.

        The closure delegates to
        ``GATTManager.async_poll_gatt_with_semaphore`` and raises
        ``RuntimeError`` if no data is returned (handled gracefully by
        the ``ActiveBluetoothProcessorCoordinator`` error handler).

        Returns an empty update if GATT is disabled for this device.
        """
        gatt = self._gatt_manager

        async def _poll(
            _service_info: BluetoothServiceInfoBleak,
        ) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
            if not entry.options.get(CONF_GATT_ENABLED, True):
                msg = f"GATT disabled for {address}"
                raise RuntimeError(msg)
            result = await gatt.async_poll_gatt_with_semaphore(address)
            if result is None:
                msg = f"GATT poll returned no data for {address}"
                raise RuntimeError(msg)
            return result

        return _poll

    @callback
    def notify_probe_complete(self, address: BLEAddress) -> None:
        """Trigger an immediate poll after a successful GATT probe.

        For devices whose advertisement data never changes, HA's bluetooth
        framework deduplicates and stops firing callbacks.  Without a new
        callback the ``ActiveBluetoothProcessorCoordinator`` never
        re-evaluates ``needs_poll``, so cached GATT data would remain
        undelivered.

        This method schedules the poll directly via the debouncer, ensuring
        entities are populated promptly after probe completion regardless of
        advertisement frequency.
        """
        proc = self._processor_coordinators.get(address)
        if proc is None:
            return
        # The debouncer requires _last_service_info to be set (asserted
        # in _async_poll).  It is populated by the initial replay in
        # async_register_callback at startup.
        if proc._last_service_info is None:  # noqa: SLF001
            _LOGGER.debug("Cannot trigger poll for %s — no last service info", address)
            return
        _LOGGER.debug(
            "Triggering immediate poll for %s after successful probe", address
        )
        proc._debounced_poll.async_schedule_call()  # noqa: SLF001

    def remove_device(self, address: BLEAddress) -> None:
        """Remove tracking state for a device whose config entry was removed."""
        self._processor_coordinators.pop(address, None)
        self._gatt_manager.remove_device(address)
        self._discovery_tracker.remove_device(address)

    # ------------------------------------------------------------------
    # Device data update pipeline
    # ------------------------------------------------------------------

    def update_device(
        self, service_info: BluetoothServiceInfoBleak
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
        """Update device data from Bluetooth advertisement."""
        address = service_info.address
        is_first_update = address not in self.devices

        _LOGGER.debug(
            "Processing device %s (name=%s, rssi=%s, mfr_data=%d, svc_data=%d)",
            address,
            service_info.name or "unknown",
            service_info.rssi,
            len(service_info.manufacturer_data)
            if service_info.manufacturer_data
            else 0,
            len(service_info.service_data) if service_info.service_data else 0,
        )

        if is_first_update:
            _LOGGER.info(
                "Device %s: first advertisement update received (name=%s)",
                address,
                service_info.name or "unknown",
            )

        # Get or create device instance
        if address not in self.devices:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, address, connectable=True
            )
            adapter = HomeAssistantBluetoothAdapter(
                address,
                service_info.name or "",
                hass=self.hass,
                ble_device=ble_device,
            )
            self.devices[address] = Device(
                connection_manager=adapter,
                translator=self.translator,
            )
            _LOGGER.debug("Created new device for address %s", address)

        # Convert advertisement using AdvertisementManager
        advertisement = AdvertisementManager.convert_advertisement(service_info)

        return self._build_passive_bluetooth_update(
            address, service_info, advertisement
        )

    def _build_passive_bluetooth_update(
        self,
        address: BLEAddress,
        service_info: BluetoothServiceInfoBleak,
        advertisement: AdvertisementData,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
        """Build PassiveBluetoothDataUpdate from advertisement data."""
        devices: dict[str | None, DeviceInfo] = {}
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
        entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

        device_name = service_info.name or f"Bluetooth Device {address[-8:]}"
        devices[None] = DeviceInfo(
            name=device_name,
            manufacturer=AdvertisementManager.get_manufacturer_name(advertisement),
            model=AdvertisementManager.get_model_name(advertisement),
        )

        # Process interpreted data if available
        seen_uuids: set[str] = set()
        if advertisement.interpreted_data:
            _LOGGER.debug(
                "Device %s has interpreted data from %s: %s",
                address,
                advertisement.interpreter_name,
                advertisement.interpreted_data,
            )
            add_interpreted_entities(
                None,
                advertisement.interpreter_name,
                advertisement.interpreted_data,
                entity_descriptions,
                entity_names,
                entity_data,
                seen_uuids=seen_uuids,
            )

        # Process service data for standard GATT characteristics
        if advertisement.ad_structures.core.service_data:
            add_service_data_entities(
                None,
                advertisement.ad_structures.core.service_data,
                self.translator,
                entity_descriptions,
                entity_names,
                entity_data,
                skip_uuids=seen_uuids if advertisement.interpreted_data else set(),
            )

        _LOGGER.debug(
            "Device %s: built update with %d entities (descriptions=%d, names=%d)",
            address,
            len(entity_data),
            len(entity_descriptions),
            len(entity_names),
        )

        return PassiveBluetoothDataUpdate(
            devices=devices,
            entity_descriptions=entity_descriptions,
            entity_names=entity_names,
            entity_data=entity_data,
        )

    # ------------------------------------------------------------------
    # Discovery orchestration
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the coordinator with continuous Bluetooth discovery."""
        _LOGGER.debug("Starting Bluetooth SIG coordinator with global discovery")

        scanner_count = bluetooth.async_scanner_count(self.hass, connectable=False)
        _LOGGER.debug("Bluetooth scanners available: %d", scanner_count)

        self._cancel_discovery = bluetooth.async_register_callback(
            self.hass,
            self._async_device_discovered,
            BluetoothCallbackMatcher(connectable=False),
            BluetoothScanningMode.PASSIVE,
        )
        _LOGGER.debug("Registered global Bluetooth callback for all devices")

        # Start stale-device cleanup timer
        self._discovery_tracker.async_start()

        # Process already-discovered devices
        already_discovered_connectable = list(
            bluetooth.async_discovered_service_info(self.hass, connectable=True)
        )
        already_discovered_nonconnectable = list(
            bluetooth.async_discovered_service_info(self.hass, connectable=False)
        )
        _LOGGER.debug(
            "Already-discovered devices: %d connectable, %d non-connectable",
            len(already_discovered_connectable),
            len(already_discovered_nonconnectable),
        )

        seen_addresses: dict[BLEAddress, BluetoothServiceInfoBleak] = {}
        for service_info in (
            already_discovered_connectable + already_discovered_nonconnectable
        ):
            if is_static_address(service_info):
                seen_addresses.setdefault(service_info.address, service_info)
        for service_info in seen_addresses.values():
            self._discovery_tracker.last_seen_time[service_info.address] = (
                time.monotonic()
            )
            self._ensure_device_processor(service_info)

        _LOGGER.info(
            "Bluetooth SIG coordinator started, monitoring for parseable devices"
        )

    @callback
    def _async_device_discovered(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Handle a Bluetooth device advertisement."""
        address = service_info.address

        # Ephemeral address filter
        if not is_static_address(service_info):
            count = self._discovery_tracker.increment_filtered_ephemeral()
            if count % 100 == 1:
                _LOGGER.debug(
                    "Filtered ephemeral BLE address %s (total filtered: %d)",
                    address,
                    count,
                )
            return

        tracker = self._discovery_tracker
        is_first = tracker.record_sighting(address)
        if is_first:
            _LOGGER.debug(
                "First BLE sighting: %s (name=%s, connectable=%s)",
                address,
                service_info.name or "unknown",
                service_info.connectable,
            )

        self._ensure_device_processor(service_info)

    def _ensure_device_processor(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Handle a discovered BLE device.

        For devices with a confirmed config entry, schedules GATT probing
        if applicable.  For new devices with parseable data, fires a
        standard HA discovery flow.
        """
        address = service_info.address
        tracker = self._discovery_tracker
        gatt = self._gatt_manager

        # Skip if we already have a processor
        if address in self._processor_coordinators:
            return

        # Skip fully-evaluated devices with no support
        if tracker.is_rejected(address):
            return

        # If a config entry already exists, just handle GATT probing
        if self.has_config_entry(address):
            if (
                service_info.connectable
                and self._is_gatt_enabled(address)
                and gatt.can_probe(address, service_info.connectable)
            ):
                gatt.schedule_probe(service_info)
            return

        # Already triggered discovery for this address
        if tracker.is_discovery_triggered(address):
            _LOGGER.debug("Device %s: discovery already triggered — skipping", address)
            return

        # Check if we have supported data from advertisement
        has_advert_data = self._support_detector.has_supported_data(service_info)

        # If no advertisement data is interpretable, try GATT probing
        if not has_advert_data:
            if gatt.can_probe(address, service_info.connectable):
                gatt.schedule_probe(service_info)
            elif not service_info.connectable:
                reason = "non-connectable with no parseable advertisement data"
                tracker.mark_rejected(address, reason)
                _LOGGER.info("Device %s rejected: %s", address, reason)
            elif gatt.is_probes_exhausted(address):
                reason = "all GATT probe attempts exhausted"
                tracker.mark_rejected(address, reason)
                _LOGGER.info("Device %s rejected: %s", address, reason)
            return

        # Device has parseable advertisement data — fire discovery flow
        tracker.mark_discovery_triggered(address)

        # Convert advertisement once and reuse for both manufacturer
        # support detection and company name extraction.
        advertisement = None
        manufacturer = ""
        try:
            advertisement = AdvertisementManager.convert_advertisement(service_info)
            manufacturer = (
                AdvertisementManager.get_manufacturer_name(advertisement) or ""
            )
        except Exception:
            _LOGGER.warning("Could not extract manufacturer for %s", address)

        # Fall back to GATT Manufacturer Name String if advert had none
        if not manufacturer:
            probe_result = gatt.probe_results.get(address)
            if probe_result and probe_result.manufacturer_name:
                manufacturer = probe_result.manufacturer_name

        # Collect characteristic names for the discovery card
        supported = self._support_detector.get_supported_characteristics(service_info)
        manufacturer_interp = (
            self._support_detector.check_manufacturer_support(
                service_info, advertisement=advertisement
            )
            or ""
        )
        char_names = self._support_detector.build_characteristics_summary(
            address,
            supported,
            self.known_characteristics,
            manufacturer_name=manufacturer_interp,
        )

        _LOGGER.info(
            "Firing discovery flow for device %s (%s) — characteristics: %s",
            address,
            service_info.name or "unknown",
            char_names or "none",
        )
        discovery_flow.async_create_flow(
            self.hass,
            DOMAIN,
            context={"source": "integration_discovery"},
            data=DiscoveryData(
                address=address,
                name=service_info.name or f"Bluetooth Device {address[-8:]}",
                characteristics=char_names,
                manufacturer=manufacturer,
                rssi=service_info.rssi,
            ),
        )

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        _LOGGER.debug("Stopping Bluetooth SIG coordinator")

        # Stop sub-managers
        await self._gatt_manager.async_stop()
        self._discovery_tracker.async_stop()

        # Cancel discovery callback
        if self._cancel_discovery is not None:
            self._cancel_discovery()
            self._cancel_discovery = None

        # Clear tracked state
        self.devices.clear()

    # ------------------------------------------------------------------
    # Diagnostics API
    # ------------------------------------------------------------------

    def is_device_active(self, address: BLEAddress) -> bool:
        """Return True if a device is actively tracked by a processor."""
        return address in self._processor_coordinators

    def get_known_characteristics(self, address: BLEAddress) -> dict[str, str]:
        """Return ``{uuid_str: human_name}`` for all known characteristics."""
        return self._support_detector.get_known_characteristics(
            address, self.known_characteristics
        )

    def get_diagnostics_snapshot(self) -> DiagnosticsSnapshot:
        """Return a snapshot of coordinator state for diagnostics."""
        gatt = self._gatt_manager
        tracker = self._discovery_tracker

        probe_results_data: dict[str, GATTProbeSnapshotData] = {}
        for addr, result in gatt.probe_results.items():
            probe_results_data[addr] = GATTProbeSnapshotData(
                parseable_characteristics=result.parseable_count,
                has_support=result.has_support(),
                probe_failures=gatt.probe_failures.get(addr, 0),
            )

        return DiagnosticsSnapshot(
            device_statistics=DeviceStatistics(
                tracked_devices=len(self.devices),
                active_processor_coordinators=len(self._processor_coordinators),
                gatt_probed_devices=len(gatt.probe_results),
                pending_probes=len(gatt.pending_probes),
                seen_devices=len(tracker.seen_devices),
                rejected_devices=len(tracker.rejected_devices),
                discovery_triggered=len(tracker.discovery_triggered),
                filtered_ephemeral_count=tracker.filtered_ephemeral_count,
            ),
            gatt_probe_results=probe_results_data,
            probe_failures=dict(gatt.probe_failures),
            known_characteristics={
                addr: list(chars.values())
                for addr, chars in self.known_characteristics.items()
            },
            rejection_reasons=dict(tracker.rejection_reasons),
        )
