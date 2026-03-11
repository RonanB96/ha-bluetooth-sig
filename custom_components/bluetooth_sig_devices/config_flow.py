"""Config flow for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import async_scanner_count
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow

from .const import (
    CONF_CONNECTION_TIMEOUT,
    CONF_DEVICE_POLL_INTERVAL,
    CONF_GATT_ENABLED,
    CONF_MAX_CONCURRENT_CONNECTIONS,
    CONF_MAX_PROBE_RETRIES,
    CONF_POLL_INTERVAL,
    CONF_STALE_DEVICE_TIMEOUT,
    DEFAULT_CONCURRENT_CONNECTIONS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_PROBE_RETRIES,
    DEFAULT_STALE_DEVICE_TIMEOUT,
    DOMAIN,
    MAX_CONCURRENT_CONNECTIONS,
    MAX_CONNECTION_TIMEOUT,
    MAX_POLL_INTERVAL_SECONDS,
    MAX_PROBE_RETRIES,
    MAX_STALE_DEVICE_TIMEOUT,
    MIN_CONCURRENT_CONNECTIONS,
    MIN_CONNECTION_TIMEOUT,
    MIN_POLL_INTERVAL_SECONDS,
    MIN_PROBE_RETRIES,
    MIN_STALE_DEVICE_TIMEOUT,
    DiscoveryData,
)

_LOGGER = logging.getLogger(__name__)


class BluetoothSIGDevicesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bluetooth SIG Devices."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None
        self._discovered_characteristics: str = ""
        self._discovered_manufacturer: str = ""
        self._discovered_rssi: int | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Return the options flow handler."""
        return BluetoothSIGDevicesOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — create the hub entry.

        The hub entry has no device ``address`` in its data.  It starts
        the scanner coordinator which discovers devices and fires
        per-device discovery flows.
        """
        # Only one hub entry is allowed
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Check if Bluetooth is available
        if not async_scanner_count(self.hass, connectable=False):
            return self.async_abort(reason="bluetooth_not_available")

        if user_input is not None:
            return self.async_create_entry(
                title="Bluetooth SIG Devices",
                data={},
            )

        # Show confirmation form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": "Bluetooth SIG Devices",
            },
        )

    async def async_step_import(
        self, import_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle import from configuration.yaml."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if not async_scanner_count(self.hass, connectable=False):
            return self.async_abort(reason="bluetooth_not_available")

        return self.async_create_entry(
            title="Bluetooth SIG Devices",
            data={},
        )

    # ------------------------------------------------------------------
    # Standard discovery flow — triggered by the hub coordinator
    # ------------------------------------------------------------------

    async def async_step_integration_discovery(
        self,
        discovery_info: DiscoveryData,  # type: ignore[override]
    ) -> ConfigFlowResult:
        """Handle a device discovered by the hub coordinator.

        The coordinator calls ``discovery_flow.async_create_flow()``
        with ``source=integration_discovery`` and ``data`` containing
        the BLE address and device name.
        """
        address: str = discovery_info["address"]
        name: str = discovery_info.get("name") or f"Bluetooth Device {address[-8:]}"
        characteristics: str = discovery_info.get("characteristics", "")
        manufacturer: str = discovery_info.get("manufacturer", "")
        rssi: int | None = discovery_info.get("rssi")

        _LOGGER.info(
            "Discovery flow received for device %s (%s)",
            address,
            name,
        )

        # One config entry per BLE address
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self._discovered_address = address
        self._discovered_name = name
        self._discovered_characteristics = characteristics
        self._discovered_manufacturer = manufacturer
        self._discovered_rssi = rssi

        # Title shown in the "Discovered" list
        self.context["title_placeholders"] = {"name": name}

        return await self.async_step_integration_discovery_confirm()

    async def async_step_integration_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm addition of a discovered Bluetooth SIG device."""
        assert self._discovered_address is not None
        assert self._discovered_name is not None

        if user_input is not None:
            _LOGGER.info(
                "User confirmed device %s (%s) — creating config entry",
                self._discovered_address,
                self._discovered_name,
            )
            return self.async_create_entry(
                title=self._discovered_name,
                data={"address": self._discovered_address},
            )

        return self.async_show_form(
            step_id="integration_discovery_confirm",
            description_placeholders={
                "name": self._discovered_name,
                "address": self._discovered_address,
                "manufacturer": (
                    f"\nManufacturer: **{self._discovered_manufacturer}**"
                    if self._discovered_manufacturer
                    else ""
                ),
                "rssi": (
                    f"\nSignal strength: **{self._discovered_rssi} dBm**"
                    if self._discovered_rssi is not None
                    else ""
                ),
                "characteristics": self._discovered_characteristics
                or "Unknown (will be detected after setup)",
            },
        )


class BluetoothSIGDevicesOptionsFlow(OptionsFlow):
    """Handle options for Bluetooth SIG Devices."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Route to hub or device options."""
        if "address" in self.config_entry.data:
            return await self.async_step_device_options(user_input)
        return await self.async_step_hub_options(user_input)

    async def async_step_hub_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage hub-level options.

        Configures global poll interval, connection concurrency, timeouts,
        probe retries, and stale device cleanup.
        """
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_POLL_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_POLL_INTERVAL_SECONDS,
                        max=MAX_POLL_INTERVAL_SECONDS,
                    ),
                ),
                vol.Optional(CONF_MAX_CONCURRENT_CONNECTIONS): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_CONCURRENT_CONNECTIONS,
                        max=MAX_CONCURRENT_CONNECTIONS,
                    ),
                ),
                vol.Optional(CONF_CONNECTION_TIMEOUT): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_CONNECTION_TIMEOUT,
                        max=MAX_CONNECTION_TIMEOUT,
                    ),
                ),
                vol.Optional(CONF_MAX_PROBE_RETRIES): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_PROBE_RETRIES,
                        max=MAX_PROBE_RETRIES,
                    ),
                ),
                vol.Optional(CONF_STALE_DEVICE_TIMEOUT): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_STALE_DEVICE_TIMEOUT,
                        max=MAX_STALE_DEVICE_TIMEOUT,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="hub_options",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_POLL_INTERVAL: opts.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS
                    ),
                    CONF_MAX_CONCURRENT_CONNECTIONS: opts.get(
                        CONF_MAX_CONCURRENT_CONNECTIONS,
                        DEFAULT_CONCURRENT_CONNECTIONS,
                    ),
                    CONF_CONNECTION_TIMEOUT: opts.get(
                        CONF_CONNECTION_TIMEOUT,
                        DEFAULT_CONNECTION_TIMEOUT,
                    ),
                    CONF_MAX_PROBE_RETRIES: opts.get(
                        CONF_MAX_PROBE_RETRIES, DEFAULT_PROBE_RETRIES
                    ),
                    CONF_STALE_DEVICE_TIMEOUT: opts.get(
                        CONF_STALE_DEVICE_TIMEOUT, DEFAULT_STALE_DEVICE_TIMEOUT
                    ),
                },
            ),
        )

    async def async_step_device_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage per-device options.

        Allows enabling/disabling GATT connections and overriding the
        hub poll interval for this specific device.
        """
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_GATT_ENABLED): bool,
                vol.Optional(CONF_DEVICE_POLL_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=0,
                        max=MAX_POLL_INTERVAL_SECONDS,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="device_options",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_GATT_ENABLED: opts.get(CONF_GATT_ENABLED, True),
                    CONF_DEVICE_POLL_INTERVAL: opts.get(CONF_DEVICE_POLL_INTERVAL, 0),
                },
            ),
        )
