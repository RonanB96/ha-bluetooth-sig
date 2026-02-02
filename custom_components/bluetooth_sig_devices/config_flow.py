"""Config flow for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import async_scanner_count
from homeassistant.config_entries import ConfigFlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class BluetoothSIGDevicesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bluetooth SIG Devices."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Check if already configured
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # Check if Bluetooth is available
        if not async_scanner_count(self.hass, connectable=False):
            return self.async_abort(reason="bluetooth_not_available")

        if user_input is not None:
            # Create the config entry
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

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(import_data)
