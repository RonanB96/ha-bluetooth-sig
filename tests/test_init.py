"""Tests for the integration setup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices import (
    async_remove_config_entry_device,
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
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
    ):
        result = await async_setup_entry(hass, mock_config_entry)

        assert result is True
        # Check coordinator exists in runtime_data (Bronze requirement)
        assert mock_config_entry.runtime_data is not None

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
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
            return_value=[],
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
        # runtime_data is managed by HA, we just verify unload succeeded

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
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
    ):
        await async_setup_entry(hass, mock_config_entry)

        # Check coordinator exists in runtime_data (Bronze requirement)
        coordinator = mock_config_entry.runtime_data
        assert coordinator is not None

        # Check it's the right type
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        assert isinstance(coordinator, BluetoothSIGCoordinator)


class TestAsyncRemoveConfigEntryDevice:
    """Tests for async_remove_config_entry_device (stale-devices rule)."""

    def _make_config_entry(self, active_addresses: list[str]) -> MagicMock:
        """Return a mock config entry whose coordinator tracks given addresses."""
        coordinator = MagicMock()
        coordinator._processor_coordinators = {
            addr: MagicMock() for addr in active_addresses
        }
        entry = MagicMock()
        entry.runtime_data = coordinator
        return entry

    def _make_device_entry(self, domain: str, identifier: str) -> MagicMock:
        """Return a mock device entry with a single identifier."""
        device_entry = MagicMock()
        device_entry.identifiers = {(domain, identifier)}
        return device_entry

    async def test_allows_removal_when_device_not_active(
        self, hass: HomeAssistant
    ) -> None:
        """Device not in active processor coordinators → removal allowed."""
        entry = self._make_config_entry(active_addresses=[])
        device_entry = self._make_device_entry(DOMAIN, "AA:BB:CC:DD:EE:FF")

        result = await async_remove_config_entry_device(hass, entry, device_entry)

        assert result is True

    async def test_blocks_removal_when_device_is_active(
        self, hass: HomeAssistant
    ) -> None:
        """Device present in active processor coordinators → removal blocked."""
        address = "AA:BB:CC:DD:EE:FF"
        # coordinator key uses lowercase-no-colon device_id, not the raw address;
        # but _processor_coordinators is keyed by raw address from the coordinator code
        entry = self._make_config_entry(active_addresses=[address])
        device_entry = self._make_device_entry(DOMAIN, address)

        result = await async_remove_config_entry_device(hass, entry, device_entry)

        assert result is False

    async def test_allows_removal_of_different_domain_identifier(
        self, hass: HomeAssistant
    ) -> None:
        """Identifiers from other domains are ignored; removal is permitted."""
        address = "AA:BB:CC:DD:EE:FF"
        entry = self._make_config_entry(active_addresses=[address])
        device_entry = self._make_device_entry("other_domain", address)

        result = await async_remove_config_entry_device(hass, entry, device_entry)

        assert result is True
