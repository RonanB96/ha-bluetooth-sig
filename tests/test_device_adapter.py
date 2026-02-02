"""Tests for the device adapter module."""

from unittest.mock import MagicMock

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.bluetooth_sig_devices.device_adapter import (
    HomeAssistantBluetoothAdapter,
)


class TestConvertAdvertisement:
    """Test the HA to bluetooth-sig advertisement conversion."""

    def test_extracts_device_name(
        self, mock_bluetooth_service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Test that device name is correctly extracted from HA service info."""
        ad_data = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info
        )
        assert ad_data.ad_structures.core.local_name == "Test Device"

    def test_extracts_rssi(
        self, mock_bluetooth_service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Test that RSSI is correctly extracted from HA service info."""
        ad_data = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info
        )
        assert ad_data.rssi == -60

    def test_preserves_manufacturer_data_company_ids(
        self, mock_bluetooth_service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Test that manufacturer company IDs are preserved during conversion."""
        ad_data = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info
        )
        # The company ID from the fixture (Apple = 0x004C) should be a key
        assert 0x004C in ad_data.ad_structures.core.manufacturer_data

    def test_preserves_manufacturer_data_payload(
        self, mock_bluetooth_service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Test that manufacturer data payload bytes are preserved."""
        ad_data = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info
        )
        mfr_data = ad_data.ad_structures.core.manufacturer_data[0x004C]
        assert mfr_data.payload == b"\x02\x15test"

    def test_converts_service_data_uuid_strings_to_objects(
        self, mock_bluetooth_service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Test that string UUIDs from HA are converted to BluetoothUUID objects."""
        ad_data = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info
        )
        # Service data should have BluetoothUUID keys, not string keys
        for key in ad_data.ad_structures.core.service_data:
            # Should NOT be a plain string anymore
            assert not isinstance(key, str)

    def test_handles_empty_advertisement(self) -> None:
        """Test conversion handles minimal advertisement data."""
        service_info = BluetoothServiceInfoBleak(
            name="",
            address="11:22:33:44:55:66",
            rssi=-100,
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

        # Should not raise
        ad_data = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)
        assert ad_data.ad_structures.core.local_name == ""
        assert ad_data.rssi == -100


class TestAdapterProperties:
    """Test adapter instance properties."""

    def test_stores_address(self) -> None:
        """Test that adapter stores the device address."""
        adapter = HomeAssistantBluetoothAdapter("AA:BB:CC:DD:EE:FF", "Test")
        assert adapter.address == "AA:BB:CC:DD:EE:FF"

    def test_stores_name(self) -> None:
        """Test that adapter stores the device name."""
        adapter = HomeAssistantBluetoothAdapter("AA:BB:CC:DD:EE:FF", "My Device")
        assert adapter.name == "My Device"

    def test_default_mtu_size(self) -> None:
        """Test that default MTU is the BLE standard 23 bytes."""
        adapter = HomeAssistantBluetoothAdapter("AA:BB:CC:DD:EE:FF", "Test")
        assert adapter.mtu_size == 23

    def test_initially_not_connected(self) -> None:
        """Test that adapter starts in disconnected state."""
        adapter = HomeAssistantBluetoothAdapter("AA:BB:CC:DD:EE:FF", "Test")
        assert adapter.is_connected is False
