"""Tests for device_adapter.py - advertisement conversion and parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.exc import BleakError
from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.types.advertising import AdvertisementData, BLEAdvertisingFlags
from bluetooth_sig.types.uuid import BluetoothUUID
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
        assert (
            result.interpreted_data.characteristic_name
            == "CSCMeasurementCharacteristic"
        )

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
        self,
        mock_bluetooth_service_info_body_sensor_location: BluetoothServiceInfoBleak,
    ) -> None:
        """Test converting advertisement with Body Sensor Location characteristic (enum)."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_body_sensor_location
        )

        assert isinstance(result, AdvertisementData)
        assert result.rssi == -75
        assert result.interpreted_data is not None
        assert isinstance(result.interpreted_data, SIGCharacteristicData)
        assert (
            result.interpreted_data.characteristic_name
            == "BodySensorLocationCharacteristic"
        )

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
            assert not isinstance(result.interpreted_data, SIGCharacteristicData)

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

    def test_convert_sets_flags_connectable(
        self, mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak
    ) -> None:
        """Test that connectable devices get BR_EDR_NOT_SUPPORTED | LE_GENERAL_DISCOVERABLE_MODE."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_battery
        )

        flags = result.ad_structures.properties.flags
        assert flags & BLEAdvertisingFlags.BR_EDR_NOT_SUPPORTED
        assert flags & BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE

    def test_convert_sets_flags_non_connectable(self) -> None:
        """Test that non-connectable devices only get BR_EDR_NOT_SUPPORTED."""
        service_info = BluetoothServiceInfoBleak(
            name="Non-Connectable Device",
            address="AA:BB:CC:DD:EE:10",
            rssi=-80,
            manufacturer_data={},
            service_data={
                "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x50]),
            },
            service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=False,
            time=0,
            tx_power=None,
        )
        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        flags = result.ad_structures.properties.flags
        assert flags & BLEAdvertisingFlags.BR_EDR_NOT_SUPPORTED
        assert not (flags & BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE)

    def test_convert_maps_tx_power(self) -> None:
        """Test that tx_power from service info is mapped to DeviceProperties."""
        service_info = BluetoothServiceInfoBleak(
            name="TX Power Device",
            address="AA:BB:CC:DD:EE:11",
            rssi=-65,
            manufacturer_data={},
            service_data={
                "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x50]),
            },
            service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=8,
        )
        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        assert result.ad_structures.properties.tx_power == 8

    def test_convert_tx_power_none_defaults_to_zero(
        self, mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak
    ) -> None:
        """Test that tx_power=None defaults to 0."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_battery
        )

        assert result.ad_structures.properties.tx_power == 0

    def test_convert_sets_device_address(
        self, mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak
    ) -> None:
        """Test that le_bluetooth_device_address is set from service info."""
        result = HomeAssistantBluetoothAdapter.convert_advertisement(
            mock_bluetooth_service_info_battery
        )

        assert (
            result.ad_structures.directed.le_bluetooth_device_address
            == "AA:BB:CC:DD:EE:01"
        )

    def test_convert_resolves_company_name(self) -> None:
        """Test that manufacturer data uses resolved company names from SIG registry."""
        service_info = BluetoothServiceInfoBleak(
            name="Apple Device",
            address="AA:BB:CC:DD:EE:12",
            rssi=-70,
            manufacturer_data={0x004C: bytes([0x01, 0x02, 0x03])},
            service_data={},
            service_uuids=[],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )
        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        mfr_data = result.ad_structures.core.manufacturer_data
        assert 0x004C in mfr_data
        # Company name should be resolved, not "Unknown"
        assert mfr_data[0x004C].company.name != "Unknown"

    def test_convert_raw_pdu_extracts_real_flags(self) -> None:
        """Test Tier 1: raw PDU bytes produce real BLE flags."""
        mock_device = MagicMock()
        mock_device.details = {}
        service_info = BluetoothServiceInfoBleak(
            name="Raw Device",
            address="AA:BB:CC:DD:EE:20",
            rssi=-60,
            manufacturer_data={},
            service_data={
                "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x50]),
            },
            service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )
        # Inject raw AD bytes: flags(02 01 06) + battery service data
        object.__setattr__(
            service_info,
            "raw",
            bytes(
                [
                    0x02,
                    0x01,
                    0x06,  # Flags: LE_GENERAL_DISCOVERABLE | BR_EDR_NOT_SUPPORTED
                    0x04,
                    0x16,
                    0x19,
                    0x2A,
                    0x50,  # Service Data: Battery 80%
                ]
            ),
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # Real flags from raw parse (value 6 = 0x06)
        assert result.ad_structures.properties.flags == BLEAdvertisingFlags(0x06)
        # Address supplemented from service_info
        assert (
            result.ad_structures.directed.le_bluetooth_device_address
            == "AA:BB:CC:DD:EE:20"
        )

    def test_convert_raw_pdu_extracts_appearance(self) -> None:
        """Test Tier 1: raw PDU bytes with appearance data."""
        mock_device = MagicMock()
        mock_device.details = {}
        service_info = BluetoothServiceInfoBleak(
            name="Appearance Device",
            address="AA:BB:CC:DD:EE:21",
            rssi=-55,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=False,
            time=0,
            tx_power=None,
        )
        # Raw: flags + appearance 0x03C1 (HID Keyboard)
        object.__setattr__(
            service_info,
            "raw",
            bytes(
                [
                    0x02,
                    0x01,
                    0x06,
                    0x03,
                    0x19,
                    0xC1,
                    0x03,  # Appearance: 0x03C1
                ]
            ),
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        assert result.ad_structures.properties.appearance is not None
        assert result.ad_structures.properties.appearance.raw_value == 0x03C1

    def test_convert_raw_pdu_extracts_tx_power(self) -> None:
        """Test Tier 1: raw PDU bytes with TX power."""
        mock_device = MagicMock()
        mock_device.details = {}
        service_info = BluetoothServiceInfoBleak(
            name="TX Device",
            address="AA:BB:CC:DD:EE:22",
            rssi=-65,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )
        # Raw: flags + tx power 4 dBm
        object.__setattr__(
            service_info,
            "raw",
            bytes(
                [
                    0x02,
                    0x01,
                    0x06,
                    0x02,
                    0x0A,
                    0x04,  # TX Power: 4 dBm
                ]
            ),
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        assert result.ad_structures.properties.tx_power == 4

    def test_convert_falls_back_when_no_raw(self) -> None:
        """Test Tier 2: manual fallback when raw is None."""
        mock_device = MagicMock()
        mock_device.details = {}
        service_info = BluetoothServiceInfoBleak(
            name="No Raw Device",
            address="AA:BB:CC:DD:EE:23",
            rssi=-70,
            manufacturer_data={},
            service_data={
                "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x50]),
            },
            service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=5,
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # Manual fallback: synthetic flags
        flags = result.ad_structures.properties.flags
        assert flags & BLEAdvertisingFlags.BR_EDR_NOT_SUPPORTED
        assert flags & BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE
        assert result.ad_structures.properties.tx_power == 5
        assert result.ad_structures.core.local_name == "No Raw Device"

    def test_convert_enriches_from_bluez_appearance(self) -> None:
        """Test Tier 3: BlueZ Device1 props enrich appearance."""
        mock_device = MagicMock()
        mock_device.details = {
            "path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_24",
            "props": {
                "Appearance": 0x03C1,  # HID Keyboard
            },
        }
        service_info = BluetoothServiceInfoBleak(
            name="BlueZ Device",
            address="AA:BB:CC:DD:EE:24",
            rssi=-60,
            manufacturer_data={},
            service_data={
                "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x50]),
            },
            service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # Appearance resolved from BlueZ props
        assert result.ad_structures.properties.appearance is not None
        assert result.ad_structures.properties.appearance.raw_value == 0x03C1
        assert "Human Interface Device" in (
            result.ad_structures.properties.appearance.full_name or ""
        )

    def test_convert_enriches_from_bluez_class_of_device(self) -> None:
        """Test Tier 3: BlueZ Device1 props enrich class_of_device."""
        mock_device = MagicMock()
        mock_device.details = {
            "path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_25",
            "props": {
                "Class": 0x240404,  # Audio/Video headset
            },
        }
        service_info = BluetoothServiceInfoBleak(
            name="Headset",
            address="AA:BB:CC:DD:EE:25",
            rssi=-55,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # Class of Device resolved from BlueZ props
        cod = result.ad_structures.properties.class_of_device
        assert cod is not None
        assert cod.raw_value == 0x240404

    def test_convert_enriches_from_bluez_real_flags(self) -> None:
        """Test Tier 3: BlueZ AdvertisingFlags override synthetic flags."""
        mock_device = MagicMock()
        mock_device.details = {
            "path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_26",
            "props": {
                "AdvertisingFlags": bytes([0x05]),  # LIMITED | BR_EDR_NOT_SUPPORTED
            },
        }
        service_info = BluetoothServiceInfoBleak(
            name="BlueZ Flags Device",
            address="AA:BB:CC:DD:EE:26",
            rssi=-50,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        flags = result.ad_structures.properties.flags
        # Real flags from BlueZ + connectable mapping adds LE_GENERAL
        assert flags & BLEAdvertisingFlags.LE_LIMITED_DISCOVERABLE_MODE
        assert flags & BLEAdvertisingFlags.BR_EDR_NOT_SUPPORTED
        assert flags & BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE

    def test_convert_esphome_no_enrichment(self) -> None:
        """Test ESPHome path: only address_type in details, no enrichment."""
        mock_device = MagicMock()
        mock_device.details = {"address_type": 0}  # ESPHome public address
        service_info = BluetoothServiceInfoBleak(
            name="ESPHome Device",
            address="AA:BB:CC:DD:EE:27",
            rssi=-65,
            manufacturer_data={},
            service_data={
                "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x50]),
            },
            service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
            source="esphome_proxy",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # No enrichment: appearance and class_of_device remain None
        assert result.ad_structures.properties.appearance is None
        assert result.ad_structures.properties.class_of_device is None
        # Still produces valid result
        assert result.rssi == -65

    def test_convert_raw_pdu_not_overwritten_by_bluez_appearance(self) -> None:
        """Test that raw-parsed appearance is NOT overwritten by BlueZ props."""
        mock_device = MagicMock()
        mock_device.details = {
            "path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_28",
            "props": {
                "Appearance": 0x0040,  # Generic Thermometer
            },
        }
        service_info = BluetoothServiceInfoBleak(
            name="Raw+BlueZ Device",
            address="AA:BB:CC:DD:EE:28",
            rssi=-60,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=mock_device,
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )
        # Raw has appearance 0x03C1 (HID Keyboard)
        object.__setattr__(
            service_info,
            "raw",
            bytes(
                [
                    0x02,
                    0x01,
                    0x06,
                    0x03,
                    0x19,
                    0xC1,
                    0x03,
                ]
            ),
        )

        result = HomeAssistantBluetoothAdapter.convert_advertisement(service_info)

        # Raw-parsed appearance (0x03C1) is kept, NOT overwritten by BlueZ (0x0040)
        assert result.ad_structures.properties.appearance is not None
        assert result.ad_structures.properties.appearance.raw_value == 0x03C1


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

    async def test_connection_methods_require_hass(self) -> None:
        """Test that connection methods require hass parameter."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        # Without hass parameter, connect should raise RuntimeError
        with pytest.raises(
            RuntimeError, match="GATT operations require hass parameter"
        ):
            await adapter.connect()

        # get_services requires connection, should raise RuntimeError
        with pytest.raises(RuntimeError, match="Not connected to device"):
            await adapter.get_services()

        # read_gatt_char requires connection, should raise RuntimeError
        with pytest.raises(RuntimeError, match="Not connected to device"):
            await adapter.read_gatt_char(BluetoothUUID("2A19"))

    def test_adapter_has_connection_support_property(self) -> None:
        """Test has_connection_support property."""
        from unittest.mock import MagicMock

        # Without hass, should not have connection support
        adapter_no_hass = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )
        assert adapter_no_hass.has_connection_support is False

        # With hass, should have connection support
        mock_hass = MagicMock()
        adapter_with_hass = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
            hass=mock_hass,
        )
        assert adapter_with_hass.has_connection_support is True

    def test_adapter_update_ble_device(self) -> None:
        """Test update_ble_device method."""
        from unittest.mock import MagicMock

        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        assert adapter._ble_device is None

        mock_ble_device = MagicMock()
        adapter.update_ble_device(mock_ble_device)

        assert adapter._ble_device is mock_ble_device

    def test_adapter_is_connected_property(self) -> None:
        """Test is_connected property reflects actual state."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        # Without client, should not be connected
        assert adapter.is_connected is False

    def test_adapter_mtu_size_default(self) -> None:
        """Test default MTU size."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
        )

        # Default MTU size should be 23
        assert adapter.mtu_size == 23


# =========================================================================
# Connection lifecycle tests
# =========================================================================


class TestConnectionLifecycle:
    """Tests for connect / disconnect / state cleanup."""

    @pytest.fixture
    def adapter_with_hass(self) -> HomeAssistantBluetoothAdapter:
        """Return an adapter configured for GATT connections."""
        mock_hass = MagicMock()
        mock_ble_device = MagicMock()
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
            hass=mock_hass,
            ble_device=mock_ble_device,
        )
        return adapter

    async def test_connect_success(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test successful connection sets state correctly."""
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.mtu_size = 185

        with (
            patch(
                "custom_components.bluetooth_sig_devices.device_adapter.establish_connection",
                return_value=mock_client,
            ),
            patch(
                "custom_components.bluetooth_sig_devices.device_adapter.close_stale_connections_by_address",
                new_callable=AsyncMock,
            ),
        ):
            await adapter_with_hass.connect()

        assert adapter_with_hass.is_connected is True
        assert adapter_with_hass.mtu_size == 185

    async def test_connect_already_connected_skips(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test connecting when already connected is a no-op."""
        mock_client = MagicMock()
        mock_client.is_connected = True
        adapter_with_hass._client = mock_client
        adapter_with_hass._is_connected = True

        # Should not call establish_connection
        await adapter_with_hass.connect()
        assert adapter_with_hass.is_connected is True

    async def test_connect_failure_cleans_state(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test that connect failure clears state properly."""
        with (
            patch(
                "custom_components.bluetooth_sig_devices.device_adapter.establish_connection",
                side_effect=BleakError("Connection refused"),
            ),
            patch(
                "custom_components.bluetooth_sig_devices.device_adapter.close_stale_connections_by_address",
                new_callable=AsyncMock,
            ),
            pytest.raises(BleakError, match="Connection refused"),
        ):
            await adapter_with_hass.connect()

        assert adapter_with_hass.is_connected is False
        assert adapter_with_hass._client is None

    async def test_disconnect_with_stop_notify_failures(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test disconnect cleans up even when stop_notify fails."""
        mock_client = AsyncMock()
        mock_client.is_connected = True
        mock_client.stop_notify = AsyncMock(side_effect=Exception("stop_notify failed"))
        mock_client.disconnect = AsyncMock()
        adapter_with_hass._client = mock_client
        adapter_with_hass._is_connected = True
        adapter_with_hass._notification_callbacks = {
            "uuid1": MagicMock(),
            "uuid2": MagicMock(),
        }

        await adapter_with_hass.disconnect()

        assert adapter_with_hass._client is None
        assert adapter_with_hass._is_connected is False
        assert len(adapter_with_hass._notification_callbacks) == 0

    async def test_disconnect_with_bleak_error(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test disconnect handles BleakError gracefully."""
        mock_client = AsyncMock()
        mock_client.is_connected = True
        mock_client.disconnect = AsyncMock(side_effect=BleakError("disc error"))
        adapter_with_hass._client = mock_client
        adapter_with_hass._is_connected = True
        adapter_with_hass._notification_callbacks = {}

        await adapter_with_hass.disconnect()

        assert adapter_with_hass._client is None
        assert adapter_with_hass._is_connected is False
        assert adapter_with_hass._cached_services is None

    async def test_disconnect_already_disconnected(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test disconnect when client is already not connected."""
        mock_client = MagicMock()
        mock_client.is_connected = False
        adapter_with_hass._client = mock_client
        adapter_with_hass._is_connected = True

        await adapter_with_hass.disconnect()

        assert adapter_with_hass._client is None
        assert adapter_with_hass._is_connected is False

    async def test_disconnect_no_client(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test disconnect when client is None is a no-op."""
        adapter_with_hass._client = None
        await adapter_with_hass.disconnect()
        assert adapter_with_hass._is_connected is False

    def test_on_disconnect_callback(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test _on_disconnect resets state and fires callback."""
        mock_cb = MagicMock()
        adapter_with_hass._is_connected = True
        adapter_with_hass._client = MagicMock()
        adapter_with_hass.set_disconnected_callback(mock_cb)

        adapter_with_hass._on_disconnect(MagicMock())

        assert adapter_with_hass._is_connected is False
        assert adapter_with_hass._client is None
        mock_cb.assert_called_once()

    def test_on_disconnect_no_callback(
        self, adapter_with_hass: HomeAssistantBluetoothAdapter
    ) -> None:
        """Test _on_disconnect works without a disconnected callback."""
        adapter_with_hass._is_connected = True
        adapter_with_hass._client = MagicMock()

        adapter_with_hass._on_disconnect(MagicMock())

        assert adapter_with_hass._is_connected is False


# =========================================================================
# Advertisement callback tests
# =========================================================================


class TestAdvertisementCallbacks:
    """Tests for advertisement registration, unregistration, and dispatch."""

    def test_register_and_receive(self) -> None:
        """Test registering a callback and receiving an advertisement."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        received = []
        adapter.register_advertisement_callback(received.append)

        mock_ad = MagicMock(spec=AdvertisementData)
        adapter.on_advertisement_received(mock_ad)

        assert len(received) == 1
        assert received[0] is mock_ad
        assert adapter._latest_advertisement is mock_ad

    def test_unregister_callback(self) -> None:
        """Test unregistering a callback stops delivery."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        received = []
        cb = received.append
        adapter.register_advertisement_callback(cb)
        adapter.unregister_advertisement_callback(cb)

        adapter.on_advertisement_received(MagicMock(spec=AdvertisementData))
        assert len(received) == 0

    def test_unregister_nonexistent_callback(self) -> None:
        """Test unregistering a callback that was never registered is safe."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        adapter.unregister_advertisement_callback(lambda ad: None)

    def test_list_copy_iteration_safety(self) -> None:
        """Test callbacks can safely modify the list during iteration."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        calls = []

        def self_removing_cb(ad: AdvertisementData) -> None:
            calls.append("self_removing")
            adapter.unregister_advertisement_callback(self_removing_cb)

        adapter.register_advertisement_callback(self_removing_cb)
        adapter.register_advertisement_callback(lambda ad: calls.append("second"))

        adapter.on_advertisement_received(MagicMock(spec=AdvertisementData))
        assert "self_removing" in calls
        assert "second" in calls


# =========================================================================
# Descriptor operations tests
# =========================================================================


class TestDescriptorOperations:
    """Tests for _find_descriptor_handle, read/write_gatt_descriptor."""

    def _make_connected_adapter(
        self,
    ) -> tuple[HomeAssistantBluetoothAdapter, MagicMock]:
        """Return (adapter, mock_client) in connected state."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            hass=MagicMock(),
        )
        mock_desc = MagicMock()
        mock_desc.uuid = "00002902-0000-1000-8000-00805f9b34fb"
        mock_desc.handle = 42

        mock_char = MagicMock()
        mock_char.descriptors = [mock_desc]

        mock_service = MagicMock()
        mock_service.characteristics = [mock_char]

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.services = [mock_service]
        mock_client.read_gatt_descriptor = AsyncMock(
            return_value=bytearray(b"\x01\x00")
        )
        mock_client.write_gatt_descriptor = AsyncMock()

        adapter._client = mock_client
        adapter._is_connected = True
        return adapter, mock_client

    def test_find_descriptor_handle_found(self) -> None:
        """Test finding a descriptor handle by UUID."""
        adapter, _ = self._make_connected_adapter()
        handle = adapter._find_descriptor_handle(
            BluetoothUUID("00002902-0000-1000-8000-00805f9b34fb")
        )
        assert handle == 42

    def test_find_descriptor_handle_not_found(self) -> None:
        """Test finding a descriptor that doesn't exist raises ValueError."""
        adapter, _ = self._make_connected_adapter()
        with pytest.raises(ValueError, match="Descriptor .* not found"):
            adapter._find_descriptor_handle(
                BluetoothUUID("00002903-0000-1000-8000-00805f9b34fb")
            )

    def test_find_descriptor_not_connected(self) -> None:
        """Test finding a descriptor when not connected raises RuntimeError."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            adapter._find_descriptor_handle(
                BluetoothUUID("00002902-0000-1000-8000-00805f9b34fb")
            )

    async def test_read_gatt_descriptor(self) -> None:
        """Test reading a GATT descriptor by UUID."""
        adapter, mock_client = self._make_connected_adapter()
        result = await adapter.read_gatt_descriptor(
            BluetoothUUID("00002902-0000-1000-8000-00805f9b34fb")
        )
        assert result == b"\x01\x00"
        mock_client.read_gatt_descriptor.assert_called_once_with(42)

    async def test_write_gatt_descriptor(self) -> None:
        """Test writing a GATT descriptor by UUID."""
        adapter, mock_client = self._make_connected_adapter()
        await adapter.write_gatt_descriptor(
            BluetoothUUID("00002902-0000-1000-8000-00805f9b34fb"),
            b"\x01\x00",
        )
        mock_client.write_gatt_descriptor.assert_called_once_with(42, b"\x01\x00")


# =========================================================================
# Write GATT char tests
# =========================================================================


class TestWriteGattChar:
    """Tests for write_gatt_char."""

    async def test_write_delegates_to_client(self) -> None:
        """Test write_gatt_char delegates correctly."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = True

        uuid = BluetoothUUID("2A19")
        await adapter.write_gatt_char(uuid, b"\x50", response=True)
        mock_client.write_gatt_char.assert_called_once_with(
            str(uuid), b"\x50", response=True
        )

    async def test_write_not_connected_raises(self) -> None:
        """Test write_gatt_char raises when not connected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.write_gatt_char(BluetoothUUID("2A19"), b"\x50")


# =========================================================================
# Property accessor tests
# =========================================================================


class TestPropertyAccessors:
    """Tests for is_connected, mtu_size (connected), has_connection_support, name."""

    def test_name_property(self) -> None:
        """Test name property returns the configured name."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="My Sensor"
        )
        assert adapter.name == "My Sensor"

    def test_is_connected_all_conditions_true(self) -> None:
        """Test is_connected is True only when all conditions hold."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        mock_client = MagicMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = True
        assert adapter.is_connected is True

    def test_is_connected_flag_false(self) -> None:
        """Test is_connected is False when _is_connected is False."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        mock_client = MagicMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = False
        assert adapter.is_connected is False

    def test_mtu_size_from_connected_client(self) -> None:
        """Test mtu_size returns client MTU when connected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.mtu_size = 247
        adapter._client = mock_client
        assert adapter.mtu_size == 247

    def test_mtu_size_cached_when_disconnected(self) -> None:
        """Test mtu_size returns cached value when disconnected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        adapter._mtu_size = 185
        assert adapter.mtu_size == 185


# =========================================================================
# Notification tests
# =========================================================================


class TestNotifications:
    """Tests for start_notify and stop_notify."""

    async def test_start_notify(self) -> None:
        """Test start_notify registers callback and delegates to client."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = True

        mock_cb = MagicMock()
        uuid = BluetoothUUID("2A37")
        await adapter.start_notify(uuid, mock_cb)

        assert str(uuid) in adapter._notification_callbacks
        mock_client.start_notify.assert_called_once()

    async def test_stop_notify(self) -> None:
        """Test stop_notify removes callback and delegates to client."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = True

        uuid = BluetoothUUID("2A37")
        adapter._notification_callbacks[str(uuid)] = MagicMock()

        await adapter.stop_notify(uuid)
        assert str(uuid) not in adapter._notification_callbacks
        mock_client.stop_notify.assert_called_once_with(str(uuid))

    async def test_start_notify_not_connected(self) -> None:
        """Test start_notify raises when not connected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.start_notify(BluetoothUUID("2A37"), MagicMock())

    async def test_stop_notify_not_connected(self) -> None:
        """Test stop_notify raises when not connected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.stop_notify(BluetoothUUID("2A37"))


# =========================================================================
# Pair / Unpair tests
# =========================================================================


class TestPairUnpair:
    """Tests for pair and unpair methods."""

    async def test_pair_success(self) -> None:
        """Test pair delegates to client."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = True

        await adapter.pair()
        mock_client.pair.assert_called_once()

    async def test_pair_not_implemented(self) -> None:
        """Test pair raises NotImplementedError when platform doesn't support it."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        mock_client.pair = AsyncMock(side_effect=NotImplementedError)
        adapter._client = mock_client
        adapter._is_connected = True

        with pytest.raises(NotImplementedError):
            await adapter.pair()

    async def test_pair_not_connected(self) -> None:
        """Test pair raises when not connected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.pair()

    async def test_unpair_success(self) -> None:
        """Test unpair delegates to client."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        adapter._client = mock_client
        adapter._is_connected = True

        await adapter.unpair()
        mock_client.unpair.assert_called_once()

    async def test_unpair_not_implemented(self) -> None:
        """Test unpair raises NotImplementedError when platform doesn't support it."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=MagicMock()
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        mock_client.unpair = AsyncMock(side_effect=NotImplementedError)
        adapter._client = mock_client
        adapter._is_connected = True

        with pytest.raises(NotImplementedError):
            await adapter.unpair()

    async def test_unpair_not_connected(self) -> None:
        """Test unpair raises when not connected."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.unpair()


# =========================================================================
# RSSI tests
# =========================================================================


class TestReadRSSI:
    """Tests for read_rssi."""

    async def test_read_rssi_returns_cached(self) -> None:
        """Test read_rssi returns cached RSSI from latest advertisement."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        mock_ad = MagicMock()
        mock_ad.rssi = -72
        adapter._latest_advertisement = mock_ad

        assert await adapter.read_rssi() == -72

    async def test_read_rssi_no_advertisement_raises(self) -> None:
        """Test read_rssi raises ValueError when no advertisement."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        with pytest.raises(ValueError, match="No RSSI available"):
            await adapter.read_rssi()


# =========================================================================
# get_latest_advertisement / get_advertisement_rssi tests
# =========================================================================


class TestAdvertisementFetch:
    """Tests for get_latest_advertisement and get_advertisement_rssi."""

    async def test_get_latest_advertisement_no_refresh(self) -> None:
        """Test get_latest_advertisement returns cached without refresh."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        mock_ad = MagicMock()
        adapter._latest_advertisement = mock_ad

        result = await adapter.get_latest_advertisement(refresh=False)
        assert result is mock_ad

    async def test_get_latest_advertisement_refresh_with_hass(self) -> None:
        """Test get_latest_advertisement refresh fetches from HA."""
        mock_service_info = MagicMock(spec=BluetoothServiceInfoBleak)
        mock_service_info.address = "AA:BB:CC:DD:EE:FF"
        mock_service_info.rssi = -60
        mock_service_info.manufacturer_data = {}
        mock_service_info.service_data = {
            "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x4B]),
        }
        mock_service_info.service_uuids = ["00002a19-0000-1000-8000-00805f9b34fb"]
        mock_service_info.name = "Test"
        mock_service_info.connectable = True
        mock_service_info.time = 0.0
        mock_service_info.tx_power = None
        mock_service_info.device = MagicMock()

        mock_hass = MagicMock()
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=mock_hass
        )

        with patch(
            "custom_components.bluetooth_sig_devices.device_adapter.bluetooth.async_last_service_info",
            return_value=mock_service_info,
        ):
            result = await adapter.get_latest_advertisement(refresh=True)

        assert result is not None

    async def test_get_latest_advertisement_refresh_no_service_info(self) -> None:
        """Test get_latest_advertisement refresh when HA has no data."""
        mock_hass = MagicMock()
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=mock_hass
        )

        with patch(
            "custom_components.bluetooth_sig_devices.device_adapter.bluetooth.async_last_service_info",
            return_value=None,
        ):
            result = await adapter.get_latest_advertisement(refresh=True)

        assert result is None

    async def test_get_advertisement_rssi_refresh(self) -> None:
        """Test get_advertisement_rssi with refresh."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        mock_ad = MagicMock()
        mock_ad.rssi = -65
        adapter._latest_advertisement = mock_ad

        rssi = await adapter.get_advertisement_rssi(refresh=False)
        assert rssi == -65

    async def test_get_advertisement_rssi_none(self) -> None:
        """Test get_advertisement_rssi returns None when no advertisement."""
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test"
        )
        rssi = await adapter.get_advertisement_rssi(refresh=False)
        assert rssi is None


# =========================================================================
# _get_ble_device tests
# =========================================================================


class TestGetBleDevice:
    """Tests for _get_ble_device."""

    def test_get_ble_device_refreshes_from_hass(self) -> None:
        """Test _get_ble_device fetches a fresh device from HA."""
        mock_hass = MagicMock()
        fresh_device = MagicMock()
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=mock_hass
        )

        with patch(
            "custom_components.bluetooth_sig_devices.device_adapter.bluetooth.async_ble_device_from_address",
            return_value=fresh_device,
        ):
            result = adapter._get_ble_device()

        assert result is fresh_device

    def test_get_ble_device_falls_back_to_cached(self) -> None:
        """Test _get_ble_device uses cached device when HA returns None."""
        mock_hass = MagicMock()
        cached_device = MagicMock()
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            hass=mock_hass,
            ble_device=cached_device,
        )

        with patch(
            "custom_components.bluetooth_sig_devices.device_adapter.bluetooth.async_ble_device_from_address",
            return_value=None,
        ):
            result = adapter._get_ble_device()

        assert result is cached_device

    def test_get_ble_device_no_device_raises(self) -> None:
        """Test _get_ble_device raises when no device available."""
        mock_hass = MagicMock()
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF", name="Test", hass=mock_hass
        )

        with (
            patch(
                "custom_components.bluetooth_sig_devices.device_adapter.bluetooth.async_ble_device_from_address",
                return_value=None,
            ),
            pytest.raises(RuntimeError, match="No BLE device available"),
        ):
            adapter._get_ble_device()


# =========================================================================
# Scan stubs
# =========================================================================


class TestScanStubs:
    """Test that scanning stubs raise NotImplementedError."""

    async def test_scan_raises(self) -> None:
        """Test scan raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await HomeAssistantBluetoothAdapter.scan()

    def test_scan_stream_raises(self) -> None:
        """Test scan_stream raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            HomeAssistantBluetoothAdapter.scan_stream()

    async def test_find_device_raises(self) -> None:
        """Test find_device raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await HomeAssistantBluetoothAdapter.find_device(filters={})
