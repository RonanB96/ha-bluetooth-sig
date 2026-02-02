"""Tests for the coordinator module."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices.const import DOMAIN
from custom_components.bluetooth_sig_devices.coordinator import BluetoothSIGCoordinator


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bluetooth SIG Devices",
        data={},
        entry_id="test_entry_id",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def coordinator(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> BluetoothSIGCoordinator:
    """Create a coordinator instance."""
    return BluetoothSIGCoordinator(hass, mock_config_entry)


class TestUpdateDevice:
    """Test the update_device method - core runtime logic."""

    def test_creates_device_on_first_advertisement(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that a new device is created when first seen."""
        assert len(coordinator.devices) == 0

        coordinator.update_device(mock_bluetooth_service_info)

        assert len(coordinator.devices) == 1
        assert "AA:BB:CC:DD:EE:FF" in coordinator.devices

    def test_reuses_existing_device(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that subsequent updates reuse the same device instance."""
        coordinator.update_device(mock_bluetooth_service_info)
        device1 = coordinator.devices["AA:BB:CC:DD:EE:FF"]

        coordinator.update_device(mock_bluetooth_service_info)
        device2 = coordinator.devices["AA:BB:CC:DD:EE:FF"]

        assert device1 is device2

    def test_returns_passive_bluetooth_update(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that update_device returns a PassiveBluetoothDataUpdate."""
        from homeassistant.components.bluetooth.passive_update_processor import (
            PassiveBluetoothDataUpdate,
        )

        result = coordinator.update_device(mock_bluetooth_service_info)

        assert isinstance(result, PassiveBluetoothDataUpdate)

    def test_update_contains_device_info(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that the update includes device info for HA device registry."""
        result = coordinator.update_device(mock_bluetooth_service_info)

        # Should have device info keyed by None (the default device)
        assert None in result.devices
        device_info = result.devices[None]

        # Check device info contains the address
        assert (DOMAIN, "AA:BB:CC:DD:EE:FF") in device_info["identifiers"]

    def test_update_contains_rssi_entity(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that RSSI sensor is included in the update."""
        result = coordinator.update_device(mock_bluetooth_service_info)

        # Find the RSSI entity
        rssi_keys = [k for k in result.entity_data if k.key == "rssi"]
        assert len(rssi_keys) == 1

        # Check RSSI value matches
        assert result.entity_data[rssi_keys[0]] == -60

    def test_device_name_from_advertisement(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that device name is taken from the advertisement."""
        result = coordinator.update_device(mock_bluetooth_service_info)

        device_info = result.devices[None]
        assert device_info["name"] == "Test Device"

    def test_device_name_fallback_when_empty(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test fallback device name when advertisement has no name."""
        coordinator = BluetoothSIGCoordinator(hass, mock_config_entry)

        service_info = BluetoothServiceInfoBleak(
            name="",
            address="11:22:33:44:55:66",
            rssi=-50,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            advertisement=MagicMock(),
            device=MagicMock(),
            time=0,
            connectable=False,
            tx_power=None,
        )

        result = coordinator.update_device(service_info)
        device_info = result.devices[None]

        # Should use fallback name with last 8 chars of address
        assert "55:66" in device_info["name"]


class TestEntityDescriptions:
    """Test that entity descriptions are correctly built."""

    def test_rssi_entity_has_correct_unit(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that RSSI entity has dBm unit."""
        result = coordinator.update_device(mock_bluetooth_service_info)

        rssi_keys = [k for k in result.entity_descriptions if k.key == "rssi"]
        rssi_desc = result.entity_descriptions[rssi_keys[0]]

        assert rssi_desc.native_unit_of_measurement == "dBm"

    def test_rssi_entity_has_measurement_state_class(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that RSSI entity has MEASUREMENT state class."""
        from homeassistant.components.sensor import SensorStateClass

        result = coordinator.update_device(mock_bluetooth_service_info)

        rssi_keys = [k for k in result.entity_descriptions if k.key == "rssi"]
        rssi_desc = result.entity_descriptions[rssi_keys[0]]

        assert rssi_desc.state_class == SensorStateClass.MEASUREMENT


class TestCoordinatorLifecycle:
    """Test coordinator start/stop lifecycle."""

    async def test_stop_clears_devices(
        self,
        coordinator: BluetoothSIGCoordinator,
        mock_bluetooth_service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that stopping the coordinator clears the device cache."""
        coordinator.update_device(mock_bluetooth_service_info)
        assert len(coordinator.devices) == 1

        await coordinator.async_stop()

        assert len(coordinator.devices) == 0
