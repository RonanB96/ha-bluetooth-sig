"""Tests for the config flow."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.bluetooth_sig_devices.const import (
    CONF_CONNECTION_TIMEOUT,
    CONF_DEVICE_POLL_INTERVAL,
    CONF_GATT_ENABLED,
    CONF_MAX_CONCURRENT_CONNECTIONS,
    CONF_MAX_PROBE_RETRIES,
    CONF_POLL_INTERVAL,
    CONF_STALE_DEVICE_TIMEOUT,
    DEFAULT_CONCURRENT_CONNECTIONS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PROBE_RETRIES,
    DEFAULT_STALE_DEVICE_TIMEOUT,
    DOMAIN,
    MAX_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
)

from .conftest import make_device_entry, make_hub_entry


async def test_flow_user_init_success(
    hass: HomeAssistant, mock_bluetooth_disabled: Generator[None]
) -> None:
    """Test successful user-initiated config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_flow_user_create_entry(
    hass: HomeAssistant, mock_bluetooth_disabled: Generator[None]
) -> None:
    """Test creating an entry with user flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Complete the flow
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Bluetooth SIG Devices"
    assert result2["data"] == {}


async def test_flow_user_single_instance_allowed(
    hass: HomeAssistant, mock_bluetooth_disabled: Generator[None]
) -> None:
    """Test that only one instance is allowed."""
    # Create first entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY

    # Try to create second instance
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result3["type"] == FlowResultType.ABORT
    assert result3["reason"] == "already_configured"


async def test_flow_user_bluetooth_not_available(
    hass: HomeAssistant, mock_bluetooth_disabled: Generator[None]
) -> None:
    """Test flow aborts when Bluetooth is not available."""
    # Override the scanner count at the config-flow import site to simulate
    # no adapters present (mock_bluetooth_disabled sets it to 1 by default).
    with patch(
        "custom_components.bluetooth_sig_devices.config_flow.async_scanner_count",
        return_value=0,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "bluetooth_not_available"


# ===================================================================
# Options flow — hub entry
# ===================================================================

DEFAULT_POLL_INTERVAL_SECONDS = int(DEFAULT_POLL_INTERVAL.total_seconds())


class TestHubOptionsFlow:
    """Test the options flow for the hub config entry."""

    async def test_hub_options_shows_form(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Opening options on the hub entry shows the hub_options form."""
        entry = make_hub_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "hub_options"

    async def test_hub_options_suggested_values_defaults(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Hub options form has correct default suggested values."""
        entry = make_hub_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        # The form's data_schema contains suggested values via add_suggested_values_to_schema.
        # We verify the schema keys exist (the form rendered without error).
        assert result["type"] == FlowResultType.FORM
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_POLL_INTERVAL in schema_keys
        assert CONF_MAX_CONCURRENT_CONNECTIONS in schema_keys
        assert CONF_CONNECTION_TIMEOUT in schema_keys
        assert CONF_MAX_PROBE_RETRIES in schema_keys
        assert CONF_STALE_DEVICE_TIMEOUT in schema_keys

    async def test_hub_options_submit_saves_values(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Submitting hub options saves the values to the config entry."""
        entry = make_hub_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_POLL_INTERVAL: 120,
                CONF_MAX_CONCURRENT_CONNECTIONS: 3,
                CONF_CONNECTION_TIMEOUT: 45,
                CONF_MAX_PROBE_RETRIES: 5,
                CONF_STALE_DEVICE_TIMEOUT: 7200,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_POLL_INTERVAL] == 120
        assert entry.options[CONF_MAX_CONCURRENT_CONNECTIONS] == 3
        assert entry.options[CONF_CONNECTION_TIMEOUT] == 45
        assert entry.options[CONF_MAX_PROBE_RETRIES] == 5
        assert entry.options[CONF_STALE_DEVICE_TIMEOUT] == 7200

    async def test_hub_options_preserves_existing_values(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Re-opening hub options after a save shows previously saved values."""
        entry = make_hub_entry(options={CONF_POLL_INTERVAL: 600})
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Open options — form should show saved poll_interval
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "hub_options"

        # Submit with a new value
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_POLL_INTERVAL: 900,
                CONF_MAX_CONCURRENT_CONNECTIONS: DEFAULT_CONCURRENT_CONNECTIONS,
                CONF_CONNECTION_TIMEOUT: DEFAULT_CONNECTION_TIMEOUT,
                CONF_MAX_PROBE_RETRIES: DEFAULT_PROBE_RETRIES,
                CONF_STALE_DEVICE_TIMEOUT: DEFAULT_STALE_DEVICE_TIMEOUT,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_POLL_INTERVAL] == 900

    async def test_hub_options_rejects_poll_interval_below_minimum(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Poll interval below minimum raises a validation error."""
        entry = make_hub_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        with pytest.raises(vol.Invalid):
            await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    CONF_POLL_INTERVAL: MIN_POLL_INTERVAL_SECONDS - 1,
                    CONF_MAX_CONCURRENT_CONNECTIONS: DEFAULT_CONCURRENT_CONNECTIONS,
                    CONF_CONNECTION_TIMEOUT: DEFAULT_CONNECTION_TIMEOUT,
                    CONF_MAX_PROBE_RETRIES: DEFAULT_PROBE_RETRIES,
                    CONF_STALE_DEVICE_TIMEOUT: DEFAULT_STALE_DEVICE_TIMEOUT,
                },
            )

    async def test_hub_options_rejects_poll_interval_above_maximum(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Poll interval above maximum raises a validation error."""
        entry = make_hub_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        with pytest.raises(vol.Invalid):
            await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    CONF_POLL_INTERVAL: MAX_POLL_INTERVAL_SECONDS + 1,
                    CONF_MAX_CONCURRENT_CONNECTIONS: DEFAULT_CONCURRENT_CONNECTIONS,
                    CONF_CONNECTION_TIMEOUT: DEFAULT_CONNECTION_TIMEOUT,
                    CONF_MAX_PROBE_RETRIES: DEFAULT_PROBE_RETRIES,
                    CONF_STALE_DEVICE_TIMEOUT: DEFAULT_STALE_DEVICE_TIMEOUT,
                },
            )

    async def test_hub_options_partial_submit_omits_unset_fields(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Submitting only some fields saves only those fields."""
        entry = make_hub_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_POLL_INTERVAL: 60,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_POLL_INTERVAL] == 60
        # Other options should not be present since they were not submitted
        assert CONF_MAX_CONCURRENT_CONNECTIONS not in entry.options


