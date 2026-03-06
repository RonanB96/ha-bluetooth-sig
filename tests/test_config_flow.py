"""Tests for the config flow."""

from collections.abc import Generator
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.bluetooth_sig_devices.const import DOMAIN


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
