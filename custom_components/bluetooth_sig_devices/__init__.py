"""The Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import BluetoothSIGCoordinator

type BluetoothSIGConfigEntry = ConfigEntry[BluetoothSIGCoordinator]

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Bluetooth SIG Devices from YAML configuration."""
    if DOMAIN in config:
        # Trigger import flow to create a config entry
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=config.get(DOMAIN, {}),
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bluetooth SIG Devices from a config entry."""
    # Verify Bluetooth is available
    if not bluetooth.async_scanner_count(hass, connectable=False):
        raise ConfigEntryNotReady("No Bluetooth scanner available")

    # Create global coordinator for managing all devices
    coordinator = BluetoothSIGCoordinator(hass, entry)

    # Store coordinator in runtime_data (Bronze requirement)
    entry.runtime_data = coordinator

    # Forward setup to platforms first
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start coordinator after Home Assistant is fully started
    # This ensures Bluetooth discovery has had time to populate
    @callback
    def _async_start_coordinator(event: Event | None = None) -> None:
        """Start the coordinator after HA is started."""
        hass.async_create_task(coordinator.async_start())

    if hass.is_running:
        # HA already started, start coordinator now
        await coordinator.async_start()
    else:
        # Wait for HA to fully start before starting coordinator
        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _async_start_coordinator
            )
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Stop coordinator
        await entry.runtime_data.async_stop()

    return unload_ok
