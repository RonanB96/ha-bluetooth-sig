"""Tests for the integration setup."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices import (
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.bluetooth_sig_devices.const import (
    CONF_CONNECTION_TIMEOUT,
    CONF_MAX_CONCURRENT_CONNECTIONS,
    CONF_MAX_PROBE_RETRIES,
    CONF_POLL_INTERVAL,
    CONF_STALE_DEVICE_TIMEOUT,
    DOMAIN,
)

from .conftest import make_device_entry, make_hub_entry


@pytest.fixture
def hub_config_entry() -> MockConfigEntry:
    """Create a mock hub config entry (no address)."""
    return make_hub_entry(entry_id="test_entry_id")


async def test_async_setup_entry(
    hass: HomeAssistant, hub_config_entry: MockConfigEntry
) -> None:
    """Test setting up the hub integration entry.

    Hub entries create a coordinator but do NOT forward platforms —
    platform forwarding happens in per-device entries.
    """
    hub_config_entry.add_to_hass(hass)

    with (
        patch("homeassistant.components.bluetooth.async_scanner_count", return_value=1),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
    ):
        result = await async_setup_entry(hass, hub_config_entry)

        assert result is True
        # Check coordinator exists in runtime_data (Bronze requirement)
        assert hub_config_entry.runtime_data is not None
        # Coordinator must also be stored in hass.data for device entries
        assert hass.data[DOMAIN]["coordinator"] is hub_config_entry.runtime_data


async def test_async_unload_entry(
    hass: HomeAssistant, hub_config_entry: MockConfigEntry
) -> None:
    """Test unloading the hub integration entry.

    Hub entry unload stops the coordinator and cleans up hass.data.
    It does NOT unload platforms — that happens in per-device entries.
    """
    hub_config_entry.add_to_hass(hass)

    # First set up
    with (
        patch("homeassistant.components.bluetooth.async_scanner_count", return_value=1),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
    ):
        await async_setup_entry(hass, hub_config_entry)

    # Verify coordinator is set up
    coordinator = hub_config_entry.runtime_data
    assert coordinator is not None
    assert DOMAIN in hass.data

    # Then unload
    with patch.object(coordinator, "async_stop", new_callable=AsyncMock) as mock_stop:
        result = await async_unload_entry(hass, hub_config_entry)

        assert result is True
        mock_stop.assert_called_once()
        # hass.data[DOMAIN] should be cleaned up
        assert DOMAIN not in hass.data


async def test_async_setup_entry_coordinator_created(
    hass: HomeAssistant, hub_config_entry: MockConfigEntry
) -> None:
    """Test that coordinator is created during setup."""
    hub_config_entry.add_to_hass(hass)

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
        await async_setup_entry(hass, hub_config_entry)

        # Check coordinator exists in runtime_data (Bronze requirement)
        coordinator = hub_config_entry.runtime_data
        assert coordinator is not None

        # Check it's the right type
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        assert isinstance(coordinator, BluetoothSIGCoordinator)


class TestAsyncRemoveConfigEntryDevice:
    """Tests for async_remove_config_entry_device (stale-devices rule).

    The function checks device_entry.connections (not identifiers) because
    the passive BLE framework registers devices with ("bluetooth", address)
    connections, enabling cross-integration device merging.
    """

    def _setup_coordinator(
        self, hass: HomeAssistant, active_addresses: list[str]
    ) -> MagicMock:
        """Store a mock coordinator in hass.data[DOMAIN] and return it."""
        coordinator = MagicMock()
        active_set = set(active_addresses)
        coordinator.is_device_active.side_effect = lambda addr: addr in active_set
        # Keep _processor_coordinators for any other test that checks it
        coordinator._processor_coordinators = {
            addr: MagicMock() for addr in active_addresses
        }
        hass.data.setdefault(DOMAIN, {})["coordinator"] = coordinator
        return coordinator

    def _make_hub_entry(self) -> MagicMock:
        """Return a mock hub config entry (no 'address' in data)."""
        entry = MagicMock()
        entry.data = {}  # hub entries have no "address" key
        return entry

    def _make_device_entry(
        self, connections: set[tuple[str, str]] | None = None
    ) -> MagicMock:
        """Return a mock device entry with bluetooth connections."""
        device_entry = MagicMock()
        device_entry.connections = connections or set()
        device_entry.identifiers = set()
        return device_entry

    async def test_allows_removal_when_device_not_active(
        self, hass: HomeAssistant
    ) -> None:
        """Device not in active processor coordinators → removal allowed."""
        self._setup_coordinator(hass, active_addresses=[])
        entry = self._make_hub_entry()
        device_entry = self._make_device_entry(
            connections={("bluetooth", "AA:BB:CC:DD:EE:FF")}
        )

        result = await async_remove_config_entry_device(hass, entry, device_entry)

        assert result is True

    async def test_blocks_removal_when_device_is_active(
        self, hass: HomeAssistant
    ) -> None:
        """Device present in active processor coordinators → removal blocked."""
        address = "AA:BB:CC:DD:EE:FF"
        self._setup_coordinator(hass, active_addresses=[address])
        entry = self._make_hub_entry()
        device_entry = self._make_device_entry(connections={("bluetooth", address)})

        result = await async_remove_config_entry_device(hass, entry, device_entry)

        assert result is False

    async def test_allows_removal_of_non_bluetooth_connection(
        self, hass: HomeAssistant
    ) -> None:
        """Non-bluetooth connections are ignored; removal is permitted."""
        address = "AA:BB:CC:DD:EE:FF"
        self._setup_coordinator(hass, active_addresses=[address])
        entry = self._make_hub_entry()
        device_entry = self._make_device_entry(connections={("other_type", address)})

        result = await async_remove_config_entry_device(hass, entry, device_entry)

        assert result is True


class TestInitEntryRouting:
    """Verify that __init__.async_setup_entry routes correctly."""

    async def test_hub_entry_creates_coordinator(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Hub entry (no address) creates a coordinator in hass.data."""
        hub = make_hub_entry()
        hub.add_to_hass(hass)

        with (
            patch(
                "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
                return_value=lambda: None,
            ),
            patch(
                "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
                return_value=[],
            ),
        ):
            result = await hass.config_entries.async_setup(hub.entry_id)

        assert result is True
        assert DOMAIN in hass.data
        assert "coordinator" in hass.data[DOMAIN]

    async def test_device_entry_without_hub_raises_not_ready(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """A device entry loaded before the hub raises ConfigEntryNotReady."""
        dev = make_device_entry()
        dev.add_to_hass(hass)

        # No hub set up — hass.data[DOMAIN] is empty
        result = await hass.config_entries.async_setup(dev.entry_id)

        # Entry should not be loaded
        assert result is False
        assert dev.state == config_entries.ConfigEntryState.SETUP_RETRY


class TestHubOptionsPassedToCoordinator:
    """Verify that hub entry options are forwarded to coordinator construction."""

    async def test_custom_hub_options_reach_coordinator(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Hub options (poll_interval etc.) are passed to BluetoothSIGCoordinator."""
        hub = make_hub_entry(
            options={
                CONF_POLL_INTERVAL: 120,
                CONF_MAX_CONCURRENT_CONNECTIONS: 4,
                CONF_CONNECTION_TIMEOUT: 60,
                CONF_MAX_PROBE_RETRIES: 7,
                CONF_STALE_DEVICE_TIMEOUT: 1800,
            }
        )
        hub.add_to_hass(hass)

        with (
            patch(
                "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
                return_value=lambda: None,
            ),
            patch(
                "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
                return_value=[],
            ),
        ):
            result = await hass.config_entries.async_setup(hub.entry_id)

        assert result is True
        coordinator = hass.data[DOMAIN]["coordinator"]
        assert coordinator.poll_interval == 120

    async def test_default_hub_options_when_not_set(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """When no hub options are set, coordinator uses defaults."""
        hub = make_hub_entry()  # No options
        hub.add_to_hass(hass)

        with (
            patch(
                "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_register_callback",
                return_value=lambda: None,
            ),
            patch(
                "custom_components.bluetooth_sig_devices.coordinator.bluetooth.async_discovered_service_info",
                return_value=[],
            ),
        ):
            result = await hass.config_entries.async_setup(hub.entry_id)

        assert result is True
        coordinator = hass.data[DOMAIN]["coordinator"]
        # Default poll interval is 300 seconds (5 minutes)
        assert coordinator.poll_interval == 300
