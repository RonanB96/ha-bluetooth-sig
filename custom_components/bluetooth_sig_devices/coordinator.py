"""Coordinator for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.device.device import Device
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.types.advertising import AdvertisementData
from bluetooth_sig.types.gatt_enums import ValueType
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.components.sensor import SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device_adapter import HomeAssistantBluetoothAdapter

_LOGGER = logging.getLogger(__name__)


class BluetoothSIGCoordinator:
    """Coordinator for managing Bluetooth SIG devices.

    This coordinator implements continuous auto-discovery of ALL Bluetooth devices.
    When a device advertises data that the bluetooth-sig-python library can parse,
    entities are created automatically.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.translator = BluetoothSIGTranslator()
        self.devices: dict[str, Device] = {}
        # Per-device processor coordinators keyed by address
        self._processor_coordinators: dict[
            str,
            PassiveBluetoothProcessorCoordinator[
                PassiveBluetoothDataUpdate[float | int | str | bool]
            ],
        ] = {}
        # Callback to unregister global discovery
        self._cancel_discovery: CALLBACK_TYPE | None = None
        # Entity adder callback from sensor platform
        self._async_add_entities: AddEntitiesCallback | None = None
        # Entity class to use for sensor creation
        self._entity_class: type | None = None

    def set_entity_adder(
        self,
        async_add_entities: AddEntitiesCallback,
        entity_class: type,
    ) -> None:
        """Set the callback for adding entities from sensor platform."""
        self._async_add_entities = async_add_entities
        self._entity_class = entity_class
        _LOGGER.debug("Entity adder registered for sensor platform")

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
            adapter = HomeAssistantBluetoothAdapter(address, service_info.name)
            self.devices[address] = Device(
                connection_manager=adapter,
                translator=self.translator,
            )
            _LOGGER.debug("Created new device for address %s", address)

        # Convert HA advertisement to library format
        advertisement = HomeAssistantBluetoothAdapter.convert_advertisement(
            service_info
        )

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
        device_id = address.replace(":", "").lower()

        devices[None] = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=device_name,
            connections={("bluetooth", address)},
            manufacturer=self._get_manufacturer_name(advertisement),
            model=self._get_model_name(advertisement),
        )

        # Add RSSI sensor
        if advertisement.rssi is not None:
            rssi_key = PassiveBluetoothEntityKey("rssi", device_id)
            entity_descriptions[rssi_key] = SensorEntityDescription(
                key="rssi",
                name="Signal Strength",
                native_unit_of_measurement="dBm",
                state_class=SensorStateClass.MEASUREMENT,
            )
            entity_names[rssi_key] = "Signal Strength"
            entity_data[rssi_key] = advertisement.rssi

        # Process interpreted data if available
        if advertisement.interpreted_data:
            _LOGGER.debug(
                "Device %s has interpreted data from %s: %s",
                address,
                advertisement.interpreter_name,
                advertisement.interpreted_data,
            )
            self._add_interpreted_entities(
                device_id,
                advertisement.interpreter_name,
                advertisement.interpreted_data,
                entity_descriptions,
                entity_names,
                entity_data,
            )

        # Process service data for standard GATT characteristics
        if advertisement.ad_structures.core.service_data:
            self._add_service_data_entities(
                device_id,
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
        device_id: str,
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
        device_id: str,
        data: SIGCharacteristicData,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add entity from SIGCharacteristicData using library metadata."""
        # Get characteristic class and metadata from registry
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(data.uuid)
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
        value_type = char_instance.value_type
        parsed_value = data.parsed_value

        uuid_obj = BluetoothUUID(data.uuid)

        _LOGGER.debug(
            "Processing %s (uuid=%s, value_type=%s, unit=%s) for device %s",
            char_name,
            uuid_obj.short_form,
            value_type.name,
            unit,
            device_id,
        )

        # Handle based on ValueType from library
        if value_type in (ValueType.INT, ValueType.FLOAT):
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
        elif value_type in (ValueType.VARIOUS, ValueType.BITFIELD):
            self._add_struct_entities(
                device_id,
                str(data.uuid),
                char_name,
                parsed_value,
                unit,
                entity_descriptions,
                entity_names,
                entity_data,
            )
        elif value_type == ValueType.STRING:
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
        else:
            _LOGGER.debug(
                "Unhandled value_type %s for %s on device %s",
                value_type.name,
                char_name,
                device_id,
            )

    def _add_simple_entity(
        self,
        device_id: str,
        uuid: str,
        name: str,
        value: int | float | str | bool,
        unit: str | None,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add a simple single-value entity."""
        entity_key = PassiveBluetoothEntityKey(uuid, device_id)
        entity_descriptions[entity_key] = SensorEntityDescription(
            key=uuid,
            name=name,
            native_unit_of_measurement=unit,
            state_class=SensorStateClass.MEASUREMENT
            if isinstance(value, (int, float))
            else None,
        )
        entity_names[entity_key] = name
        entity_data[entity_key] = value
        _LOGGER.debug(
            "Added entity %s = %s %s for device %s", name, value, unit or "", device_id
        )

    def _add_struct_entities(
        self,
        device_id: str,
        uuid: str,
        char_name: str,
        struct_value: object,
        unit: str | None,
        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
        entity_names: dict[PassiveBluetoothEntityKey, str | None],
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    ) -> None:
        """Add entities from a msgspec Struct with multiple fields."""
        # msgspec Structs have __struct_fields__ tuple
        if not hasattr(struct_value, "__struct_fields__"):
            _LOGGER.debug(
                "Value for %s is not a struct, cannot extract fields", char_name
            )
            return

        for field_name in struct_value.__struct_fields__:
            field_value = getattr(struct_value, field_name)
            # Only create entities for primitive types
            if not isinstance(field_value, (int, float, str, bool)):
                continue

            entity_key = PassiveBluetoothEntityKey(f"{uuid}_{field_name}", device_id)
            field_display_name = f"{char_name} {field_name.replace('_', ' ').title()}"

            entity_descriptions[entity_key] = SensorEntityDescription(
                key=f"{uuid}_{field_name}",
                name=field_display_name,
                native_unit_of_measurement=unit
                if isinstance(field_value, (int, float))
                else None,
                state_class=SensorStateClass.MEASUREMENT
                if isinstance(field_value, (int, float))
                else None,
            )
            entity_names[entity_key] = field_display_name
            entity_data[entity_key] = field_value
            _LOGGER.debug(
                "Added struct field entity %s = %s for device %s",
                field_display_name,
                field_value,
                device_id,
            )

    def _add_service_data_entities(
        self,
        device_id: str,
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
                    entity_descriptions[entity_key] = SensorEntityDescription(
                        key=f"svc_{service_uuid}",
                        name=char_info.name or f"Service {service_uuid}",
                        native_unit_of_measurement=char_info.unit,
                        state_class=SensorStateClass.MEASUREMENT,
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
        for service_info in already_discovered_connectable + already_discovered_nonconnectable:
            self._ensure_device_processor(service_info)

        _LOGGER.info(
            "Bluetooth SIG coordinator started, tracking %d devices",
            len(self._processor_coordinators),
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
                advertisement = HomeAssistantBluetoothAdapter.convert_advertisement(
                    service_info
                )
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

        return False

    def _ensure_device_processor(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Ensure a processor coordinator exists for this device address.

        If this is the first time seeing this address and the device has
        supported data, creates a new PassiveBluetoothProcessorCoordinator
        and registers entity listeners.
        """
        address = service_info.address

        # Skip if we already have a processor for this address
        if address in self._processor_coordinators:
            return

        # Skip if sensor platform hasn't registered yet
        if self._async_add_entities is None or self._entity_class is None:
            _LOGGER.debug("Skipping device %s - sensor platform not ready yet", address)
            return

        # Only create processor for devices with data we can parse
        if not self._has_supported_data(service_info):
            return

        _LOGGER.debug("Creating processor coordinator for new device %s", address)

        # Create processor coordinator for this specific device address
        processor_coordinator: PassiveBluetoothProcessorCoordinator[
            PassiveBluetoothDataUpdate[float | int | str | bool]
        ] = PassiveBluetoothProcessorCoordinator(
            self.hass,
            _LOGGER,
            address=address,
            mode=BluetoothScanningMode.PASSIVE,
            update_method=self.update_device,
        )

        # Create data processor that passes through the update directly
        processor: PassiveBluetoothDataProcessor[
            float | int | str | bool,
            PassiveBluetoothDataUpdate[float | int | str | bool],
        ] = PassiveBluetoothDataProcessor(lambda x: x)

        # Register entity listener so new entities are created automatically
        self.entry.async_on_unload(
            processor.async_add_entities_listener(
                self._entity_class, self._async_add_entities
            )
        )

        # Register the processor with the coordinator
        self.entry.async_on_unload(
            processor_coordinator.async_register_processor(processor)
        )

        # Start the processor coordinator
        self.entry.async_on_unload(processor_coordinator.async_start())

        # Store for tracking
        self._processor_coordinators[address] = processor_coordinator

        _LOGGER.info("Now tracking Bluetooth device %s", address)

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        _LOGGER.debug("Stopping Bluetooth SIG coordinator")

        # Cancel discovery callback
        if self._cancel_discovery is not None:
            self._cancel_discovery()
            self._cancel_discovery = None

        # Clear tracked state
        self._processor_coordinators.clear()
        self.devices.clear()
