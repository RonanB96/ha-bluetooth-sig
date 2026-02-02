"""Sensor platform for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    async_discovered_service_info,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothProcessorCoordinator,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetooth SIG sensor platform."""
    coordinator: BluetoothSIGCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Get all currently discovered Bluetooth devices
    discovered_devices = async_discovered_service_info(hass, connectable=False)

    # Create processors for each discovered device
    processors_created = set()

    for service_info in discovered_devices:
        address = service_info.address

        if address not in processors_created:
            # Create a processor coordinator for this device
            processor_coordinator: PassiveBluetoothProcessorCoordinator[
                PassiveBluetoothDataUpdate[float | int | str | bool]
            ] = PassiveBluetoothProcessorCoordinator(
                hass,
                _LOGGER,
                address=address,
                mode=BluetoothScanningMode.ACTIVE,
                update_method=coordinator.update_device,
            )

            # Create processor that passes through the data update
            processor: PassiveBluetoothDataProcessor[
                float | int | str | bool,
                PassiveBluetoothDataUpdate[float | int | str | bool],
            ] = PassiveBluetoothDataProcessor(lambda x: x)

            # Register entity listener
            entry.async_on_unload(
                processor.async_add_entities_listener(
                    BluetoothSIGSensorEntity, async_add_entities
                )
            )

            # Register processor with coordinator
            entry.async_on_unload(
                processor_coordinator.async_register_processor(processor)
            )

            # Start the coordinator (only after all platforms have subscribed)
            entry.async_on_unload(processor_coordinator.async_start())

            # Store the coordinator
            coordinator.register_processor(processor_coordinator)

            processors_created.add(address)
            _LOGGER.debug("Created processor for device %s", address)

    _LOGGER.info(
        "Bluetooth SIG sensor platform set up with %d devices",
        len(processors_created),
    )


class BluetoothSIGSensorEntity(
    PassiveBluetoothProcessorEntity[
        PassiveBluetoothDataProcessor[
            float | int | str | bool,
            PassiveBluetoothDataUpdate[float | int | str | bool],
        ]
    ],
    SensorEntity,
):
    """Representation of a Bluetooth SIG sensor."""

    @property
    def native_value(self) -> float | int | str | bool | None:
        """Return the native value of the sensor."""
        value = self.processor.entity_data.get(self.entity_key)
        if isinstance(value, (float, int, str, bool)):
            return value
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Entity is available if we have data for it
        return self.processor.entity_data.get(self.entity_key) is not None
