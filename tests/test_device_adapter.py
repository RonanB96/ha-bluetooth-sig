"""Tests for device_adapter.py - advertisement conversion and parsing."""

from __future__ import annotations

import pytest
from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.types.advertising import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.bluetooth_sig_devices.device_adapter import (
    HomeAssistantBluetoothAdapter,
)


class TestConvertAdvertisement:
    """Test cases for HomeAssistantBluetoothAdapter.convert_advertisement."""

    def test_convert_battery_level_advertisement(
        self, mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with Battery Level characteristic."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_battery
        )

        # Verify result type
        assert isinstance(result, AdvertisementData)

        # Verify RSSI is preserved
        assert result.rssi == -65

        # Verify service data is converted
        assert result.ad_structures.core.service_data is not None
        service_data_keys = list(result.ad_structures.core.service_data.keys())
        assert len(service_data_keys) == 1
        # Case-insensitive UUID comparison
        assert (
            str(service_data_keys[0]).lower() == "00002a19-0000-1000-8000-00805f9b34fb"
        )

        # Verify interpreted data is SIGCharacteristicData (battery level should parse)
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert (
            result.interpreted_data.characteristic_name == "BatteryLevelCharacteristic"
        )
        assert result.interpreted_data.parsed_value == 75

    def test_convert_temperature_advertisement(
        self, mock_bluetooth_service_info_temperature: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with Temperature characteristic."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_temperature
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -55
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert (
            result.interpreted_data.characteristic_name == "TemperatureCharacteristic"
        )
        # Temperature 0x0964 = 2404 -> 24.04°C
        assert abs(result.interpreted_data.parsed_value - 24.04) < 0.01

    def test_convert_humidity_advertisement(
        self, mock_bluetooth_service_info_humidity: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with Humidity characteristic."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_humidity
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -60
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert result.interpreted_data.characteristic_name == "HumidityCharacteristic"
        # Humidity 0x133A = 4922 -> 49.22%
        assert abs(result.interpreted_data.parsed_value - 49.22) < 0.01

    def test_convert_heart_rate_advertisement(
        self, mock_bluetooth_service_info_heart_rate: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with Heart Rate Measurement characteristic."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_heart_rate
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -70
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert (
            result.interpreted_data.characteristic_name
            == "HeartRateMeasurementCharacteristic"
        )
        # Heart rate is a struct with heart_rate field
        assert hasattr(result.interpreted_data.parsed_value, "heart_rate")
        assert result.interpreted_data.parsed_value.heart_rate == 72

    def test_convert_csc_measurement_advertisement(
        self, mock_bluetooth_service_info_csc_measurement: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with CSC Measurement characteristic (complex struct)."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_csc_measurement
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -65
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert result.interpreted_data.characteristic_name == "CSCMeasurementCharacteristic"

        # CSC measurement is a complex struct with multiple fields
        parsed = result.interpreted_data.parsed_value
        assert hasattr(parsed, "cumulative_wheel_revolutions")
        assert hasattr(parsed, "last_wheel_event_time")
        assert hasattr(parsed, "cumulative_crank_revolutions")
        assert hasattr(parsed, "last_crank_event_time")

        assert parsed.cumulative_wheel_revolutions == 16
        assert parsed.last_wheel_event_time == 0.03125  # 32/1024
        assert parsed.cumulative_crank_revolutions == 48
        assert parsed.last_crank_event_time == 0.0625  # 64/1024

    def test_convert_csc_feature_advertisement(
        self, mock_bluetooth_service_info_csc_feature: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with CSC Feature characteristic (bitfield)."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_csc_feature
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -70
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert result.interpreted_data.characteristic_name == "CSCFeatureCharacteristic"

        # CSC feature is a complex struct with bitfield and individual boolean fields
        parsed = result.interpreted_data.parsed_value
        assert hasattr(parsed, "features")
        assert hasattr(parsed, "wheel_revolution_data_supported")
        assert hasattr(parsed, "crank_revolution_data_supported")
        assert hasattr(parsed, "multiple_sensor_locations_supported")

        assert parsed.wheel_revolution_data_supported is True
        assert parsed.crank_revolution_data_supported is True
        assert parsed.multiple_sensor_locations_supported is True

    def test_convert_body_sensor_location_advertisement(
        self, mock_bluetooth_service_info_body_sensor_location: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with Body Sensor Location characteristic (enum)."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_body_sensor_location
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -75
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert result.interpreted_data.characteristic_name == "BodySensorLocationCharacteristic"

        # Body sensor location is an enum/int value
        assert result.interpreted_data.parsed_value == 1  # Chest location

    def test_convert_rssi_only_advertisement(
        self, mock_bluetooth_service_info_rssi_only: BluetoothServiceInfoBleak
    ) -> None:
        """Test converting advertisement with only RSSI, no parseable GATT data."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_rssi_only
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -80

        # Apple manufacturer data is proprietary - should not parse to SIGCharacteristicData
        # interpreted_data may be None or some other type
        if result.interpreted_data is not None:
            # If parsed, it shouldn't be a SIGCharacteristicData
            # (unless the library adds Apple parsing later)
            pass

        # Verify manufacturer data is preserved
        assert result.ad_structures.core.manufacturer_data is not None
        assert 0x004C in result.ad_structures.core.manufacturer_data

    def test_convert_preserves_local_name(
        self, mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak
    ) -> None:
        """Test that local name is preserved in advertisement."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_battery
        )

        assert result.ad_structures.core.local_name == "Test Battery Device"

    def test_convert_invalid_type_raises(self) -> None:
        """Test that invalid input type raises TypeError."""
        with pytest.raises(TypeError, match="Expected BluetoothServiceInfoBleak"):
            HomeAssistantBluetoothAdapter.convert_advertisement("not_a_service_info")


class TestHomeAssistantBluetoothAdapter:
    """Test cases for HomeAssistantBluetoothAdapter class."""

    def test_adapter_properties(self) -> None:
        """Test adapter basic properties."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        assert adapter.address == "AA:BB:CC:DD:EE:FF"
        assert adapter.name == "Test Device"
        assert adapter.is_connected is False
        assert adapter.mtu_size == 23
        assert adapter.supports_scanning is False

    def test_adapter_advertisement_callbacks(self) -> None:
        """Test advertisement callback registration."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        received_advertisements = []

        def callback(adv: AdvertisementData) -> None:
            received_advertisements.append(adv)

        adapter.register_advertisement_callback(callback)

        # Create a mock advertisement
        from unittest.mock import MagicMock

        mock_adv = MagicMock(spec=AdvertisementData)
        mock_adv.rssi = -50

        adapter.on_advertisement_received(mock_adv)

        assert len(received_advertisements) == 1
        assert received_advertisements[0].rssi == -50

        # Unregister and verify no more callbacks
        adapter.unregister_advertisement_callback(callback)
        adapter.on_advertisement_received(mock_adv)

        assert len(received_advertisements) == 1  # Still 1, not 2

    def test_connection_methods_raise_not_implemented(self) -> None:
        """Test that connection methods raise NotImplementedError."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        with pytest.raises(NotImplementedError):
            import asyncio

            asyncio.get_event_loop().run_until_complete(adapter.connect())

        with pytest.raises(NotImplementedError):
            import asyncio

            asyncio.get_event_loop().run_until_complete(adapter.disconnect())

        with pytest.raises(NotImplementedError):
            import asyncio

            asyncio.get_event_loop().run_until_complete(adapter.get_services())
