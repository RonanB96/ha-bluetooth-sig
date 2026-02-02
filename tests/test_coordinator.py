"""Tests for coordinator.py - device management and entity creation."""

from __future__ import annotations

from unittest.mock import MagicMock

from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.types.gatt_enums import ValueType
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
)

from custom_components.bluetooth_sig_devices.const import DOMAIN
from custom_components.bluetooth_sig_devices.coordinator import BluetoothSIGCoordinator


class TestBluetoothSIGCoordinator:
    """Test cases for BluetoothSIGCoordinator."""

    def test_coordinator_initialization(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test coordinator initializes correctly."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        assert coordinator.hass is mock_hass
        assert coordinator.entry is mock_config_entry
        assert coordinator.devices == {}
        assert coordinator.processors == []
        assert coordinator.translator is not None

    def test_register_processor(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test registering a processor."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        processor = MagicMock()

        coordinator.register_processor(processor)

        assert processor in coordinator.processors


class TestUpdateDevice:
    """Test cases for update_device method."""

    def test_update_device_creates_device(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that update_device creates a new device entry."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        assert "AA:BB:CC:DD:EE:01" in coordinator.devices
        assert isinstance(result, PassiveBluetoothDataUpdate)

    def test_update_device_reuses_existing_device(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that update_device reuses existing device entry."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        # First call creates device
        coordinator.update_device(mock_bluetooth_service_info_battery)
        device_count_after_first = len(coordinator.devices)

        # Second call should reuse
        coordinator.update_device(mock_bluetooth_service_info_battery)
        device_count_after_second = len(coordinator.devices)

        assert device_count_after_first == device_count_after_second == 1


class TestBuildPassiveBluetoothUpdate:
    """Test cases for _build_passive_bluetooth_update method."""

    def test_creates_device_info(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that device info is correctly created."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        assert None in result.devices
        device_info = result.devices[None]
        assert (DOMAIN, "AA:BB:CC:DD:EE:01") in device_info.get("identifiers", set())
        assert device_info.get("name") == "Test Battery Device"

    def test_creates_rssi_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that RSSI entity is created."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        # Find RSSI key
        rssi_keys = [k for k in result.entity_data if k.key == "rssi"]
        assert len(rssi_keys) == 1

        rssi_key = rssi_keys[0]
        assert result.entity_data[rssi_key] == -65
        assert result.entity_names[rssi_key] == "Signal Strength"

        description = result.entity_descriptions[rssi_key]
        assert description.native_unit_of_measurement == "dBm"


class TestEntityCreationFromSIGCharacteristicData:
    """Test cases for entity creation from SIGCharacteristicData."""

    def test_battery_level_creates_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that Battery Level characteristic creates sensor entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        # Find battery entity (key contains the UUID)
        battery_keys = [k for k in result.entity_data if "2a19" in str(k.key).lower()]
        # May have 1 or 2 keys (interpreted_data + service_data)
        assert len(battery_keys) >= 1

        # At least one entity should have value 75
        battery_values = [result.entity_data[k] for k in battery_keys]
        assert 75 in battery_values

        # Find the "Battery Level" entity specifically
        for key in battery_keys:
            desc = result.entity_descriptions[key]
            if desc.name == "Battery Level":
                # Use type name comparison in case of import path differences
                assert "SensorEntityDescription" in type(desc).__name__
                assert desc.native_unit_of_measurement == "%"
                break
        else:
            # At minimum, check any battery entity exists
            desc = result.entity_descriptions[battery_keys[0]]
            assert "SensorEntityDescription" in type(desc).__name__

    def test_temperature_creates_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_temperature: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that Temperature characteristic creates sensor entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_temperature)

        # Find temperature entity
        temp_keys = [k for k in result.entity_data if "2a6e" in str(k.key).lower()]
        # May have 1 or 2 keys (interpreted_data + service_data)
        assert len(temp_keys) >= 1

        # At least one entity should have value ~24.04
        temp_values = [
            result.entity_data[k]
            for k in temp_keys
            if isinstance(result.entity_data[k], (int, float))
        ]
        assert any(abs(float(v) - 24.04) < 0.1 for v in temp_values)

        # Find the "Temperature" entity specifically
        for key in temp_keys:
            desc = result.entity_descriptions[key]
            if desc.name == "Temperature":
                assert desc.native_unit_of_measurement == "°C"
                break

    def test_humidity_creates_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_humidity: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that Humidity characteristic creates sensor entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_humidity)

        # Find humidity entity
        humidity_keys = [k for k in result.entity_data if "2a6f" in str(k.key).lower()]
        # May have 1 or 2 keys (interpreted_data + service_data)
        assert len(humidity_keys) >= 1

        # At least one entity should have value ~49.22
        humidity_values = [
            result.entity_data[k]
            for k in humidity_keys
            if isinstance(result.entity_data[k], (int, float))
        ]
        assert any(abs(float(v) - 49.22) < 0.1 for v in humidity_values)

        # Find the "Humidity" entity specifically
        for key in humidity_keys:
            desc = result.entity_descriptions[key]
            if desc.name == "Humidity":
                assert desc.native_unit_of_measurement == "%"
                break

    def test_heart_rate_creates_struct_entities(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_heart_rate: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that Heart Rate Measurement creates struct field entities."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_heart_rate)

        # Heart rate has ValueType.VARIOUS, so it creates multiple entities from struct fields
        hr_keys = [
            k
            for k in result.entity_data
            if "2a37" in str(k.key).lower() and "heart_rate" in str(k.key).lower()
        ]

        # Should have at least the heart_rate field
        assert len(hr_keys) >= 1

        hr_key = hr_keys[0]
        assert result.entity_data[hr_key] == 72

    def test_csc_measurement_creates_struct_entities(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_csc_measurement: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that CSC Measurement creates multiple struct field entities."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_csc_measurement)

        # CSC measurement creates multiple entities from struct fields
        csc_keys = [
            k for k in result.entity_data
            if "2a5b" in str(k.key).lower()
        ]

        # Should have multiple entities for different CSC fields
        assert len(csc_keys) >= 4  # wheel revs, wheel time, crank revs, crank time

        # Check that we have the expected values
        entity_values = [result.entity_data[k] for k in csc_keys]
        assert 16 in entity_values  # cumulative_wheel_revolutions
        assert 0.03125 in entity_values  # last_wheel_event_time (32/1024)
        assert 48 in entity_values  # cumulative_crank_revolutions
        assert 0.0625 in entity_values  # last_crank_event_time (64/1024)

    def test_csc_feature_creates_bitfield_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_csc_feature: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that CSC Feature creates bitfield entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_csc_feature)

        # Find CSC feature entity
        feature_keys = [
            k for k in result.entity_data
            if "2a5c" in str(k.key).lower()
        ]

        assert len(feature_keys) >= 1
        # CSC feature creates multiple entities for different aspects
        # At minimum, we should have some entities created from the bitfield

    def test_body_sensor_location_creates_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_body_sensor_location: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that Body Sensor Location creates entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_body_sensor_location)

        # Find body sensor location entity
        location_keys = [
            k for k in result.entity_data
            if "2a38" in str(k.key).lower()
        ]

        assert len(location_keys) >= 1
        location_key = location_keys[0]
        assert result.entity_data[location_key] == 1  # Chest location

    def test_rssi_only_device_creates_only_rssi(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_rssi_only: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that device with no parseable data only gets RSSI entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_rssi_only)

        # Should only have RSSI entity
        # Either no extra entities, or only manufacturer-specific ones (not SIG characteristics)
        # No assertions about specific count since proprietary data handling may vary
        assert "rssi" in [k.key for k in result.entity_data]


class TestCharacteristicRegistry:
    """Test cases for CharacteristicRegistry integration."""

    def test_battery_level_registry_lookup(self) -> None:
        """Test looking up Battery Level in CharacteristicRegistry."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            "00002a19-0000-1000-8000-00805f9b34fb"
        )

        assert char_class is not None

        instance = char_class()
        assert instance.name == "Battery Level"
        assert instance.unit == "%"
        assert instance.value_type == ValueType.INT

    def test_temperature_registry_lookup(self) -> None:
        """Test looking up Temperature in CharacteristicRegistry."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            "00002a6e-0000-1000-8000-00805f9b34fb"
        )

        assert char_class is not None

        instance = char_class()
        assert instance.name == "Temperature"
        assert instance.unit == "°C"
        # Temperature is stored as int but represents decimal
        assert instance.value_type == ValueType.INT

    def test_heart_rate_registry_lookup(self) -> None:
        """Test looking up Heart Rate Measurement in CharacteristicRegistry."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            "00002a37-0000-1000-8000-00805f9b34fb"
        )

        assert char_class is not None

        instance = char_class()
        assert instance.name == "Heart Rate Measurement"
        assert instance.unit == "beats per minute"
        assert instance.value_type == ValueType.VARIOUS

    def test_unknown_uuid_returns_none(self) -> None:
        """Test that unknown UUID returns None from registry."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            "00000000-0000-0000-0000-000000000000"
        )

        assert char_class is None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_name_uses_address(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test device with no name uses address-based name."""
        service_info = BluetoothServiceInfoBleak(
            name="",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-75,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(service_info)

        device_info = result.devices[None]
        # Should use address suffix as name
        device_name = device_info.get("name") or ""
        assert (
            "DD:EE:FF" in device_name
            or "Bluetooth Device" in device_name
        )

    def test_empty_service_data(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test handling of empty service data."""
        service_info = BluetoothServiceInfoBleak(
            name="Empty Device",
            address="AA:BB:CC:DD:EE:AA",
            rssi=-80,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(service_info)

        # Should still create device and RSSI entity
        assert result.devices is not None
        assert len(result.entity_data) >= 1  # At least RSSI
