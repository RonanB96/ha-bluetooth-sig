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

from . import _is_hub_entry
from .const import BLEAddress
from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetooth SIG sensor platform.

    Hub entries (no ``address`` in data) have no sensors.
    Device entries create a PassiveBluetoothProcessorCoordinator via the
    shared hub coordinator.
    """
    # Hub entry — no sensors
    if _is_hub_entry(entry):
        return

    coordinator: BluetoothSIGCoordinator = entry.runtime_data
    address: BLEAddress = entry.data["address"]

    coordinator.create_device_processor(
        address, entry, async_add_entities, BluetoothSIGSensorEntity
    )

    _LOGGER.info("Bluetooth SIG sensor platform set up for device %s", address)


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
    _unavailable_logged: bool = False

    @property
    def available(self) -> bool:
        """Return True if entity is available, logging transitions once."""
        is_available = super().available
        if not is_available and not self._unavailable_logged:
            _LOGGER.info(
                "Bluetooth device for entity %s is unavailable",
                self.entity_description.key,
            )
            self._unavailable_logged = True
        elif is_available and self._unavailable_logged:
            _LOGGER.info(
                "Bluetooth device for entity %s is back online",
                self.entity_description.key,
            )
            self._unavailable_logged = False
        return is_available

    @property
    def native_value(self) -> float | int | str | bool | None:
        """Return the native value of the sensor."""
        value = self.processor.entity_data.get(self.entity_key)
        if isinstance(value, (float, int, str, bool)):
            return value
        return None
