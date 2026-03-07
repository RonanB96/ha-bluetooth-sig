"""The Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN
from .coordinator import BluetoothSIGCoordinator

type BluetoothSIGConfigEntry = ConfigEntry[BluetoothSIGCoordinator]

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _is_hub_entry(entry: ConfigEntry) -> bool:
    """Return True if this is the discovery hub entry (no device address)."""
    return CONF_ADDRESS not in entry.data


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
    """Set up Bluetooth SIG Devices from a config entry.

    Hub entries (no address) start the coordinator for global discovery.
    Device entries (with address) forward to sensor platform for entities.
    """
    # Verify Bluetooth is available
    if not bluetooth.async_scanner_count(hass, connectable=False):
        raise ConfigEntryNotReady("No Bluetooth scanner available")

    if _is_hub_entry(entry):
        return await _async_setup_hub_entry(hass, entry)

    return await _async_setup_device_entry(hass, entry)


async def _async_setup_hub_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the discovery hub entry."""
    poll_seconds = entry.options.get(
        CONF_POLL_INTERVAL, int(DEFAULT_POLL_INTERVAL.total_seconds())
    )

    # Pre-warm bluetooth-sig registries before creating the coordinator.
    await hass.async_add_executor_job(BluetoothSIGCoordinator.prewarm_registries)

    coordinator = BluetoothSIGCoordinator(hass, entry, poll_interval=poll_seconds)

    # Store coordinator centrally so device entries can access it
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinator"] = coordinator

    # Store in runtime_data too
    entry.runtime_data = coordinator

    # Reload integration when options change (e.g. poll_interval)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Start coordinator after Home Assistant is fully started
    @callback
    def _async_start_coordinator(event: Event | None = None) -> None:
        """Start the coordinator after HA is started."""
        hass.async_create_task(coordinator.async_start())

    if hass.is_running:
        await coordinator.async_start()
    else:
        # Only register the listener removal if we actually add the listener
        listener_unsub = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _async_start_coordinator
        )
        entry.async_on_unload(listener_unsub)

    return True


async def _async_setup_device_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a per-device entry with its own processor coordinator."""
    # Get the hub coordinator — it holds the translator and device instances
    hub_data = hass.data.get(DOMAIN, {})
    coordinator = hub_data.get("coordinator")
    if coordinator is None:
        raise ConfigEntryNotReady("Discovery hub not yet loaded — will retry")

    # Store coordinator reference for use by sensor platform
    entry.runtime_data = coordinator

    # Forward to sensor platform which creates the processor and entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Device entry set up for %s (%s)",
        entry.data.get(CONF_ADDRESS),
        entry.title,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if _is_hub_entry(entry):
        # Stop coordinator and clean up central data
        await entry.runtime_data.async_stop()
        hass.data.pop(DOMAIN, None)
        return True

    # Device entry — unload sensor platform
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: BluetoothSIGCoordinator | None = hass.data.get(DOMAIN, {}).get(
            "coordinator"
        )
        if coordinator and entry.unique_id:
            coordinator.remove_device(entry.unique_id)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow device removal only when the device is no longer active.

    Checks device_entry.connections (not identifiers) because the passive
    BLE framework registers devices with ("bluetooth", address) connections.
    """
    hub_data = hass.data.get(DOMAIN, {})
    coordinator = hub_data.get("coordinator")
    if coordinator is None:
        return True

    for conn_type, address in device_entry.connections:
        if conn_type == "bluetooth" and coordinator.is_device_active(address):
            return False

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: BluetoothSIGConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
