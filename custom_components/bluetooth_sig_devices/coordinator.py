"""Coordinator for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.device.device import Device
from bluetooth_sig.types.advertising.result import AdvertisementData
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.components.sensor import SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription

from .const import DOMAIN
from .device_adapter import HomeAssistantBluetoothAdapter

_LOGGER = logging.getLogger(__name__)


class BluetoothSIGCoordinator:
    """Coordinator for managing Bluetooth SIG devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.translator = BluetoothSIGTranslator()
        self.devices: dict[str, Device] = {}
        self.processors: list[
            PassiveBluetoothProcessorCoordinator[
                PassiveBluetoothDataUpdate[float | int | str | bool]
            ]
        ] = []

    def register_processor(
        self,
        processor: PassiveBluetoothProcessorCoordinator[
            PassiveBluetoothDataUpdate[float | int | str | bool]
        ],
    ) -> None:
        """Register a processor coordinator."""
        self.processors.append(processor)

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
                entity_registry_enabled_default=False,
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
        """Add entities from interpreted advertising data.

        Uses reflection to extract fields from the interpreted data object.
        """
        if not hasattr(interpreted_data, "__dict__"):
            _LOGGER.debug("Interpreted data has no __dict__, cannot extract fields")
            return

        # Use reflection to extract all fields from the interpreted data
        for field_name, value in interpreted_data.__dict__.items():
            if field_name.startswith("_"):
                # Skip private fields
                continue

            # Only include serializable types
            if not isinstance(value, (str, int, float, bool)):
                continue

            # Create entity key
            entity_key = PassiveBluetoothEntityKey(field_name, device_id)

            # Create entity description based on field type and name
            entity_descriptions[entity_key] = SensorEntityDescription(
                key=field_name,
                name=field_name.replace("_", " ").title(),
                state_class=self._determine_state_class(field_name, value),
            )

            # Format field name as entity name
            entity_names[entity_key] = field_name.replace("_", " ").title()

            # Store the value
            entity_data[entity_key] = value

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
        """Start the coordinator."""
        _LOGGER.debug("Starting Bluetooth SIG coordinator")

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        _LOGGER.debug("Stopping Bluetooth SIG coordinator")
        self.devices.clear()