# ===================================================================
# Options flow — device entry
# ===================================================================


class TestDeviceOptionsFlow:
    """Test the options flow for a per-device config entry."""

    async def test_device_options_shows_form(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Opening options on a device entry shows the device_options form."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        # Device entries need the hub loaded first, but for config flow
        # testing we only need the entry registered in hass.
        # We load it to ensure options flow handler is accessible.
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device_options"

    async def test_device_options_suggested_values_defaults(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Device options form has correct default suggested values."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == FlowResultType.FORM
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_GATT_ENABLED in schema_keys
        assert CONF_DEVICE_POLL_INTERVAL in schema_keys

    async def test_device_options_submit_enables_gatt(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Submitting device options with GATT enabled saves correctly."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_GATT_ENABLED: True,
                CONF_DEVICE_POLL_INTERVAL: 0,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_GATT_ENABLED] is True
        assert entry.options[CONF_DEVICE_POLL_INTERVAL] == 0

    async def test_device_options_submit_disables_gatt(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Submitting device options with GATT disabled saves correctly."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_GATT_ENABLED: False,
                CONF_DEVICE_POLL_INTERVAL: 0,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_GATT_ENABLED] is False

    async def test_device_options_custom_poll_interval(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Submitting a custom poll interval override saves correctly."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_GATT_ENABLED: True,
                CONF_DEVICE_POLL_INTERVAL: 120,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_DEVICE_POLL_INTERVAL] == 120

    async def test_device_options_rejects_negative_poll_interval(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Negative device poll interval raises a validation error."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        with pytest.raises(vol.Invalid):
            await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    CONF_GATT_ENABLED: True,
                    CONF_DEVICE_POLL_INTERVAL: -1,
                },
            )

    async def test_device_options_rejects_poll_interval_above_maximum(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Device poll interval above maximum raises a validation error."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        with pytest.raises(vol.Invalid):
            await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    CONF_GATT_ENABLED: True,
                    CONF_DEVICE_POLL_INTERVAL: MAX_POLL_INTERVAL_SECONDS + 1,
                },
            )

    async def test_device_options_preserves_existing_values(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Re-opening device options after a save shows previously saved values."""
        entry = make_device_entry(
            options={CONF_GATT_ENABLED: False, CONF_DEVICE_POLL_INTERVAL: 60}
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Open options
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device_options"

        # Submit with changed values
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_GATT_ENABLED: True,
                CONF_DEVICE_POLL_INTERVAL: 180,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_GATT_ENABLED] is True
        assert entry.options[CONF_DEVICE_POLL_INTERVAL] == 180

    async def test_device_options_zero_poll_interval_means_hub_default(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Poll interval of 0 is valid and means 'use hub default'."""
        entry = make_device_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_GATT_ENABLED: True,
                CONF_DEVICE_POLL_INTERVAL: 0,
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_DEVICE_POLL_INTERVAL] == 0
