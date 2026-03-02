"""The Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN
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
    poll_seconds = entry.options.get(
        CONF_POLL_INTERVAL, int(DEFAULT_POLL_INTERVAL.total_seconds())
    )
    coordinator = BluetoothSIGCoordinator(hass, entry, poll_interval=poll_seconds)

    # Store coordinator in runtime_data (Bronze requirement)
    entry.runtime_data = coordinator

    # Forward setup to platforms first
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload integration when options change (e.g. poll_interval)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

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


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: BluetoothSIGConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removal of a device from the device registry.

    For passive BLE discovery, we can never be certain a device is permanently
    gone (vs. temporarily out of range), so we always permit manual deletion.
    The device will be re-added automatically if it starts advertising again.
    """
    return not any(
        identifier[1] in config_entry.runtime_data._processor_coordinators
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    )


async def _async_options_updated(
    hass: HomeAssistant, entry: BluetoothSIGConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
