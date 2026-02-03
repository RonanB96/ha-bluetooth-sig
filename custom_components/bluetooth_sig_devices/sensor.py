"""Sensor platform for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetooth SIG sensor platform.

    Registers the entity adder with the coordinator so that new devices
    discovered via Bluetooth will automatically have sensors created.
    """
    coordinator: BluetoothSIGCoordinator = entry.runtime_data

    # Register entity creation callback with coordinator
    # The coordinator will call async_add_entities when new devices are discovered
    coordinator.set_entity_adder(async_add_entities, BluetoothSIGSensorEntity)

    _LOGGER.info("Bluetooth SIG sensor platform registered for auto-discovery")


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

    _attr_has_entity_name = True

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
