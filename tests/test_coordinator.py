"""Tests for coordinator.py — device management, discovery orchestration, lifecycle."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from bluetooth_sig.gatt.characteristics.unknown import UnknownCharacteristic
from bluetooth_sig.types.data_types import CharacteristicInfo
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry

from custom_components.bluetooth_sig_devices.const import (
    DEFAULT_STALE_DEVICE_TIMEOUT,
    CharacteristicSource,
    DiscoveredCharacteristic,
)
from custom_components.bluetooth_sig_devices.coordinator import (
    BluetoothSIGCoordinator,
)


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
        assert coordinator.processor_coordinators == {}
        assert coordinator.translator is not None


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
        """Test that device info is correctly created.

        Device info must NOT include identifiers or connections — the passive
        BLE framework adds them automatically (using the "bluetooth" domain)
        when device_id is None, which enables device merging with other BLE
        integrations (e.g. xiaomi_ble) via the shared ("bluetooth", address)
        connection.
        """
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        assert None in result.devices
        device_info = result.devices[None]
        # Must NOT set identifiers — framework handles this
        assert "identifiers" not in device_info
        # Must NOT set connections — framework handles this
        assert "connections" not in device_info
        assert device_info.get("name") == "Test Battery Device"

    def test_no_rssi_entity_created(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that RSSI entity is NOT created (avoids duplicating BLE monitor)."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        # RSSI should NOT be created - this is generic BLE data that BLE monitor handles
        rssi_keys = [k for k in result.entity_data if k.key == "rssi"]
        assert len(rssi_keys) == 0

        # But the device should still have SIG characteristic entities (Battery Level)
        battery_keys = [k for k in result.entity_data if "2a19" in str(k.key).lower()]
        assert len(battery_keys) >= 1


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

        # Heart rate has a struct python_type, so it creates multiple entities from struct fields
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
        csc_keys = [k for k in result.entity_data if "2a5b" in str(k.key).lower()]

        # Should have multiple entities for different CSC fields
        assert len(csc_keys) >= 4  # wheel revs, wheel time, crank revs, crank time

        # Check that we have the expected values
        entity_values = [result.entity_data[k] for k in csc_keys]
        assert 16 in entity_values  # cumulative_wheel_revolutions
        assert 0.03125 in entity_values  # last_wheel_event_time (32/1024)
        assert 48 in entity_values  # cumulative_crank_revolutions
        assert 0.0625 in entity_values  # last_crank_event_time (64/1024)

    def test_csc_feature_skipped_by_role_gating(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_csc_feature: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that CSC Feature is skipped because its role is FEATURE.

        FEATURE-role characteristics describe device capabilities, not
        measurable data, so they should not create sensor entities.
        """
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_csc_feature)

        # CSC Feature has role=FEATURE and should be gated out entirely
        assert result is None or not any(
            "2a5c" in str(k.key).lower() for k in result.entity_data
        )

    def test_body_sensor_location_creates_entity(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_body_sensor_location: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that Body Sensor Location creates entity."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(
            mock_bluetooth_service_info_body_sensor_location
        )

        # Find body sensor location entity
        location_keys = [k for k in result.entity_data if "2a38" in str(k.key).lower()]

        assert len(location_keys) >= 1
        location_key = location_keys[0]
        # BodySensorLocation is an IntEnum → _to_ha_state returns .name
        value = result.entity_data[location_key]
        assert isinstance(value, str)
        assert value == "CHEST"  # Chest location member name

    def test_rssi_only_device_creates_no_entities(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_rssi_only: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that device with no parseable SIG data creates NO entities.

        This integration only creates entities for devices that expose
        standard Bluetooth SIG GATT characteristics. Generic RSSI data
        is handled by dedicated BLE monitor integrations.
        """
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_rssi_only)

        # Should NOT create any entities for devices without SIG characteristic data
        # RSSI-only devices are handled by BLE monitor integrations
        assert len(result.entity_data) == 0


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
        assert "DD:EE:FF" in device_name or "Bluetooth Device" in device_name

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

        # Device info should still be created for tracking
        assert result.devices is not None
        # But NO entities should be created without SIG characteristic data
        # (RSSI-only devices are handled by BLE monitor integrations)
        assert len(result.entity_data) == 0


class TestHasSupportedData:
    """Test cases for support_detector.has_supported_data filtering."""

    def test_device_with_known_service_data_is_supported(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that device with known GATT service UUID is supported."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        assert coordinator.support_detector.has_supported_data(
            mock_bluetooth_service_info_battery
        )

    def test_device_with_unknown_data_is_not_supported(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test that device with no known data is not supported."""
        service_info = BluetoothServiceInfoBleak(
            name="Unknown Device",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-75,
            manufacturer_data={0xFFFF: b"\x01\x02\x03"},  # Unknown manufacturer
            service_data={
                "00001234-0000-1000-8000-00805f9b34fb": b"\x00"
            },  # Unknown UUID
            service_uuids=[],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        assert not coordinator.support_detector.has_supported_data(service_info)

    def test_device_with_empty_data_is_not_supported(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test that device with no service or manufacturer data is not supported."""
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
        assert not coordinator.support_detector.has_supported_data(service_info)


class TestGetSupportedCharacteristics:
    """Test cases for support_detector.get_supported_characteristics."""

    def test_returns_characteristic_names_for_service_data(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Known service data UUIDs return characteristic names."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.support_detector.get_supported_characteristics(
            mock_bluetooth_service_info_battery
        )

        assert len(result) > 0
        # Each result is a DiscoveredCharacteristic named tuple
        for info in result:
            assert isinstance(info.characteristic.uuid, BluetoothUUID)
            assert isinstance(info.characteristic.name, str)
            assert len(info.characteristic.name) > 0
            assert isinstance(info.source, CharacteristicSource)

    def test_returns_empty_for_unknown_data(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Unknown service data returns an empty list."""
        service_info = BluetoothServiceInfoBleak(
            name="Unknown Device",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-75,
            manufacturer_data={},
            service_data={
                "00001234-0000-1000-8000-00805f9b34fb": b"\x00",
            },
            service_uuids=[],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0,
            tx_power=None,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.support_detector.get_supported_characteristics(
            service_info
        )
        assert result == []

    def test_includes_gatt_probe_results(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """GATT probe characteristic UUIDs are included in the result."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        from custom_components.bluetooth_sig_devices.device_validator import (
            GATTProbeResult,
        )

        service_info = BluetoothServiceInfoBleak(
            name="GATT Device",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-70,
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

        # Add a GATT probe result with Battery Level (0x2A19)
        battery_uuid = BluetoothUUID("2A19")
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="GATT Device",
            parseable_count=1,
            supported_char_uuids=(battery_uuid,),
        )

        result = coordinator.support_detector.get_supported_characteristics(
            service_info
        )
        assert len(result) >= 1
        names = [info.characteristic.name for info in result]
        # Should contain a non-empty name string
        assert all(len(n) > 0 for n in names)


class TestKnownCharacteristics:
    """Test cases for known_characteristics tracking."""

    def test_known_characteristics_initially_empty(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Coordinator starts with empty known_characteristics."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        assert coordinator.known_characteristics == {}

    def test_build_characteristics_summary_populates_known(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """_support_detector.build_characteristics_summary populates known_characteristics."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        supported = [
            DiscoveredCharacteristic(
                characteristic=UnknownCharacteristic(
                    info=CharacteristicInfo(
                        uuid=BluetoothUUID(0x2A6E),
                        name="Temperature",
                    )
                ),
            ),
            DiscoveredCharacteristic(
                characteristic=UnknownCharacteristic(
                    info=CharacteristicInfo(
                        uuid=BluetoothUUID(0x2A6F),
                        name="Humidity",
                    )
                ),
            ),
        ]
        result = coordinator._support_detector.build_characteristics_summary(
            "AA:BB:CC:DD:EE:FF",
            supported,
            coordinator.known_characteristics,
        )

        expected = "**Advertising data:**\n  \u2022 Unknown: Temperature\n  \u2022 Unknown: Humidity"
        assert result == expected
        assert "AA:BB:CC:DD:EE:FF" in coordinator.known_characteristics
        temp_uuid_str = str(BluetoothUUID(0x2A6E))
        humidity_uuid_str = str(BluetoothUUID(0x2A6F))
        assert (
            coordinator.known_characteristics["AA:BB:CC:DD:EE:FF"][temp_uuid_str]
            == "Unknown: Temperature"
        )
        assert (
            coordinator.known_characteristics["AA:BB:CC:DD:EE:FF"][humidity_uuid_str]
            == "Unknown: Humidity"
        )

    def test_get_known_characteristics_merges_gatt(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """get_known_characteristics merges advertisement and GATT data."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        from custom_components.bluetooth_sig_devices.device_validator import (
            GATTProbeResult,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        # Add advertisement-sourced characteristic
        coordinator.known_characteristics["AA:BB:CC:DD:EE:FF"] = {
            "uuid1": "Temperature",
        }

        # Add a GATT probe result with Battery Level (0x2A19)
        battery_uuid = BluetoothUUID("2A19")
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="GATT Device",
            parseable_count=1,
            supported_char_uuids=(battery_uuid,),
        )

        result = coordinator.get_known_characteristics("AA:BB:CC:DD:EE:FF")

        # Should contain both the advertisement and GATT characteristics
        assert "uuid1" in result
        assert result["uuid1"] == "Temperature"
        assert str(battery_uuid) in result

    def test_get_known_characteristics_empty_address(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """get_known_characteristics returns empty dict for unknown address."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.get_known_characteristics("FF:FF:FF:FF:FF:FF")
        assert result == {}

    def test_discovery_flow_includes_characteristics(
        self,
        hass,
    ) -> None:
        """Discovery flow data includes characteristics string."""
        from tests.conftest import make_hub_entry, make_service_info

        entry = make_hub_entry()
        entry.add_to_hass(hass)

        coordinator = BluetoothSIGCoordinator(hass, entry)
        service_info = make_service_info()

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.discovery_flow.async_create_flow"
        ) as mock_create_flow:
            coordinator._ensure_device_processor(service_info)

            mock_create_flow.assert_called_once()
            call_data = mock_create_flow.call_args[1]["data"]
            assert "characteristics" in call_data
            assert isinstance(call_data["characteristics"], str)
            # Battery Level UUID is in the test service_info
            assert len(call_data["characteristics"]) > 0


class TestCoordinatorGATTMethods:
    """Test cases for coordinator GATT-related methods."""

    def test_coordinator_has_gatt_probe_cache(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test coordinator initializes with GATT probe cache."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        assert hasattr(coordinator, "gatt_manager")
        assert coordinator.gatt_manager.probe_results == {}
        assert coordinator.gatt_manager.probe_failures == {}

    def test_has_supported_data_checks_gatt_results(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test _has_supported_data checks GATT probe results."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        from custom_components.bluetooth_sig_devices.device_validator import (
            GATTProbeResult,
        )

        service_info = BluetoothServiceInfoBleak(
            name="GATT Device",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-70,
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

        # Without GATT results, should not be supported
        assert not coordinator.support_detector.has_supported_data(service_info)

        # Add GATT probe result with parseable chars (must include real UUIDs)
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="GATT Device",
            parseable_count=2,
            supported_char_uuids=(BluetoothUUID("2A19"), BluetoothUUID("2A6E")),
        )

        # Now should be supported
        assert coordinator.support_detector.has_supported_data(service_info)

    def test_coordinator_has_support_detector(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test coordinator has support detector."""
        from custom_components.bluetooth_sig_devices.support_detector import (
            SupportDetector,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        assert hasattr(coordinator, "support_detector")
        assert isinstance(coordinator.support_detector, SupportDetector)

    async def test_probe_failures_incremented_on_generic_exception(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Non-timeout exceptions in _async_probe_and_setup must increment _probe_failures."""
        from unittest.mock import AsyncMock

        service_info = BluetoothServiceInfoBleak(
            name="GATT Device",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-70,
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
        coordinator.gatt_manager.async_probe_device = AsyncMock(
            side_effect=RuntimeError("adapter error")
        )

        # Invoke the probe-and-setup directly, bypassing the semaphore check
        await coordinator.gatt_manager.async_probe_and_setup(service_info)

        assert coordinator.gatt_manager.probe_failures.get("AA:BB:CC:DD:EE:FF", 0) == 1
        assert "AA:BB:CC:DD:EE:FF" not in coordinator.gatt_manager.pending_probes

    async def test_probe_task_tracked_in_ensure_device_processor(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """_ensure_device_processor stores the probe task in _probe_tasks."""
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close

        service_info = BluetoothServiceInfoBleak(
            name="GATT Device",
            address="AA:BB:CC:DD:EE:FF",
            rssi=-70,
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
        coordinator._async_add_entities = MagicMock()
        coordinator._entity_class = MagicMock()

        coordinator._ensure_device_processor(service_info)

        assert "AA:BB:CC:DD:EE:FF" in coordinator.gatt_manager.probe_tasks
        assert coordinator.gatt_manager.probe_tasks["AA:BB:CC:DD:EE:FF"] is mock_task


class TestGATTPollInterval:
    """Test cases for poll_interval wiring."""

    def test_poll_interval_stored(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test that poll_interval is stored on coordinator."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=120
        )
        assert coordinator.poll_interval == 120

    def test_poll_interval_default(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test default poll_interval is 300 seconds."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        assert coordinator.poll_interval == 300


class TestAdvertisementPathIndependence:
    """Test that advertisement updates do NOT include GATT data."""

    def test_advertisement_update_excludes_gatt_data(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Advertisement update should not contain any GATT-prefixed entity keys."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        gatt_keys = [k for k in result.entity_data if "gatt_" in str(k.key).lower()]
        assert gatt_keys == [], "GATT entities must not appear in advertisement updates"

    def test_no_cached_gatt_data_still_works(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test update_device works fine with no cached GATT data."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        # Should still have battery entity
        battery_keys = [k for k in result.entity_data if "2a19" in str(k.key).lower()]
        assert len(battery_keys) >= 1


class TestNeedsPollClosure:
    """Test cases for the _needs_poll closure factory."""

    @staticmethod
    def _make_device_entry(**opts: object) -> MagicMock:
        """Return a minimal mock config entry for a device."""
        entry = MagicMock(spec=ConfigEntry)
        entry.data = {"address": "AA:BB:CC:DD:EE:01"}
        entry.options = dict(opts)
        return entry

    def test_returns_false_without_probe_results(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """No probe results means no poll is needed."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        dev_entry = self._make_device_entry()
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        svc_info = MagicMock()
        assert check(svc_info, None) is False
        assert check(svc_info, 999.0) is False

    def test_returns_true_when_never_polled(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """First poll (last_poll=None) should always return True."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry()
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        assert check(MagicMock(), None) is True

    def test_returns_true_when_interval_elapsed(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Poll needed when poll_age >= poll_interval."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=120
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry()
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        assert check(MagicMock(), 120.0) is True
        assert check(MagicMock(), 121.0) is True

    def test_returns_false_when_interval_not_elapsed(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """No poll needed when poll_age < poll_interval."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=120
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry()
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        assert check(MagicMock(), 60.0) is False
        assert check(MagicMock(), 0.0) is False


class TestPollGattClosure:
    """Test cases for the _poll_gatt closure factory."""

    @staticmethod
    def _make_device_entry(**opts: object) -> MagicMock:
        """Return a minimal mock config entry for a device."""
        entry = MagicMock(spec=ConfigEntry)
        entry.data = {"address": "AA:BB:CC:DD:EE:01"}
        entry.options = dict(opts)
        return entry

    async def test_poll_raises_on_no_data(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """poll_method should raise RuntimeError when GATT returns None."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        coordinator.gatt_manager.async_poll_gatt_with_semaphore = MagicMock(
            return_value=None
        )
        # Make the mock awaitable
        import asyncio

        fut: asyncio.Future[None] = asyncio.Future()
        fut.set_result(None)
        coordinator.gatt_manager.async_poll_gatt_with_semaphore = MagicMock(
            return_value=fut
        )

        dev_entry = self._make_device_entry()
        poll = coordinator._poll_gatt("AA:BB:CC:DD:EE:01", dev_entry)
        import pytest

        with pytest.raises(RuntimeError, match="GATT poll returned no data"):
            await poll(MagicMock())

    async def test_poll_returns_update(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """poll_method should return the update from GATTManager."""
        import asyncio

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        expected = PassiveBluetoothDataUpdate(
            devices={}, entity_descriptions={}, entity_names={}, entity_data={}
        )
        fut: asyncio.Future[PassiveBluetoothDataUpdate] = asyncio.Future()
        fut.set_result(expected)
        coordinator.gatt_manager.async_poll_gatt_with_semaphore = MagicMock(
            return_value=fut
        )

        dev_entry = self._make_device_entry()
        poll = coordinator._poll_gatt("AA:BB:CC:DD:EE:01", dev_entry)
        result = await poll(MagicMock())
        assert result is expected


class TestGattEnabledOption:
    """Test GATT enabled/disabled option on _needs_poll and _poll_gatt."""

    @staticmethod
    def _make_device_entry(**opts: object) -> MagicMock:
        entry = MagicMock(spec=ConfigEntry)
        entry.data = {"address": "AA:BB:CC:DD:EE:01"}
        entry.options = dict(opts)
        return entry

    def test_needs_poll_returns_false_when_gatt_disabled(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When gatt_enabled=False, _needs_poll always returns False."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry(gatt_enabled=False)
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        # Should be False even with probe results and last_poll=None
        assert check(MagicMock(), None) is False

    def test_needs_poll_returns_true_when_gatt_enabled(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When gatt_enabled=True (default), _needs_poll works normally."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry(gatt_enabled=True)
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        assert check(MagicMock(), None) is True

    def test_needs_poll_defaults_to_enabled_when_option_absent(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When gatt_enabled option is not set, defaults to enabled."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry()  # No gatt_enabled option
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)
        assert check(MagicMock(), None) is True

    async def test_poll_gatt_raises_when_gatt_disabled(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When gatt_enabled=False, _poll_gatt raises RuntimeError."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        dev_entry = self._make_device_entry(gatt_enabled=False)
        poll = coordinator._poll_gatt("AA:BB:CC:DD:EE:01", dev_entry)

        import pytest

        with pytest.raises(RuntimeError, match="GATT disabled"):
            await poll(MagicMock())

    async def test_poll_gatt_succeeds_when_gatt_enabled(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When gatt_enabled=True, _poll_gatt proceeds normally."""
        import asyncio

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        expected = PassiveBluetoothDataUpdate(
            devices={}, entity_descriptions={}, entity_names={}, entity_data={}
        )
        fut: asyncio.Future[PassiveBluetoothDataUpdate] = asyncio.Future()
        fut.set_result(expected)
        coordinator.gatt_manager.async_poll_gatt_with_semaphore = MagicMock(
            return_value=fut
        )

        dev_entry = self._make_device_entry(gatt_enabled=True)
        poll = coordinator._poll_gatt("AA:BB:CC:DD:EE:01", dev_entry)
        result = await poll(MagicMock())
        assert result is expected


class TestDevicePollIntervalOverride:
    """Test per-device poll interval override in _needs_poll."""

    @staticmethod
    def _make_device_entry(**opts: object) -> MagicMock:
        entry = MagicMock(spec=ConfigEntry)
        entry.data = {"address": "AA:BB:CC:DD:EE:01"}
        entry.options = dict(opts)
        return entry

    def test_device_override_uses_device_interval(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When device_poll_interval is set (non-zero), it overrides the hub value."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=300
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        # Device interval is 60, hub is 300
        dev_entry = self._make_device_entry(device_poll_interval=60)
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)

        # 60 seconds elapsed — should need poll (device interval is 60)
        assert check(MagicMock(), 60.0) is True
        # 59 seconds elapsed — should NOT need poll
        assert check(MagicMock(), 59.0) is False

    def test_device_override_zero_uses_hub_default(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When device_poll_interval is 0, falls back to hub poll_interval."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=300
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry(device_poll_interval=0)
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)

        # 300 seconds elapsed — should need poll (hub default)
        assert check(MagicMock(), 300.0) is True
        # 299 seconds elapsed — should NOT need poll
        assert check(MagicMock(), 299.0) is False

    def test_device_override_absent_uses_hub_default(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """When device_poll_interval option is absent, uses hub default."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=300
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry()  # No device_poll_interval
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)

        assert check(MagicMock(), 300.0) is True
        assert check(MagicMock(), 299.0) is False

    def test_shorter_device_interval_than_hub(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """A device with a shorter interval polls more frequently than hub default."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=600
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry(device_poll_interval=30)
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)

        # 30 seconds — needs poll at device interval
        assert check(MagicMock(), 30.0) is True
        # 29 seconds — too soon
        assert check(MagicMock(), 29.0) is False
        # 600 seconds would be hub default, but device interval takes precedence
        assert check(MagicMock(), 600.0) is True

    def test_longer_device_interval_than_hub(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """A device with a longer interval polls less frequently than hub default."""
        coordinator = BluetoothSIGCoordinator(
            mock_hass, mock_config_entry, poll_interval=60
        )
        probe = MagicMock()
        probe.has_support.return_value = True
        coordinator.gatt_manager.probe_results["AA:BB:CC:DD:EE:01"] = probe

        dev_entry = self._make_device_entry(device_poll_interval=600)
        check = coordinator._needs_poll("AA:BB:CC:DD:EE:01", dev_entry)

        # 60 seconds (hub default) — NOT enough for device override
        assert check(MagicMock(), 60.0) is False
        # 600 seconds — needs poll at device interval
        assert check(MagicMock(), 600.0) is True


class TestInitialGattCache:
    """Test the initial GATT read cache in GATTManager.

    During ``async_probe_and_setup``, a successful probe should also
    read characteristic values and cache the result. The first call to
    ``async_poll_gatt_with_semaphore`` returns this cached data without
    acquiring the semaphore or opening a BLE connection.
    """

    async def test_cached_data_returned_on_first_poll(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """First poll returns cached initial read without semaphore."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        gatt = coordinator.gatt_manager

        cached_update = PassiveBluetoothDataUpdate(
            devices={},
            entity_descriptions={},
            entity_names={},
            entity_data={"key": 42},
        )
        gatt._initial_gatt_cache["AA:BB:CC:DD:EE:01"] = cached_update

        result = await gatt.async_poll_gatt_with_semaphore("AA:BB:CC:DD:EE:01")
        assert result is cached_update
        # Cache is consumed — second call would go through semaphore
        assert "AA:BB:CC:DD:EE:01" not in gatt._initial_gatt_cache

    async def test_cache_consumed_after_first_poll(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """After consuming cache, subsequent polls use live GATT read."""
        import asyncio

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        gatt = coordinator.gatt_manager

        cached_update = PassiveBluetoothDataUpdate(
            devices={},
            entity_descriptions={},
            entity_names={},
            entity_data={"key": 42},
        )
        gatt._initial_gatt_cache["AA:BB:CC:DD:EE:01"] = cached_update

        # First call returns cache
        result1 = await gatt.async_poll_gatt_with_semaphore("AA:BB:CC:DD:EE:01")
        assert result1 is cached_update

        # Second call falls through to async_poll_gatt_characteristics
        live_update = PassiveBluetoothDataUpdate(
            devices={},
            entity_descriptions={},
            entity_names={},
            entity_data={"key": 99},
        )
        fut: asyncio.Future[PassiveBluetoothDataUpdate | None] = asyncio.Future()
        fut.set_result(live_update)
        gatt.async_poll_gatt_characteristics = MagicMock(return_value=fut)

        result2 = await gatt.async_poll_gatt_with_semaphore("AA:BB:CC:DD:EE:01")
        assert result2 is live_update

    async def test_remove_device_clears_cache(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """remove_device should clear the initial GATT cache."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        gatt = coordinator.gatt_manager

        gatt._initial_gatt_cache["AA:BB:CC:DD:EE:01"] = MagicMock()
        gatt.remove_device("AA:BB:CC:DD:EE:01")
        assert "AA:BB:CC:DD:EE:01" not in gatt._initial_gatt_cache


class TestNotifyProbeComplete:
    """Test notify_probe_complete triggers immediate poll on processor."""

    def test_triggers_debounced_poll_when_processor_exists(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Should schedule debounced poll when processor has last_service_info."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        address = "AA:BB:CC:DD:EE:01"

        mock_proc = MagicMock()
        mock_proc._last_service_info = MagicMock()
        mock_proc._debounced_poll = MagicMock()
        coordinator._processor_coordinators[address] = mock_proc

        coordinator.notify_probe_complete(address)

        mock_proc._debounced_poll.async_schedule_call.assert_called_once()

    def test_noop_when_no_processor(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Should do nothing when no processor coordinator exists."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        # No exception raised, no processor to interact with
        coordinator.notify_probe_complete("AA:BB:CC:DD:EE:01")

    def test_noop_when_no_last_service_info(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Should not trigger poll when last_service_info is None."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        address = "AA:BB:CC:DD:EE:01"

        mock_proc = MagicMock()
        mock_proc._last_service_info = None
        mock_proc._debounced_poll = MagicMock()
        coordinator._processor_coordinators[address] = mock_proc

        coordinator.notify_probe_complete(address)

        mock_proc._debounced_poll.async_schedule_call.assert_not_called()


class TestAsyncStop:
    """Test cases for async_stop cleanup."""

    async def test_async_stop_cancels_probe_tasks(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test async_stop cancels all GATT probe tasks."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        coordinator.gatt_manager.probe_tasks["AA:BB:CC:DD:EE:01"] = mock_task1
        coordinator.gatt_manager.probe_tasks["AA:BB:CC:DD:EE:02"] = mock_task2
        coordinator.gatt_manager.pending_probes.add("AA:BB:CC:DD:EE:01")

        await coordinator.async_stop()

        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()
        assert coordinator.gatt_manager.probe_tasks == {}
        assert coordinator.gatt_manager.pending_probes == set()
        assert coordinator.processor_coordinators == {}
        assert coordinator.devices == {}

    async def test_async_stop_cancels_probe_tasks_individually(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test async_stop cancels all in-flight GATT probe tasks."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        mock_probe_task = MagicMock()
        coordinator.gatt_manager.probe_tasks["AA:BB:CC:DD:EE:01"] = mock_probe_task
        coordinator.gatt_manager.pending_probes.add("AA:BB:CC:DD:EE:01")

        await coordinator.async_stop()

        mock_probe_task.cancel.assert_called_once()
        assert coordinator.gatt_manager.probe_tasks == {}
        assert coordinator.gatt_manager.pending_probes == set()

    async def test_async_stop_cancels_discovery(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test async_stop cancels the discovery callback."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        mock_cancel = MagicMock()
        coordinator._cancel_discovery = mock_cancel

        await coordinator.async_stop()

        mock_cancel.assert_called_once()
        assert coordinator._cancel_discovery is None


# ---------------------------------------------------------------------------
# device_class and precision wired into entity descriptions
# ---------------------------------------------------------------------------


class TestDeviceClassWiringSimple:
    """Tests that device_class appears correctly on simple entities."""

    def test_battery_entity_has_battery_device_class(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Battery Level entity should have device_class=BATTERY."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        battery_keys = [k for k in result.entity_data if "2a19" in str(k.key).lower()]
        assert len(battery_keys) >= 1

        for key in battery_keys:
            desc = result.entity_descriptions[key]
            if desc.name == "Battery Level":
                assert desc.device_class == SensorDeviceClass.BATTERY
                break

    def test_temperature_entity_has_temperature_device_class(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_temperature: BluetoothServiceInfoBleak,
    ) -> None:
        """Temperature entity should have device_class=TEMPERATURE."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_temperature)

        temp_keys = [k for k in result.entity_data if "2a6e" in str(k.key).lower()]
        assert len(temp_keys) >= 1

        for key in temp_keys:
            desc = result.entity_descriptions[key]
            if desc.name == "Temperature":
                assert desc.device_class == SensorDeviceClass.TEMPERATURE
                break

    def test_humidity_entity_has_humidity_device_class(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_humidity: BluetoothServiceInfoBleak,
    ) -> None:
        """Humidity entity should have device_class=HUMIDITY."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_humidity)

        humidity_keys = [k for k in result.entity_data if "2a6f" in str(k.key).lower()]
        assert len(humidity_keys) >= 1

        for key in humidity_keys:
            desc = result.entity_descriptions[key]
            if desc.name == "Humidity":
                assert desc.device_class == SensorDeviceClass.HUMIDITY
                break


# ---------------------------------------------------------------------------
# Helper to build a service_info with controllable address type metadata
# ---------------------------------------------------------------------------


def _make_service_info_with_addr_type(
    address: str,
    *,
    address_type: str | None = None,
    connectable: bool = True,
    service_data: dict | None = None,
) -> BluetoothServiceInfoBleak:
    """Build a BluetoothServiceInfoBleak with configurable BlueZ AddressType."""
    device = MagicMock()
    if address_type is not None:
        device.details = {"props": {"AddressType": address_type}}
    else:
        device.details = {}
    return BluetoothServiceInfoBleak(
        name="Test",
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data=service_data or {},
        service_uuids=[],
        source="local",
        device=device,
        advertisement=MagicMock(),
        connectable=connectable,
        time=0,
        tx_power=None,
    )


class TestEphemeralAddressFiltering:
    """Test that ephemeral (RPA/NRPA) addresses are filtered out of discovery."""

    def test_rpa_address_is_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """RPA address (random, MSB 0x40-0x7F) is never added to _seen_devices."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type(
            "5A:BB:CC:DD:EE:FF", address_type="random"
        )

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "5A:BB:CC:DD:EE:FF" not in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 1

    def test_nrpa_address_is_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """NRPA address (random, MSB 0x00-0x3F) is never added to _seen_devices."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type(
            "1A:BB:CC:DD:EE:FF", address_type="random"
        )

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "1A:BB:CC:DD:EE:FF" not in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 1

    def test_public_address_is_not_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Public address passes through the filter."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type(
            "AA:BB:CC:DD:EE:FF", address_type="public"
        )

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "AA:BB:CC:DD:EE:FF" in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 0

    def test_random_static_address_is_not_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Random Static address (random, MSB 0xC0-0xFF) passes through."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type(
            "C0:11:22:33:44:55", address_type="random"
        )

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "C0:11:22:33:44:55" in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 0

    def test_unknown_address_type_is_not_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Address with no BlueZ metadata (unknown type) is not filtered."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type("AA:BB:CC:DD:EE:FF", address_type=None)

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "AA:BB:CC:DD:EE:FF" in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 0

    def test_filtered_count_increments_for_multiple_ephemeral(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Multiple ephemeral addresses all increment the counter."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        from homeassistant.components.bluetooth import BluetoothChange

        for i in range(5):
            si = _make_service_info_with_addr_type(
                f"5{i}:BB:CC:DD:EE:FF", address_type="random"
            )
            coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert coordinator.discovery_tracker.filtered_ephemeral_count == 5
        assert len(coordinator.discovery_tracker.seen_devices) == 0

    def test_last_seen_time_updated_for_static(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Static addresses get their last-seen timestamp updated."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type(
            "AA:BB:CC:DD:EE:FF", address_type="public"
        )

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "AA:BB:CC:DD:EE:FF" in coordinator.discovery_tracker.last_seen_time
        assert coordinator.discovery_tracker.last_seen_time["AA:BB:CC:DD:EE:FF"] > 0

    def test_last_seen_time_not_set_for_ephemeral(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Ephemeral addresses do NOT get a last-seen timestamp."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type(
            "5A:BB:CC:DD:EE:FF", address_type="random"
        )

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "5A:BB:CC:DD:EE:FF" not in coordinator.discovery_tracker.last_seen_time

    def test_no_metadata_rpa_range_is_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """No metadata + RPA-range MAC (0x40-0x7F) is filtered by heuristic."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type("5A:BB:CC:DD:EE:FF", address_type=None)

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "5A:BB:CC:DD:EE:FF" not in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 1

    def test_no_metadata_nrpa_range_is_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """No metadata + NRPA-range MAC (0x00-0x3F) is filtered by heuristic."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type("1A:BB:CC:DD:EE:FF", address_type=None)

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "1A:BB:CC:DD:EE:FF" not in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 1

    def test_no_metadata_reserved_range_not_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """No metadata + reserved-range MAC (0x80-0xBF) is NOT filtered."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        si = _make_service_info_with_addr_type("AA:BB:CC:DD:EE:FF", address_type=None)

        from homeassistant.components.bluetooth import BluetoothChange

        coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert "AA:BB:CC:DD:EE:FF" in coordinator.discovery_tracker.seen_devices
        assert coordinator.discovery_tracker.filtered_ephemeral_count == 0

    def test_real_rpa_flood_no_metadata_all_filtered(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Regression: all 14 RPA addresses from original issue report are filtered.

        These addresses had no BlueZ/ESPHome metadata and were incorrectly
        treated as stable, causing 14 spurious discovery flows.
        """
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        from homeassistant.components.bluetooth import BluetoothChange

        rpa_addresses = [
            "69:D1:8A:16:39:16",
            "55:4B:2F:2A:50:7F",
            "50:41:96:6E:D6:2B",
            "56:2B:FA:C5:69:AE",
            "6B:1C:D9:7A:B7:AB",
            "58:38:DB:D8:74:F0",
            "66:79:1D:DD:62:AE",
            "4E:F4:2D:05:77:05",
            "5A:3C:73:1A:B9:1E",
            "5C:76:4C:69:80:D2",
            "71:22:4D:B9:6F:C6",
            "65:8B:54:95:02:C5",
            "47:3C:57:DF:0A:BE",
            "70:44:43:9B:2C:A5",
        ]
        for addr in rpa_addresses:
            si = _make_service_info_with_addr_type(addr, address_type=None)
            coordinator._async_device_discovered(si, BluetoothChange.ADVERTISEMENT)

        assert len(coordinator.discovery_tracker.seen_devices) == 0
        assert coordinator.discovery_tracker.filtered_ephemeral_count == len(
            rpa_addresses
        )


class TestStaleDeviceCleanup:
    """Test periodic stale device cleanup logic."""

    def test_stale_entries_are_removed(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Addresses older than DEFAULT_STALE_DEVICE_TIMEOUT are cleaned up."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        addr = "AA:BB:CC:DD:EE:01"

        # Manually inject a stale entry
        coordinator.discovery_tracker.seen_devices.add(addr)
        coordinator.discovery_tracker.rejected_devices.add(addr)
        coordinator.discovery_tracker.discovery_triggered.add(addr)
        coordinator.gatt_manager.probe_failures[addr] = 2
        coordinator.discovery_tracker.last_seen_time[addr] = (
            time.monotonic() - DEFAULT_STALE_DEVICE_TIMEOUT - 10
        )

        coordinator.discovery_tracker.async_cleanup_stale_devices()

        assert addr not in coordinator.discovery_tracker.seen_devices
        assert addr not in coordinator.discovery_tracker.rejected_devices
        assert addr not in coordinator.discovery_tracker.discovery_triggered
        assert addr not in coordinator.gatt_manager.probe_failures
        assert addr not in coordinator.discovery_tracker.last_seen_time

    def test_fresh_entries_are_not_removed(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Recently-seen addresses are NOT cleaned up."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        addr = "AA:BB:CC:DD:EE:02"

        coordinator.discovery_tracker.seen_devices.add(addr)
        coordinator.discovery_tracker.last_seen_time[addr] = time.monotonic()

        coordinator.discovery_tracker.async_cleanup_stale_devices()

        assert addr in coordinator.discovery_tracker.seen_devices
        assert addr in coordinator.discovery_tracker.last_seen_time

    def test_active_processor_entries_are_never_evicted(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Addresses with active processor coordinators are never removed."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        addr = "AA:BB:CC:DD:EE:03"

        coordinator.discovery_tracker.seen_devices.add(addr)
        coordinator.discovery_tracker.last_seen_time[addr] = (
            time.monotonic() - DEFAULT_STALE_DEVICE_TIMEOUT - 100
        )
        coordinator.processor_coordinators[addr] = MagicMock()

        coordinator.discovery_tracker.async_cleanup_stale_devices()

        assert addr in coordinator.discovery_tracker.seen_devices
        assert addr in coordinator.discovery_tracker.last_seen_time

    def test_config_entry_addresses_are_never_evicted(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Addresses with confirmed config entries are never removed."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        addr = "AA:BB:CC:DD:EE:04"

        coordinator.discovery_tracker.seen_devices.add(addr)
        coordinator.discovery_tracker.last_seen_time[addr] = (
            time.monotonic() - DEFAULT_STALE_DEVICE_TIMEOUT - 100
        )

        # Simulate _has_config_entry returning True
        with patch.object(coordinator, "_has_config_entry", return_value=True):
            coordinator.discovery_tracker.async_cleanup_stale_devices()

        assert addr in coordinator.discovery_tracker.seen_devices

    def test_gatt_probe_results_cleaned_for_stale(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Stale cleanup also removes GATT probe caches and device instances."""
        from custom_components.bluetooth_sig_devices.device_validator import (
            GATTProbeResult,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        addr = "AA:BB:CC:DD:EE:05"

        coordinator.discovery_tracker.seen_devices.add(addr)
        coordinator.discovery_tracker.last_seen_time[addr] = (
            time.monotonic() - DEFAULT_STALE_DEVICE_TIMEOUT - 10
        )
        coordinator.gatt_manager.probe_results[addr] = GATTProbeResult(
            address=addr, parseable_count=2
        )
        coordinator.devices[addr] = MagicMock()

        coordinator.discovery_tracker.async_cleanup_stale_devices()

        assert addr not in coordinator.gatt_manager.probe_results
        assert addr not in coordinator.devices


class TestSeenDevicesEviction:
    """Test bounded _seen_devices set with LRU eviction."""

    def test_evict_oldest_removes_quarter_of_entries(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """_evict_oldest_seen removes ~25% of the oldest entries."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        base_time = time.monotonic()
        for i in range(100):
            addr = f"AA:BB:CC:{i:02X}:00:00"
            coordinator.discovery_tracker.seen_devices.add(addr)
            coordinator.discovery_tracker.last_seen_time[addr] = base_time + i

        assert len(coordinator.discovery_tracker.seen_devices) == 100

        coordinator.discovery_tracker._evict_oldest_seen()

        # Should have removed ~25 entries
        assert len(coordinator.discovery_tracker.seen_devices) == 75

    def test_eviction_removes_oldest_by_timestamp(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Eviction targets the least-recently-seen addresses."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        old_addr = "AA:BB:CC:00:00:01"
        new_addr = "AA:BB:CC:00:00:02"

        coordinator.discovery_tracker.seen_devices.add(old_addr)
        coordinator.discovery_tracker.last_seen_time[old_addr] = time.monotonic() - 1000

        coordinator.discovery_tracker.seen_devices.add(new_addr)
        coordinator.discovery_tracker.last_seen_time[new_addr] = time.monotonic()

        # Force eviction of 1 entry (25% of 2, min 1)
        coordinator.discovery_tracker._evict_oldest_seen()

        # The old one should be gone, the new one should remain
        assert old_addr not in coordinator.discovery_tracker.seen_devices
        assert new_addr in coordinator.discovery_tracker.seen_devices
