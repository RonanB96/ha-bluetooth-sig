"""Tests for device_adapter.py - advertisement conversion and parsing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.types.advertising import AdvertisementData, BLEAdvertisingFlags
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
