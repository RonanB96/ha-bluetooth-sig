"""Coordinator for Bluetooth SIG Devices integration."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.device.device import Device
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.gatt.services.registry import GattServiceRegistry
from bluetooth_sig.registry.uuids.units import units_registry
from bluetooth_sig.types.advertising import AdvertisementData
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
)
from homeassistant.components.sensor import SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory, EntityDescription

from .const import DOMAIN, EXCLUDED_SERVICE_NAMES, MAX_PROBE_FAILURES
from .device_adapter import HomeAssistantBluetoothAdapter
from .device_validator import GATTProbeResult

_LOGGER = logging.getLogger(__name__)


class BluetoothSIGCoordinator:
    """Coordinator for managing Bluetooth SIG devices.

    This coordinator implements continuous auto-discovery of ALL Bluetooth devices.
    When a device advertises data that the bluetooth-sig-python library can parse,
    a discovery config flow is fired so the user can confirm adding it from the
    Integrations page. Device entries then create their own processor coordinators
    for entity management.

    For connectable devices, this coordinator can also probe GATT services to
    discover characteristics that can be parsed by the library.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.translator = BluetoothSIGTranslator()
        self.devices: dict[str, Device] = {}
        # Build excluded service/characteristic UUIDs from the library
        # Defer to async_start to avoid blocking I/O during __init__
        self._excluded_service_uuids: frozenset[str] = frozenset()
        self._excluded_char_uuids: frozenset[str] = frozenset()
        # Callback to unregister global discovery
        self._cancel_discovery: CALLBACK_TYPE | None = None
        # GATT probe results cache
        self._gatt_probe_results: dict[str, GATTProbeResult] = {}
        # Addresses that failed probing (to avoid repeated attempts)
        self._probe_failures: dict[str, int] = {}
        # Addresses currently being probed (to avoid duplicate probe attempts)
        self._pending_probes: set[str] = set()
        # Addresses for which a discovery flow has already been fired
        self._discovery_triggered: set[str] = set()
        # Semaphore to limit concurrent GATT probes (BLE adapter has limited slots)
        self._probe_semaphore = asyncio.Semaphore(2)
        # Cache for advertisement parsing results to avoid repeated blocking I/O
        self._advertisement_cache: dict[str, AdvertisementData] = {}
        # Semaphore to limit concurrent advertisement parsing
        self._advertisement_parse_semaphore = asyncio.Semaphore(1)
        # Cache for spec field units to avoid repeated blocking I/O
        self._spec_units_cache: dict[str, dict[str, str]] = {}
        # Cache for characteristic classes to avoid repeated blocking I/O
        self._char_class_cache: dict[str, type | None] = {}

    def get_gatt_probe_result(self, address: str) -> GATTProbeResult | None:
        """Return the GATT probe result for a device, if available."""
        return self._gatt_probe_results.get(address)

    @staticmethod
    def _build_excluded_uuids() -> tuple[frozenset[str], frozenset[str]]:
        """Build sets of excluded service and characteristic UUIDs from the library.

        Uses the bluetooth-sig library's GattServiceRegistry to identify
        services that should be excluded (GAP, GATT) and their characteristics.

        Returns:
            Tuple of (excluded_service_uuids, excluded_char_uuids) as frozensets
            of short-form UUIDs (e.g., '1800', '2A00')
        """
        excluded_service_uuids: set[str] = set()
        excluded_char_uuids: set[str] = set()

        for svc_class in GattServiceRegistry.get_all_services():
            svc = svc_class()
            if svc.name in EXCLUDED_SERVICE_NAMES:
                excluded_service_uuids.add(svc.uuid.short_form.upper())
                # Add all expected characteristics from this service
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

    def _convert_advertisement_cached(
        self, service_info: BluetoothServiceInfoBleak
    ) -> AdvertisementData:
        """Convert HA service info to library format with caching to avoid blocking I/O."""
        # Create a cache key from the relevant service info data
        cache_key_parts = [
            service_info.address,
            str(service_info.rssi or 0),
            str(sorted(service_info.manufacturer_data.items()) if service_info.manufacturer_data else []),
            str(sorted(service_info.service_data.items()) if service_info.service_data else []),
        ]
        cache_key = "|".join(cache_key_parts)

        # Check cache first
        if cache_key in self._advertisement_cache:
            return self._advertisement_cache[cache_key]

        # Not in cache, parse it synchronously (this may block, but should be rare due to caching)
        advertisement = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # Cache the result
        self._advertisement_cache[cache_key] = advertisement
        return advertisement

    def _get_spec_field_units_cached(
        self, char_uuid: BluetoothUUID,
    ) -> dict[str, str]:
        """Resolve per-field unit symbols from the GSS characteristic spec with caching.

        Queries the characteristic's GSS YAML specification for field-level
        unit metadata and resolves unit IDs to display symbols via the
        library's units registry.

        Args:
            char_uuid: The characteristic's Bluetooth UUID.

        Returns:
            Mapping of GSS spec python_name to unit symbol string.
            Only fields with a resolvable unit are included.
        """
        cache_key = str(char_uuid)
        if cache_key in self._spec_units_cache:
            return self._spec_units_cache[cache_key]

        # Not in cache, compute it (this may block, but should be rare)
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            char_uuid
        )
        if not char_class:
            self._spec_units_cache[cache_key] = {}
            return {}

        char_instance = char_class()
        spec = getattr(char_instance, "_spec", None)
        if not spec or not getattr(spec, "structure", None):
            self._spec_units_cache[cache_key] = {}
            return {}

        spec_units: dict[str, str] = {}
        for field_spec in spec.structure:
            uid = getattr(field_spec, "unit_id", None)
            if not uid:
                continue
            pname = getattr(field_spec, "python_name", None)
            if not pname:
                continue
            info = units_registry.get_unit_info_by_id(
                f"org.bluetooth.unit.{uid}"
            )
            if info and info.symbol:
                spec_units[pname] = info.symbol

        self._spec_units_cache[cache_key] = spec_units
        return spec_units

    @staticmethod
    def _match_field_unit(
        field_name: str,
        spec_units: dict[str, str],
    ) -> str | None:
        """Match a struct field name to a unit symbol from the GSS spec.

        Tries an exact match first, then falls back to substring
        containment (the struct field name may be a shortened form
        of the GSS spec python_name).
        """
        if field_name in spec_units:
            return spec_units[field_name]
        for spec_name, symbol in spec_units.items():
            if field_name in spec_name:
                return symbol
        return None

    async def async_probe_device(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> GATTProbeResult | None:
        """Probe a connectable device to discover its GATT characteristics.

        Uses the library's Device class to connect, discover services,
        and identify which characteristics we can parse.

        Args:
            service_info: Bluetooth service info for the device

        Returns:
            GATTProbeResult if successful, None if probe failed

        """
        address = service_info.address

        # Check if we've already probed this device
        if address in self._gatt_probe_results:
            return self._gatt_probe_results[address]

        # Check if we've hit the failure limit
        if self._probe_failures.get(address, 0) >= MAX_PROBE_FAILURES:
            _LOGGER.debug(
                "Skipping probe for %s - exceeded failure limit",
                address,
            )
            return None

        _LOGGER.debug("Probing device %s for GATT capabilities", address)

        # Get or create device instance with GATT support
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

        device = self.devices[address]

        try:
            # Connect and discover services using library's Device class
            await device.connect()
            services = await device.connected.discover_services()

            # Count parseable characteristics
            supported_uuids: list[BluetoothUUID] = []
            parseable_count = 0

            for service in services:
                # Skip excluded services (GAP, GATT) entirely
                service_uuid = BluetoothUUID(service.uuid)
                if service_uuid.short_form.upper() in self._excluded_service_uuids:
                    _LOGGER.debug(
                        "Device %s: skipping excluded service %s",
                        address,
                        service_uuid.short_form,
                    )
                    continue

                for char_uuid_str, char_instance in service.characteristics.items():
                    # If we have a characteristic instance from the registry,
                    # it means we can parse it
                    char_uuid = BluetoothUUID(char_uuid_str)

                    # Skip excluded characteristics (from GAP/GATT services)
                    if char_uuid.short_form.upper() in self._excluded_char_uuids:
                        _LOGGER.debug(
                            "Device %s: skipping excluded characteristic %s",
                            address,
                            char_uuid.short_form,
                        )
                        continue

                    char_class = (
                        await asyncio.get_event_loop().run_in_executor(
                            None, CharacteristicRegistry.get_characteristic_class_by_uuid, char_uuid
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

            self._gatt_probe_results[address] = result

            if parseable_count > 0:
                _LOGGER.info(
                    "Device %s has %d parseable GATT characteristics",
                    address,
                    parseable_count,
                )
            else:
                _LOGGER.debug(
                    "Device %s has no parseable GATT characteristics",
                    address,
                )

            return result

        except Exception as err:
            self._probe_failures[address] = self._probe_failures.get(address, 0) + 1
            _LOGGER.debug(
                "Failed to probe device %s (attempt %d/%d): %s",
                address,
                self._probe_failures[address],
                MAX_PROBE_FAILURES,
                err,
            )
            return None

        finally:
            # Always disconnect after probing
            with contextlib.suppress(Exception):
                await device.disconnect()

    async def _async_probe_and_setup(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Probe a connectable device and set up processor if successful.

        This is called as a background task for connectable devices that
        don't have interpretable advertisement data. Uses a semaphore to
        limit concurrent probes since the BLE adapter has limited slots.

        Args:
            service_info: Bluetooth service info for the device

        """
        address = service_info.address

        # Wait for available probe slot (limits concurrent connections)
        async with self._probe_semaphore:
            _LOGGER.info(
                "Starting GATT probe for connectable device %s (%s)",
                address,
                service_info.name or "unknown",
            )

            try:
                result = await self.async_probe_device(service_info)

                if result and result.has_support():
                    _LOGGER.info(
                        "GATT probe successful for %s: %d parseable characteristics",
                        address,
                        result.parseable_count,
                    )
                    # Fire discovery flow for this device
                    self._fire_discovery_flow(service_info)
                else:
                    _LOGGER.debug(
                        "GATT probe for %s found no parseable characteristics",
                        address,
                    )
            except Exception as err:
                _LOGGER.debug(
                    "GATT probe failed for %s: %s",
                    address,
                    err,
                )
            finally:
                self._pending_probes.discard(address)

            # Brief delay between probes to let BLE adapter recover
            await asyncio.sleep(0.5)

    async def async_poll_gatt_characteristics(
        self,
        address: str,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
        """Poll GATT characteristics from a connectable device.

        Connects to the device, reads all known parseable characteristics,
        and returns a PassiveBluetoothDataUpdate with the data.

        This method uses the library's Device.read() method which handles
        parsing automatically.

        Args:
            address: Device bluetooth address

        Returns:
            PassiveBluetoothDataUpdate with entity data, or None if failed

        """
        # Check if we have probe results; if not, attempt re-probe
        probe_result = self._gatt_probe_results.get(address)
        if not probe_result or not probe_result.has_support():
            # After HA restart, probe results are lost. Try re-probing.
            service_info = bluetooth.async_last_service_info(
                self.hass, address, connectable=True
            )
            if service_info:
                _LOGGER.debug(
                    "Re-probing %s for GATT capabilities (post-restart)",
                    address,
                )
                probe_result = await self.async_probe_device(service_info)
            if not probe_result or not probe_result.has_support():
                _LOGGER.debug("No GATT support for device %s", address)
                return None

        device = self.devices.get(address)
        if not device:
            _LOGGER.info("No device instance for %s", address)
            return None

        _LOGGER.info(
            "Polling %d GATT characteristics from %s",
            len(probe_result.supported_char_uuids),
            address,
        )
        try:
            await device.connect()
            _LOGGER.info("Connected to %s for GATT read", address)

            devices: dict[str | None, DeviceInfo] = {}
            entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
            entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
            entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

            devices[None] = DeviceInfo(
                name=probe_result.name or f"Bluetooth Device {address[-8:]}",
            )

            # Read each supported characteristic using the library's Device.read()
            for char_uuid in probe_result.supported_char_uuids:
                try:
                    # Use the library's read method - it handles parsing
                    parsed_value = await device.read(str(char_uuid))

                    if parsed_value is None:
                        continue

                    # Get characteristic info for entity metadata
                    # Run blocking registry call in executor
                    char_class = await asyncio.get_event_loop().run_in_executor(
                        None, CharacteristicRegistry.get_characteristic_class_by_uuid, char_uuid
                    )
                    if not char_class:
                        continue

                    char_instance = char_class()
                    char_name = char_instance.name
                    char_unit = char_instance.unit

                    # Create entity key
                    entity_key = PassiveBluetoothEntityKey(
                        f"gatt_{char_uuid.short_form}",
                        None,
                    )

                    # Handle the parsed value - could be simple or struct
                    if isinstance(parsed_value, (int, float, str, bool)):
                        is_numeric = isinstance(parsed_value, (int, float))
                        has_unit = bool(char_unit and char_unit.strip())
                        is_diag = not has_unit
                        effective_unit = (
                            char_unit if is_numeric and has_unit else None
                        )
                        entity_descriptions[entity_key] = SensorEntityDescription(
                            key=f"gatt_{char_uuid.short_form}",
                            name=char_name,
                            native_unit_of_measurement=effective_unit,
                            state_class=SensorStateClass.MEASUREMENT
                            if is_numeric and not is_diag
                            else None,
                            entity_category=EntityCategory.DIAGNOSTIC
                            if is_diag
                            else None,
                        )
                        entity_names[entity_key] = char_name
                        entity_data[entity_key] = parsed_value
                        _LOGGER.debug(
                            "Read GATT %s from %s: %s",
                            char_name,
                            address,
                            parsed_value,
                        )
                    elif hasattr(parsed_value, "__struct_fields__"):
                        # It's a struct - extract individual fields
                        self._add_struct_entities(
                            None,
                            f"gatt_{char_uuid.short_form}",
                            char_name,
                            parsed_value,
                            char_uuid,
                            entity_descriptions,
                            entity_names,
                            entity_data,
                        )

                except Exception as err:
                    _LOGGER.debug(
                        "Failed to read characteristic %s from %s: %s",
                        char_uuid.short_form,
                        address,
                        err,
                    )

            if not entity_data:
                _LOGGER.info("GATT poll produced no entity data for %s", address)
                return None

            _LOGGER.info(
                "GATT poll produced %d entities for %s",
                len(entity_data),
                address,
            )
            return PassiveBluetoothDataUpdate(
                devices=devices,
                entity_descriptions=entity_descriptions,
                entity_names=entity_names,
                entity_data=entity_data,
            )

        except Exception as err:
            _LOGGER.info("Failed to poll GATT from %s: %s", address, err)
            return None

        finally:
            with contextlib.suppress(Exception):
                await device.disconnect()

    def update_device(
        self, service_info: BluetoothServiceInfoBleak
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
        """Update device data from Bluetooth advertisement.

        Args:
            service_info: Bluetooth service information from Home Assistant

        Returns:
            PassiveBluetoothDataUpdate with entity data
        """
        address = service_info.address

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

        # Get or create device instance
        if address not in self.devices:
            # Get connectable BLE device if available
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

        # Convert HA advertisement to library format
        advertisement = self._convert_advertisement_cached(service_info)

        # Build entity data from the advertisement
        return self._build_passive_bluetooth_update(
            address, service_info, advertisement
        )

    def _build_passive_bluetooth_update(
        self,
        address: str,
        service_info: BluetoothServiceInfoBleak,
        advertisement: AdvertisementData,
    ) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
        """Build PassiveBluetoothDataUpdate from advertisement data.

        Args:
            address: Device bluetooth address
            service_info: Bluetooth service information
            advertisement: Parsed advertisement data with interpretation

        Returns:
            PassiveBluetoothDataUpdate with devices, entity descriptions, names, and data
        """
        devices: dict[str | None, DeviceInfo] = {}
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
        entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

        # Create device info
        device_name = service_info.name or f"Bluetooth Device {address[-8:]}"

        devices[None] = DeviceInfo(
            name=device_name,
            manufacturer=self._get_manufacturer_name(advertisement),
            model=self._get_model_name(advertisement),
        )

        # NOTE: We intentionally do NOT add an RSSI-only sensor here.
        # RSSI is generic BLE data that any BLE monitor can expose.
        # This integration only creates entities for real SIG data
        # (interpreted manufacturer data, GATT characteristic values).

        # Process interpreted data if available
        if advertisement.interpreted_data:
            _LOGGER.debug(
                "Device %s has interpreted data from %s: %s",
                address,
                advertisement.interpreter_name,
                advertisement.interpreted_data,
            )
            self._add_interpreted_entities(
                None,
                advertisement.interpreter_name,
                advertisement.interpreted_data,
                entity_descriptions,
                entity_names,
                entity_data,
            )

        # Process service data for standard GATT characteristics
        if advertisement.ad_structures.core.service_data:
            self._add_service_data_entities(
                None,
                advertisement.ad_structures.core.service_data,
                entity_descriptions,
                entity_names,
                entity_data,
            )

        return PassiveBluetoothDataUpdate(
            devices=devices,
            entity_descriptions=entity_descriptions,
            entity_names=entity_names,
            entity_data=entity_data,
        )

    def _get_manufacturer_name(self, advertisement: AdvertisementData) -> str | None:
        """Get manufacturer name from advertisement."""
        if advertisement.ad_structures.core.manufacturer_data:
            # Get first manufacturer's company name
            for mfr_data in advertisement.ad_structures.core.manufacturer_data.values():
                if mfr_data.company and mfr_data.company.name:
                    return mfr_data.company.name
        if advertisement.interpreter_name:
            return advertisement.interpreter_name
        return None

    def _get_model_name(self, advertisement: AdvertisementData) -> str | None:
        """Get model name from advertisement."""
        # Try to extract model from local name or interpreter
        local_name = advertisement.ad_structures.core.local_name
        if local_name:
            return local_name
        return None

    def _add_interpreted_entities(
        self,
        device_id: str | None,
        interpreter_name: str | None,
        interpreted_data: object,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add entities from interpreted advertising data."""
        # Handle SIGCharacteristicData from the library
        if isinstance(interpreted_data, SIGCharacteristicData):
            self._add_sig_characteristic_entity(
                device_id,
                interpreted_data,
                entity_descriptions,
                entity_names,
                entity_data,
            )
            return

        _LOGGER.debug(
            "Unknown interpreted data type %s for device %s",
            type(interpreted_data).__name__,
            device_id,
        )

    def _add_sig_characteristic_entity(
        self,
        device_id: str | None,
        data: SIGCharacteristicData,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add entity from SIGCharacteristicData using library metadata."""
        # Get characteristic class and metadata from registry with caching
        uuid_str = str(data.uuid)
        if uuid_str not in self._char_class_cache:
            # This may block, but should be rare due to caching
            self._char_class_cache[uuid_str] = CharacteristicRegistry.get_characteristic_class_by_uuid(data.uuid)

        char_class = self._char_class_cache[uuid_str]
        if char_class is None:
            _LOGGER.debug(
                "No characteristic class found for UUID %s on device %s",
                data.uuid,
                device_id,
            )
            return

        char_instance = char_class()
        char_name = char_instance.name
        unit = char_instance.unit
        python_type = char_instance.python_type
        parsed_value = data.parsed_value

        uuid_obj = (
            data.uuid
            if isinstance(data.uuid, BluetoothUUID)
            else BluetoothUUID(data.uuid)
        )

        _LOGGER.debug(
            "Processing %s (uuid=%s, python_type=%s, unit=%s) for device %s",
            char_name,
            uuid_obj.short_form,
            python_type.__name__ if python_type else "None",
            unit,
            device_id,
        )

        # Handle based on python_type from library
        if python_type in (int, float):
            self._add_simple_entity(
                device_id,
                str(data.uuid),
                char_name,
                parsed_value,
                unit,
                entity_descriptions,
                entity_names,
                entity_data,
            )
        elif python_type is str:
            self._add_simple_entity(
                device_id,
                str(data.uuid),
                char_name,
                parsed_value,
                None,
                entity_descriptions,
                entity_names,
                entity_data,
            )
        elif hasattr(parsed_value, "__struct_fields__"):
            # Handle struct types (msgspec Struct objects)
            self._add_struct_entities(
                device_id,
                str(data.uuid),
                char_name,
                parsed_value,
                uuid_obj,
                entity_descriptions,
                entity_names,
                entity_data,
            )
        else:
            _LOGGER.debug(
                "Unhandled python_type %s for %s on device %s",
                python_type.__name__ if python_type else "None",
                char_name,
                device_id,
            )

    def _add_simple_entity(
        self,
        device_id: str | None,
        uuid: str,
        name: str,
        value: int | float | str | bool,
        unit: str | None,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add a simple single-value entity."""
        # Characteristics without a unit are metadata/diagnostic
        has_unit = bool(unit and unit.strip())
        is_diagnostic = not has_unit

        entity_key = PassiveBluetoothEntityKey(uuid, device_id)
        entity_descriptions[entity_key] = SensorEntityDescription(
            key=uuid,
            name=name,
            native_unit_of_measurement=unit if has_unit else None,
            state_class=SensorStateClass.MEASUREMENT
            if isinstance(value, (int, float)) and not is_diagnostic
            else None,
            entity_category=EntityCategory.DIAGNOSTIC
            if is_diagnostic
            else None,
        )
        entity_names[entity_key] = name
        entity_data[entity_key] = value
        _LOGGER.debug(
            "Added entity %s = %s %s (diag=%s) for device %s",
            name, value, unit or "", is_diagnostic, device_id,
        )

    def _add_struct_entities(
        self,
        device_id: str | None,
        uuid: str,
        char_name: str,
        struct_value: object,
        char_uuid: BluetoothUUID | None,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add entities from a msgspec Struct with multiple fields.

        Per-field units are resolved from the library's GSS characteristic
        spec rather than a hardcoded map.  Fields that are Enum-typed or
        that have no unit in the spec are classified as diagnostic.
        """
        from enum import Enum

        # msgspec Structs have __struct_fields__ tuple
        if not hasattr(struct_value, "__struct_fields__"):
            _LOGGER.debug(
                "Value for %s is not a struct, cannot extract fields", char_name
            )
            return

        # Resolve per-field units from the library's GSS spec
        spec_units = (
            self._get_spec_field_units_cached(char_uuid) if char_uuid else {}
        )

        for field_name in struct_value.__struct_fields__:
            raw_value = getattr(struct_value, field_name)

            # Enum-typed fields are always diagnostic metadata
            was_enum = isinstance(raw_value, Enum)
            if was_enum:
                enum_name = raw_value.name
                if enum_name is not None:
                    field_value: int | float | str | bool = (
                        enum_name.replace("_", " ").lower()
                    )
                else:
                    field_value = str(raw_value.value)
            else:
                field_value = raw_value  # type: ignore[assignment]

            # Only create entities for primitive types
            if not isinstance(field_value, (int, float, str, bool)):
                continue

            entity_key = PassiveBluetoothEntityKey(f"{uuid}_{field_name}", device_id)
            field_display_name = f"{char_name} {field_name.replace('_', ' ').title()}"

            # Resolve unit from the GSS spec (not a hardcoded map)
            is_numeric = isinstance(field_value, (int, float))
            field_unit = (
                self._match_field_unit(field_name, spec_units)
                if is_numeric
                else None
            )

            # Diagnostic: enum fields or numeric fields without a unit
            is_diagnostic = was_enum or (is_numeric and not field_unit)

            entity_descriptions[entity_key] = SensorEntityDescription(
                key=f"{uuid}_{field_name}",
                name=field_display_name,
                native_unit_of_measurement=field_unit,
                state_class=SensorStateClass.MEASUREMENT
                if is_numeric and not is_diagnostic
                else None,
                entity_category=EntityCategory.DIAGNOSTIC
                if is_diagnostic
                else None,
            )
            entity_names[entity_key] = field_display_name
            entity_data[entity_key] = field_value
            _LOGGER.debug(
                "Added struct field entity %s = %s (unit=%s, diag=%s) for device %s",
                field_display_name,
                field_value,
                field_unit or "none",
                is_diagnostic,
                device_id,
            )

    def _add_service_data_entities(
        self,
        device_id: str | None,
        service_data: dict[BluetoothUUID, bytes],
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add entities from service data using GATT characteristic metadata."""
        for service_uuid, data in service_data.items():
            # Try to parse characteristic data using the translator
            try:
                # Get characteristic info to determine how to parse
                char_info = self.translator.get_characteristic_info_by_uuid(
                    str(service_uuid)
                )
                if char_info:
                    # Parse the data
                    parsed_value = self.translator.parse_characteristic(
                        str(service_uuid), data, None
                    )

                    # Create entity key
                    entity_key = PassiveBluetoothEntityKey(
                        f"svc_{str(service_uuid).replace('-', '_')}", device_id
                    )

                    # Create entity description
                    is_numeric = isinstance(parsed_value, (int, float))
                    svc_unit = char_info.unit if is_numeric else None
                    has_unit = bool(svc_unit and svc_unit.strip())
                    is_diag = not has_unit
                    entity_descriptions[entity_key] = SensorEntityDescription(
                        key=f"svc_{service_uuid}",
                        name=char_info.name or f"Service {service_uuid}",
                        native_unit_of_measurement=svc_unit
                        if has_unit
                        else None,
                        state_class=SensorStateClass.MEASUREMENT
                        if is_numeric and not is_diag
                        else None,
                        entity_category=EntityCategory.DIAGNOSTIC
                        if is_diag
                        else None,
                    )

                    # Only store serializable values
                    if isinstance(parsed_value, (str, int, float, bool)):
                        entity_names[entity_key] = (
                            char_info.name or f"Service {service_uuid}"
                        )
                        entity_data[entity_key] = parsed_value
            except Exception as e:
                _LOGGER.debug(
                    "Could not parse service data for %s: %s", service_uuid, e
                )

    def _determine_state_class(
        self, field_name: str, value: object
    ) -> SensorStateClass | None:
        """Determine appropriate state class based on field name and value type."""
        # If the value is numeric, use measurement
        if isinstance(value, (int, float)):
            return SensorStateClass.MEASUREMENT
        return None

    async def async_start(self) -> None:
        """Start the coordinator with continuous Bluetooth discovery.

        Registers a global callback for ALL Bluetooth advertisements.
        When a new device is seen, creates a PassiveBluetoothProcessorCoordinator
        for that address to handle ongoing updates.
        """
        _LOGGER.debug("Starting Bluetooth SIG coordinator with global discovery")

        # Build excluded service/characteristic UUIDs from the library
        # Done here to avoid blocking I/O during __init__
        self._excluded_service_uuids, self._excluded_char_uuids = (
            await self.hass.async_add_executor_job(self._build_excluded_uuids)
        )

        # Pre-populate discovery-triggered set with already-configured devices
        # so we don't fire duplicate discovery flows
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if address := entry.data.get("address"):
                self._discovery_triggered.add(address)
                _LOGGER.debug(
                    "Skipping discovery for already-configured device %s",
                    address,
                )

        # Check Bluetooth scanner count
        scanner_count = bluetooth.async_scanner_count(self.hass, connectable=False)
        _LOGGER.info("Bluetooth scanners available: %d", scanner_count)

        # Register callback for ALL Bluetooth devices (connectable and non-connectable)
        # Using connectable=False matches ALL devices (including connectable ones)
        # This follows the pattern used by ibeacon and private_ble_device integrations
        # See: homeassistant/components/ibeacon/coordinator.py
        # See: homeassistant/components/private_ble_device/coordinator.py
        self._cancel_discovery = bluetooth.async_register_callback(
            self.hass,
            self._async_device_discovered,
            BluetoothCallbackMatcher(connectable=False),
            BluetoothScanningMode.PASSIVE,
        )

        _LOGGER.info("Registered global Bluetooth callback for all devices")

        # Also process any devices already discovered before we registered
        # Check both connectable and non-connectable devices
        already_discovered_connectable = list(
            bluetooth.async_discovered_service_info(self.hass, connectable=True)
        )
        already_discovered_nonconnectable = list(
            bluetooth.async_discovered_service_info(self.hass, connectable=False)
        )
        _LOGGER.info(
            "Already-discovered devices: %d connectable, %d non-connectable",
            len(already_discovered_connectable),
            len(already_discovered_nonconnectable),
        )
        # Process all discovered devices
        for service_info in (
            already_discovered_connectable + already_discovered_nonconnectable
        ):
            self._ensure_device_processor(service_info)

        _LOGGER.info(
            "Bluetooth SIG coordinator started, monitoring for parseable devices",
        )

    @callback
    def _async_device_discovered(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Handle a Bluetooth device advertisement.

        Called for every advertisement from any Bluetooth device.
        Creates a processor for new devices to enable entity creation.
        """
        _LOGGER.debug(
            "BLE advertisement: %s (name=%s, rssi=%s, change=%s)",
            service_info.address,
            service_info.name,
            service_info.rssi,
            change,
        )
        self._ensure_device_processor(service_info)

    def _has_supported_data(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Check if the device advertisement contains data we can parse.

        Returns True if the device has:
        - Service data matching known GATT characteristic UUIDs, or
        - Manufacturer data that the bluetooth-sig library can interpret
        """
        address = service_info.address

        # Check service data for known GATT characteristics
        if service_info.service_data:
            for service_uuid_str in service_info.service_data:
                # Check if this UUID matches a known characteristic
                char_info = self.translator.get_characteristic_info_by_uuid(
                    service_uuid_str
                )
                if char_info is not None:
                    _LOGGER.debug(
                        "Device %s has supported service data UUID %s",
                        address,
                        service_uuid_str,
                    )
                    return True
                else:
                    _LOGGER.debug(
                        "Device %s has unknown service data UUID %s",
                        address,
                        service_uuid_str,
                    )

        # Check if manufacturer data can be interpreted
        if service_info.manufacturer_data:
            _LOGGER.debug(
                "Device %s has manufacturer data from IDs: %s",
                address,
                list(service_info.manufacturer_data.keys()),
            )
            # Convert to library format and check if it has interpreted data
            try:
                advertisement = self._convert_advertisement_cached(service_info)
                if advertisement.interpreted_data is not None:
                    _LOGGER.debug(
                        "Device %s has interpreted manufacturer data: %s",
                        address,
                        type(advertisement.interpreted_data).__name__,
                    )
                    return True
                else:
                    _LOGGER.debug(
                        "Device %s manufacturer data not interpreted",
                        address,
                    )
            except Exception as e:
                _LOGGER.debug(
                    "Device %s failed to parse manufacturer data: %s",
                    address,
                    e,
                )
        else:
            _LOGGER.debug(
                "Device %s has no service_data or manufacturer_data",
                address,
            )

        # Check if we have GATT probe results for this device
        if address in self._gatt_probe_results:
            probe_result = self._gatt_probe_results[address]
            if probe_result.has_support():
                _LOGGER.debug(
                    "Device %s has %d parseable GATT characteristics",
                    address,
                    probe_result.parseable_count,
                )
                return True

        return False

    def _ensure_device_processor(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Check if a device has parseable data and fire a discovery flow.

        Called for each new BLE advertisement. If the device has supported
        data (from advertisement or GATT probe), fires a config flow so
        the user can confirm adding it from the Integrations page.

        For connectable devices without interpretable advertisement data,
        schedules a GATT probe to discover parseable characteristics.
        """
        address = service_info.address

        # Skip if we already fired discovery for this address
        if address in self._discovery_triggered:
            return

        # Check if we have supported data from advertisement
        has_advert_data = self._has_supported_data(service_info)

        # If no advertisement data is interpretable, try GATT probing for connectable devices
        if not has_advert_data:
            # Schedule GATT probe for connectable devices we haven't probed yet
            if (
                service_info.connectable
                and address not in self._gatt_probe_results
                and address not in self._pending_probes
                and self._probe_failures.get(address, 0) < MAX_PROBE_FAILURES
            ):
                self._pending_probes.add(address)
                self.hass.async_create_task(
                    self._async_probe_and_setup(service_info),
                    f"bluetooth_sig_probe_{address}",
                )
            return

        # Device has parseable data — fire a discovery flow
        self._fire_discovery_flow(service_info)

    @callback
    def _fire_discovery_flow(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Fire a Bluetooth discovery config flow for a parseable device."""
        address = service_info.address

        if address in self._discovery_triggered:
            return

        self._discovery_triggered.add(address)
        _LOGGER.info(
            "Firing discovery flow for parseable device %s (%s)",
            address,
            service_info.name or "unknown",
        )
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "bluetooth"},
                data=service_info,
            ),
            f"bluetooth_sig_discover_{address}",
        )

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        _LOGGER.debug("Stopping Bluetooth SIG coordinator")

        # Cancel discovery callback
        if self._cancel_discovery is not None:
            self._cancel_discovery()
            self._cancel_discovery = None

        # Clear tracked state
        self._discovery_triggered.clear()
        self.devices.clear()
