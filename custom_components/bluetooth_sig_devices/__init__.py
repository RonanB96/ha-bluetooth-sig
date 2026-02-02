"""The Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bluetooth SIG Devices from a config entry."""
    # Verify Bluetooth is available
    if not bluetooth.async_scanner_count(hass, connectable=False):
        raise ConfigEntryNotReady("No Bluetooth scanner available")

    # Create global coordinator for managing all devices
    coordinator = BluetoothSIGCoordinator(hass, entry)

    # Store coordinator in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms first
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start coordinator after platforms have been set up
    # This allows platforms to register their processors
    await coordinator.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Stop coordinator
        coordinator: BluetoothSIGCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_stop()

        # Remove coordinator from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
