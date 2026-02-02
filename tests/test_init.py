"""Tests for the integration setup."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices import (
    async_setup_entry,
    async_unload_entry,
)
from custom_components.bluetooth_sig_devices.const import DOMAIN


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Bluetooth SIG Devices",
        data={},
        source="user",
        unique_id=DOMAIN,
        entry_id="test_entry_id",
    )


async def test_async_setup_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test setting up the integration."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch("homeassistant.components.bluetooth.async_scanner_count", return_value=1),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ) as mock_forward,
    ):
        result = await async_setup_entry(hass, mock_config_entry)

        assert result is True
        assert DOMAIN in hass.data
        assert mock_config_entry.entry_id in hass.data[DOMAIN]

        # Check that sensor platform was forwarded
        mock_forward.assert_called_once()
        call_args = mock_forward.call_args
        assert call_args[0][0] == mock_config_entry
        assert Platform.SENSOR in call_args[0][1]


async def test_async_unload_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test unloading the integration."""
    mock_config_entry.add_to_hass(hass)

    # First set up
    with (
        patch("homeassistant.components.bluetooth.async_scanner_count", return_value=1),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        await async_setup_entry(hass, mock_config_entry)

    # Then unload
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})

        # Check that platforms were unloaded
        mock_unload.assert_called_once()
        call_args = mock_unload.call_args
        assert call_args[0][0] == mock_config_entry
        assert Platform.SENSOR in call_args[0][1]


async def test_async_setup_entry_coordinator_created(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that coordinator is created during setup."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch("homeassistant.components.bluetooth.async_scanner_count", return_value=1),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        await async_setup_entry(hass, mock_config_entry)

        # Check coordinator exists in hass.data
        assert DOMAIN in hass.data
        assert mock_config_entry.entry_id in hass.data[DOMAIN]
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]

        # Check it's the right type
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        assert isinstance(coordinator, BluetoothSIGCoordinator)
