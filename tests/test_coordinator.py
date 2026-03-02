"""Tests for coordinator.py - device management and entity creation."""

from __future__ import annotations

import datetime
import enum
from unittest.mock import MagicMock

from bluetooth_sig.gatt.characteristics.body_sensor_location import BodySensorLocation
from bluetooth_sig.gatt.characteristics.cycling_power_vector import (
    CrankRevolutionData,
    CyclingPowerVectorData,
    CyclingPowerVectorFlags,
)
from bluetooth_sig.gatt.characteristics.heart_rate_measurement import (
    HeartRateData,
    HeartRateMeasurementFlags,
    SensorContactState,
)
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.gatt.characteristics.templates.data_structures import VectorData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
)
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.bluetooth_sig_devices.const import DOMAIN
from custom_components.bluetooth_sig_devices.coordinator import (
    _UNIT_TO_DEVICE_CLASS,
    BluetoothSIGCoordinator,
    _normalize_uuid_short,
    _resolve_device_class,
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
        assert coordinator._processor_coordinators == {}
        assert coordinator.translator is not None

    def test_set_entity_adder(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test setting the entity adder callback."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        mock_add_entities = MagicMock()
        mock_entity_class = MagicMock()

        coordinator.set_entity_adder(mock_add_entities, mock_entity_class)

        assert coordinator._async_add_entities is mock_add_entities
        assert coordinator._entity_class is mock_entity_class


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
        assert instance.python_type is int

    def test_temperature_registry_lookup(self) -> None:
        """Test looking up Temperature in CharacteristicRegistry."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            "00002a6e-0000-1000-8000-00805f9b34fb"
        )

        assert char_class is not None

        instance = char_class()
        assert instance.name == "Temperature"
        assert instance.unit == "°C"
        # Temperature uses float python_type (scaled from raw int)
        assert instance.python_type is float

    def test_heart_rate_registry_lookup(self) -> None:
        """Test looking up Heart Rate Measurement in CharacteristicRegistry."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
            "00002a37-0000-1000-8000-00805f9b34fb"
        )

        assert char_class is not None

        instance = char_class()
        assert instance.name == "Heart Rate Measurement"
        assert instance.unit == "beats per minute"
        # Heart Rate Measurement has a struct python_type (not a simple primitive)
        assert instance.python_type is not None
        assert instance.python_type not in (int, float, str, bool)

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
    """Test cases for _has_supported_data filtering."""

    def test_device_with_known_service_data_is_supported(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that device with known GATT service UUID is supported."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        assert coordinator._has_supported_data(mock_bluetooth_service_info_battery)

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
        assert not coordinator._has_supported_data(service_info)

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
        assert not coordinator._has_supported_data(service_info)


class TestGATTProbeResult:
    """Test cases for GATTProbeResult dataclass."""

    def test_gatt_probe_result_has_support(self) -> None:
        """Test GATTProbeResult.has_support method."""
        from custom_components.bluetooth_sig_devices.device_validator import (
            GATTProbeResult,
        )

        # No parseable characteristics
        result_empty = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
            parseable_count=0,
        )
        assert result_empty.has_support() is False

        # Has parseable characteristics
        result_with_chars = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
            parseable_count=3,
        )
        assert result_with_chars.has_support() is True


class TestCoordinatorGATTMethods:
    """Test cases for coordinator GATT-related methods."""

    def test_coordinator_has_gatt_probe_cache(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test coordinator initializes with GATT probe cache."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        assert hasattr(coordinator, "_gatt_probe_results")
        assert coordinator._gatt_probe_results == {}
        assert hasattr(coordinator, "_probe_failures")
        assert coordinator._probe_failures == {}

    def test_has_supported_data_checks_gatt_results(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test _has_supported_data checks GATT probe results."""
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
        assert not coordinator._has_supported_data(service_info)

        # Add GATT probe result with parseable chars
        coordinator._gatt_probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="GATT Device",
            parseable_count=2,
        )

        # Now should be supported
        assert coordinator._has_supported_data(service_info)

    def test_coordinator_has_validator(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test coordinator has device validator."""
        from custom_components.bluetooth_sig_devices.device_validator import (
            DeviceValidator,
        )

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        assert hasattr(coordinator, "validator")
        assert isinstance(coordinator.validator, DeviceValidator)

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
        coordinator.async_probe_device = AsyncMock(
            side_effect=RuntimeError("adapter error")
        )

        # Invoke the probe-and-setup directly, bypassing the semaphore check
        await coordinator._async_probe_and_setup(service_info)

        assert coordinator._probe_failures.get("AA:BB:CC:DD:EE:FF", 0) == 1
        assert "AA:BB:CC:DD:EE:FF" not in coordinator._pending_probes

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

        assert "AA:BB:CC:DD:EE:FF" in coordinator._probe_tasks
        assert coordinator._probe_tasks["AA:BB:CC:DD:EE:FF"] is mock_task


class TestGATTPollInterval:
    """Test cases for poll_interval wiring and GATT polling lifecycle."""

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

    def test_gatt_poll_tasks_initialised_empty(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test GATT poll task dict is initialised empty."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        assert coordinator._gatt_poll_tasks == {}
        assert coordinator._cached_gatt_updates == {}

    def test_start_gatt_poll_loop_creates_task(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test _start_gatt_poll_loop creates a background task."""
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            """Close the coroutine to avoid 'never awaited' warning."""
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        coordinator._start_gatt_poll_loop("AA:BB:CC:DD:EE:01")

        mock_hass.async_create_task.assert_called_once()
        assert "AA:BB:CC:DD:EE:01" in coordinator._gatt_poll_tasks
        assert coordinator._gatt_poll_tasks["AA:BB:CC:DD:EE:01"] is mock_task

    def test_start_gatt_poll_loop_idempotent(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test _start_gatt_poll_loop does not create duplicate tasks."""
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            """Close the coroutine to avoid 'never awaited' warning."""
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        coordinator._start_gatt_poll_loop("AA:BB:CC:DD:EE:01")
        coordinator._start_gatt_poll_loop("AA:BB:CC:DD:EE:01")

        assert mock_hass.async_create_task.call_count == 1


class TestGATTCacheMerge:
    """Test cases for merging cached GATT data into advertisement updates."""

    def test_cached_gatt_data_merged_into_update(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Test that cached GATT poll data is merged into update_device output."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        # Simulate cached GATT data for this device
        from homeassistant.components.bluetooth.passive_update_processor import (
            PassiveBluetoothEntityKey,
        )
        from homeassistant.components.sensor import SensorEntityDescription

        gatt_key = PassiveBluetoothEntityKey("gatt_2a6e", "aabbccddeee01")
        cached_update = PassiveBluetoothDataUpdate(
            devices={},
            entity_descriptions={
                gatt_key: SensorEntityDescription(
                    key="gatt_2a6e",
                    name="Temperature",
                    native_unit_of_measurement="°C",
                )
            },
            entity_names={gatt_key: "Temperature"},
            entity_data={gatt_key: 22.5},
        )
        coordinator._cached_gatt_updates["AA:BB:CC:DD:EE:01"] = cached_update

        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        # Should have both the battery entity from advertisement AND the GATT temperature
        assert gatt_key in result.entity_data
        assert result.entity_data[gatt_key] == 22.5

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


class TestAsyncStop:
    """Test cases for async_stop cleanup."""

    async def test_async_stop_cancels_poll_tasks(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test async_stop cancels all GATT poll tasks."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        # Simulate running poll tasks
        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        coordinator._gatt_poll_tasks["AA:BB:CC:DD:EE:01"] = mock_task1
        coordinator._gatt_poll_tasks["AA:BB:CC:DD:EE:02"] = mock_task2
        coordinator._cached_gatt_updates["AA:BB:CC:DD:EE:01"] = MagicMock()

        await coordinator.async_stop()

        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()
        assert coordinator._gatt_poll_tasks == {}
        assert coordinator._cached_gatt_updates == {}
        assert coordinator._processor_coordinators == {}
        assert coordinator.devices == {}

    async def test_async_stop_cancels_probe_tasks(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Test async_stop cancels all in-flight GATT probe tasks."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)

        mock_probe_task = MagicMock()
        coordinator._probe_tasks["AA:BB:CC:DD:EE:01"] = mock_probe_task
        coordinator._pending_probes.add("AA:BB:CC:DD:EE:01")

        await coordinator.async_stop()

        mock_probe_task.cancel.assert_called_once()
        assert coordinator._probe_tasks == {}
        assert coordinator._pending_probes == set()

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
# Local test enums — used to test _to_ha_state without depending on library
# __str__ changes that are not yet released.
# ---------------------------------------------------------------------------


class _TestSensorLocation(enum.IntEnum):
    """Minimal IntEnum matching SensorLocationValue's shape."""

    OTHER = 0
    TOP_OF_SHOE = 1
    IN_SHOE = 2


class _TestSensorLocationWithStr(enum.IntEnum):
    """IntEnum that already provides a human-readable __str__."""

    OTHER = 0
    TOP_OF_SHOE = 1
    IN_SHOE = 2

    def __str__(self) -> str:
        return self.name.replace("_", " ").title()


class _TestKeyboardFlags(enum.IntFlag):
    """Minimal IntFlag matching KeyboardLEDs's shape."""

    NUM_LOCK = 1
    CAPS_LOCK = 2
    SCROLL_LOCK = 4


class TestToHaState:
    """Tests for BluetoothSIGCoordinator._to_ha_state.

    Covers every branch in the isinstance chain and validates the ordering
    guarantees (bool before int, IntEnum before plain int, etc.).
    """

    # --- bool (must be checked before int) ---

    def test_bool_true(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(True)
        assert result is True
        assert isinstance(result, bool)

    def test_bool_false(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(False)
        assert result is False
        assert isinstance(result, bool)

    def test_bool_not_coerced_to_int(self) -> None:
        """bool subclasses int — ensure we return bool, not int(1)."""
        result = BluetoothSIGCoordinator._to_ha_state(True)
        assert type(result) is bool

    # --- IntEnum → str() ---

    def test_intenum_returns_str(self) -> None:
        """IntEnum values must be stringified, not cast to int."""
        result = BluetoothSIGCoordinator._to_ha_state(_TestSensorLocation.TOP_OF_SHOE)
        assert isinstance(result, str)

    def test_intenum_without_custom_str_returns_name(self) -> None:
        """IntEnum without __str__ override → returns .name (member identifier)."""
        result = BluetoothSIGCoordinator._to_ha_state(_TestSensorLocation.OTHER)
        assert result == "OTHER"

    def test_intenum_with_custom_str_returns_name(self) -> None:
        """IntEnum with __str__ override → .name is still returned (not str())."""
        result = BluetoothSIGCoordinator._to_ha_state(
            _TestSensorLocationWithStr.TOP_OF_SHOE
        )
        assert result == "TOP_OF_SHOE"

    def test_intenum_is_not_plain_int(self) -> None:
        """IntEnum must NOT return a plain int — it should return str."""
        result = BluetoothSIGCoordinator._to_ha_state(_TestSensorLocation.IN_SHOE)
        assert not isinstance(result, int)

    def test_real_library_intenum_barometric_pressure_trend(self) -> None:
        """Real library IntEnum (BarometricPressureTrend) returns .name."""
        from bluetooth_sig.gatt.characteristics.barometric_pressure_trend import (
            BarometricPressureTrend,
        )

        val = BarometricPressureTrend(0)
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, str)
        assert result == val.name

    def test_real_library_intenum_door_window_status(self) -> None:
        """Real library IntEnum (DoorWindowOpenStatus) returns .name."""
        from bluetooth_sig.gatt.characteristics.door_window_status import (
            DoorWindowOpenStatus,
        )

        val = DoorWindowOpenStatus(0)
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, str)
        assert result == val.name

    # --- IntFlag → int() ---

    def test_intflag_returns_int(self) -> None:
        """IntFlag values should become plain int."""
        result = BluetoothSIGCoordinator._to_ha_state(
            _TestKeyboardFlags.NUM_LOCK | _TestKeyboardFlags.CAPS_LOCK
        )
        assert isinstance(result, int)
        assert not isinstance(result, enum.IntFlag)
        assert result == 3

    def test_intflag_single_flag_returns_int(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(_TestKeyboardFlags.SCROLL_LOCK)
        assert isinstance(result, int)
        assert result == 4

    def test_intflag_zero_returns_int(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(_TestKeyboardFlags(0))
        assert isinstance(result, int)
        assert result == 0

    def test_real_library_intflag_keyboard_leds(self) -> None:
        """Real library IntFlag (KeyboardLEDs)."""
        from bluetooth_sig.gatt.characteristics.boot_keyboard_output_report import (
            KeyboardLEDs,
        )

        val = KeyboardLEDs(3)  # NUM_LOCK | CAPS_LOCK
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, int)
        assert not isinstance(result, enum.IntFlag)
        assert result == 3

    # --- plain int ---

    def test_plain_int(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(42)
        assert result == 42
        assert type(result) is int

    def test_plain_int_zero(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(0)
        assert result == 0
        assert type(result) is int

    def test_plain_int_negative(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(-7)
        assert result == -7

    # --- float ---

    def test_float(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(36.5)
        assert result == 36.5
        assert type(result) is float

    def test_float_zero(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(0.0)
        assert result == 0.0
        assert type(result) is float

    def test_float_negative(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state(-273.15)
        assert result == -273.15

    # --- str ---

    def test_str(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state("hello")
        assert result == "hello"
        assert type(result) is str

    def test_str_empty(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state("")
        assert result == ""

    # --- fallback: str() for everything else ---

    def test_timedelta_falls_through_to_str(self) -> None:
        val = datetime.timedelta(seconds=150)
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, str)
        assert result == str(val)

    def test_datetime_falls_through_to_str(self) -> None:
        val = datetime.datetime(2025, 6, 15, 12, 30, 0)
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, str)
        assert result == str(val)

    def test_date_falls_through_to_str(self) -> None:
        val = datetime.date(2025, 6, 15)
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, str)
        assert result == str(val)

    def test_none_falls_through_to_str(self) -> None:
        """None shouldn't normally reach _to_ha_state but it must not crash."""
        result = BluetoothSIGCoordinator._to_ha_state(None)
        assert result == "None"
        assert isinstance(result, str)

    def test_dict_falls_through_to_str(self) -> None:
        """Dict must not crash — gets stringified."""
        result = BluetoothSIGCoordinator._to_ha_state({"key": "val"})
        assert isinstance(result, str)

    def test_list_falls_through_to_str(self) -> None:
        result = BluetoothSIGCoordinator._to_ha_state([1, 2, 3])
        assert isinstance(result, str)

    # --- ordering / edge cases ---

    def test_bool_wins_over_int(self) -> None:
        """bool is a subclass of int. _to_ha_state must return bool, not int."""
        assert type(BluetoothSIGCoordinator._to_ha_state(True)) is bool
        assert type(BluetoothSIGCoordinator._to_ha_state(False)) is bool

    def test_intenum_wins_over_int(self) -> None:
        """IntEnum is a subclass of int. Must go through str(), not int()."""
        val = _TestSensorLocation.TOP_OF_SHOE
        result = BluetoothSIGCoordinator._to_ha_state(val)
        assert isinstance(result, str)

    def test_intflag_does_not_hit_intenum_branch(self) -> None:
        """IntFlag is NOT a subclass of IntEnum — should hit the int branch."""
        val = _TestKeyboardFlags.NUM_LOCK
        result = BluetoothSIGCoordinator._to_ha_state(val)
        # IntFlag → int branch → plain int
        assert isinstance(result, int)
        assert not isinstance(result, str)


# ---------------------------------------------------------------------------
# Recursive struct decomposition tests (using real bluetooth-sig library types)
# ---------------------------------------------------------------------------


class TestAddStructEntities:
    """Tests for _add_struct_entities recursive decomposition."""

    @staticmethod
    def _run(
        struct_value: object,
        char_name: str = "Test Char",
        uuid: str = "2A37",
        unit: str | None = "bpm",
        is_diagnostic: bool = False,
    ) -> tuple[dict, dict, dict]:
        """Helper to call _add_struct_entities and return the three dicts."""
        coord = BluetoothSIGCoordinator.__new__(BluetoothSIGCoordinator)
        descs: dict = {}
        names: dict = {}
        data: dict = {}
        coord._add_struct_entities(
            "aabbccddee01",
            uuid,
            char_name,
            struct_value,
            unit,
            is_diagnostic,
            descs,
            names,
            data,
        )
        return descs, names, data

    def test_flat_struct_creates_leaf_entities(self) -> None:
        """VectorData (flat struct) → one entity per field."""
        descs, names, data = self._run(
            VectorData(x_axis=1.0, y_axis=2.0, z_axis=3.0),
        )
        keys = {k.key for k in data}
        assert "2A37_x_axis" in keys
        assert "2A37_y_axis" in keys
        assert "2A37_z_axis" in keys
        assert len(data) == 3

    def test_flat_struct_values_coerced(self) -> None:
        """VectorData leaf values go through _to_ha_state (float passthrough)."""
        _, _, data = self._run(
            VectorData(x_axis=1.5, y_axis=2.5, z_axis=3.5),
        )
        values = list(data.values())
        assert 1.5 in values
        assert 2.5 in values
        assert 3.5 in values

    def test_nested_struct_recurses(self) -> None:
        """CyclingPowerVectorData → crank_revolution_data is recursed into."""
        crank = CrankRevolutionData(
            crank_revolutions=100,
            last_crank_event_time=0.5,
        )
        vec = CyclingPowerVectorData(
            flags=CyclingPowerVectorFlags(0),
            crank_revolution_data=crank,
            first_crank_measurement_angle=45.0,
            instantaneous_force_magnitude_array=None,
            instantaneous_torque_magnitude_array=None,
        )
        _, _, data = self._run(vec)
        keys = {k.key for k in data}
        # Nested struct fields get the parent field name as prefix
        assert "2A37_crank_revolution_data_crank_revolutions" in keys
        assert "2A37_crank_revolution_data_last_crank_event_time" in keys
        # Direct leaf fields
        assert "2A37_flags" in keys
        assert "2A37_first_crank_measurement_angle" in keys

    def test_nested_struct_leaf_values(self) -> None:
        """Nested CrankRevolutionData leaf values are coerced correctly."""
        crank = CrankRevolutionData(
            crank_revolutions=42,
            last_crank_event_time=1.25,
        )
        vec = CyclingPowerVectorData(
            flags=CyclingPowerVectorFlags(0),
            crank_revolution_data=crank,
            first_crank_measurement_angle=90.0,
            instantaneous_force_magnitude_array=None,
            instantaneous_torque_magnitude_array=None,
        )
        _, _, data = self._run(vec)
        val_map = {k.key: v for k, v in data.items()}
        assert val_map["2A37_crank_revolution_data_crank_revolutions"] == 42
        assert val_map["2A37_crank_revolution_data_last_crank_event_time"] == 1.25
        assert val_map["2A37_first_crank_measurement_angle"] == 90.0

    def test_nested_struct_display_names(self) -> None:
        """Display names include the full path through nested structs."""
        crank = CrankRevolutionData(
            crank_revolutions=100,
            last_crank_event_time=0.5,
        )
        vec = CyclingPowerVectorData(
            flags=CyclingPowerVectorFlags(0),
            crank_revolution_data=crank,
            first_crank_measurement_angle=45.0,
            instantaneous_force_magnitude_array=None,
            instantaneous_torque_magnitude_array=None,
        )
        _, names, _ = self._run(vec, char_name="Cycling Power Vector")
        name_map = {k.key: v for k, v in names.items()}
        assert name_map["2A37_crank_revolution_data_crank_revolutions"] == (
            "Cycling Power Vector Crank Revolution Data Crank Revolutions"
        )
        assert name_map["2A37_first_crank_measurement_angle"] == (
            "Cycling Power Vector First Crank Measurement Angle"
        )

    def test_nested_struct_total_entity_count(self) -> None:
        """CyclingPowerVectorData produces correct total entity count.

        flags (leaf) + 2 crank fields (nested) + angle (leaf)
        + force_array (leaf) + torque_array (leaf) = 6.
        """
        crank = CrankRevolutionData(
            crank_revolutions=100,
            last_crank_event_time=0.5,
        )
        vec = CyclingPowerVectorData(
            flags=CyclingPowerVectorFlags(0),
            crank_revolution_data=crank,
            first_crank_measurement_angle=45.0,
            instantaneous_force_magnitude_array=None,
            instantaneous_torque_magnitude_array=None,
        )
        _, _, data = self._run(vec)
        assert len(data) == 6

    def test_heart_rate_struct_diverse_types(self) -> None:
        """HeartRateData exercises int, IntEnum, IntFlag, tuple, and optional."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8, 0.9),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        _, _, data = self._run(hr)
        val_map = {k.key: v for k, v in data.items()}
        # plain int preserved
        assert val_map["2A37_heart_rate"] == 72
        # IntEnum → str
        assert isinstance(val_map["2A37_sensor_location"], str)
        # IntFlag → int (IntFlag is NOT IntEnum, falls to int branch)
        assert isinstance(val_map["2A37_flags"], int)
        assert val_map["2A37_flags"] == 0
        # tuple → str (fallback)
        assert isinstance(val_map["2A37_rr_intervals"], str)
        assert len(data) == 6

    def test_struct_intenum_leaf_coerced_to_str(self) -> None:
        """IntEnum fields inside a struct go through str() coercion."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8,),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        _, _, data = self._run(hr)
        val_map = {k.key: v for k, v in data.items()}
        # BodySensorLocation is IntEnum without custom __str__
        assert isinstance(val_map["2A37_sensor_location"], str)
        # SensorContactState is IntEnum with custom __str__
        assert isinstance(val_map["2A37_sensor_contact"], str)

    def test_non_struct_value_is_rejected(self) -> None:
        """Passing a non-struct to _add_struct_entities creates no entities."""
        _, _, data = self._run(42)
        assert len(data) == 0


# ---------------------------------------------------------------------------
# _resolve_device_class tests
# ---------------------------------------------------------------------------


class TestResolveDeviceClass:
    """Tests for _resolve_device_class mapping function."""

    def test_unambiguous_units_map_correctly(self) -> None:
        """Each entry in _UNIT_TO_DEVICE_CLASS resolves as expected."""
        for unit, expected_dc in _UNIT_TO_DEVICE_CLASS.items():
            result = _resolve_device_class(unit, "Some Sensor")
            assert result == expected_dc, (
                f"Unit {unit!r} → {result}, expected {expected_dc}"
            )

    def test_celsius_maps_to_temperature(self) -> None:
        result = _resolve_device_class("°C", "Temperature")
        assert result == SensorDeviceClass.TEMPERATURE

    def test_kelvin_maps_to_temperature(self) -> None:
        result = _resolve_device_class("K", "Temperature")
        assert result == SensorDeviceClass.TEMPERATURE

    def test_percent_battery_resolved(self) -> None:
        result = _resolve_device_class("%", "Battery Level")
        assert result == SensorDeviceClass.BATTERY

    def test_percent_humidity_resolved(self) -> None:
        result = _resolve_device_class("%", "Humidity")
        assert result == SensorDeviceClass.HUMIDITY

    def test_percent_generic_returns_none(self) -> None:
        """Generic '%' with no battery/humidity name → None."""
        result = _resolve_device_class("%", "CPU Usage")
        assert result is None

    def test_ambiguous_ppm_not_mapped_without_uuid(self) -> None:
        """ppm without a UUID is still ambiguous — unit-only lookup returns None."""
        result = _resolve_device_class("ppm", "CO2 Concentration")
        assert result is None

    def test_ambiguous_mm_not_mapped(self) -> None:
        """mm is deliberately excluded — could be distance or precipitation."""
        result = _resolve_device_class("mm", "Rainfall")
        assert result is None

    def test_ambiguous_m_not_mapped(self) -> None:
        """m is deliberately excluded — could be distance or time months."""
        result = _resolve_device_class("m", "Distance")
        assert result is None

    def test_ambiguous_m_per_s_not_mapped(self) -> None:
        """m/s is deliberately excluded — could be SPEED or WIND_SPEED."""
        result = _resolve_device_class("m/s", "Wind Speed")
        assert result is None

    def test_none_unit_returns_none(self) -> None:
        result = _resolve_device_class(None, "Something")
        assert result is None

    def test_empty_unit_returns_none(self) -> None:
        result = _resolve_device_class("", "Something")
        assert result is None

    def test_whitespace_unit_returns_none(self) -> None:
        result = _resolve_device_class("  ", "Something")
        assert result is None

    def test_unknown_unit_returns_none(self) -> None:
        result = _resolve_device_class("furlongs/fortnight", "Velocity")
        assert result is None


# ---------------------------------------------------------------------------
# _normalize_uuid_short tests
# ---------------------------------------------------------------------------


class TestNormalizeUuidShort:
    """Tests for the _normalize_uuid_short helper."""

    def test_full_uppercase_uuid(self) -> None:
        assert _normalize_uuid_short("00002A6E-0000-1000-8000-00805F9B34FB") == "2A6E"

    def test_full_lowercase_uuid(self) -> None:
        assert _normalize_uuid_short("00002a6e-0000-1000-8000-00805f9b34fb") == "2A6E"

    def test_gatt_prefixed_lowercase(self) -> None:
        assert _normalize_uuid_short("gatt_2a6e") == "2A6E"

    def test_gatt_prefixed_uppercase(self) -> None:
        assert _normalize_uuid_short("GATT_2A6E") == "2A6E"

    def test_already_short_uppercase(self) -> None:
        assert _normalize_uuid_short("2A6E") == "2A6E"

    def test_already_short_lowercase(self) -> None:
        assert _normalize_uuid_short("2a6e") == "2A6E"

    def test_battery_level_uuid(self) -> None:
        assert _normalize_uuid_short("00002A19-0000-1000-8000-00805F9B34FB") == "2A19"

    def test_invalid_non_hex_returns_none(self) -> None:
        assert _normalize_uuid_short("ZZZZ") is None

    def test_too_long_non_uuid_returns_none(self) -> None:
        # 8-char segment after lstrip still too long
        assert _normalize_uuid_short("ABCD1234") is None

    def test_empty_string_returns_none(self) -> None:
        assert _normalize_uuid_short("") is None


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
# Struct field unit inheritance fix tests
# ---------------------------------------------------------------------------


class TestStructFieldUnitInheritance:
    """Tests that non-numeric struct fields do not inherit parent unit."""

    @staticmethod
    def _run(
        struct_value: object,
        char_name: str = "Test Char",
        uuid: str = "2A37",
        unit: str | None = "bpm",
        is_diagnostic: bool = False,
    ) -> tuple[dict, dict, dict]:
        """Helper to call _add_struct_entities and return the three dicts."""
        coord = BluetoothSIGCoordinator.__new__(BluetoothSIGCoordinator)
        descs: dict = {}
        names: dict = {}
        data: dict = {}
        coord._add_struct_entities(
            "aabbccddee01",
            uuid,
            char_name,
            struct_value,
            unit,
            is_diagnostic,
            descs,
            names,
            data,
        )
        return descs, names, data

    def test_numeric_fields_keep_unit(self) -> None:
        """Plain int/float fields should keep the parent unit."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8,),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        descs, _, _ = self._run(hr, unit="bpm")
        desc_map = {k.key: v for k, v in descs.items()}

        # heart_rate is a plain int → should keep "bpm"
        assert desc_map["2A37_heart_rate"].native_unit_of_measurement == "bpm"

    def test_intflag_field_drops_unit(self) -> None:
        """IntFlag fields should NOT inherit the parent unit."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8,),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        descs, _, _ = self._run(hr, unit="bpm")
        desc_map = {k.key: v for k, v in descs.items()}

        # flags is IntFlag → should NOT have "bpm"
        assert desc_map["2A37_flags"].native_unit_of_measurement is None

    def test_intenum_field_drops_unit(self) -> None:
        """IntEnum fields should NOT inherit the parent unit."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8,),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        descs, _, _ = self._run(hr, unit="bpm")
        desc_map = {k.key: v for k, v in descs.items()}

        # sensor_contact is IntEnum (has .name) → should NOT have "bpm"
        assert desc_map["2A37_sensor_contact"].native_unit_of_measurement is None
        # sensor_location is also IntEnum
        assert desc_map["2A37_sensor_location"].native_unit_of_measurement is None

    def test_tuple_field_drops_unit(self) -> None:
        """Non-scalar fields (tuple→str) should NOT inherit the parent unit."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8, 0.9),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        descs, _, _ = self._run(hr, unit="bpm")
        desc_map = {k.key: v for k, v in descs.items()}

        # rr_intervals is tuple → str fallback → no unit
        assert desc_map["2A37_rr_intervals"].native_unit_of_measurement is None

    def test_energy_expended_keeps_unit(self) -> None:
        """energy_expended is a plain int → should keep parent unit."""
        hr = HeartRateData(
            heart_rate=72,
            sensor_contact=SensorContactState.DETECTED,
            energy_expended=150,
            rr_intervals=(0.8,),
            flags=HeartRateMeasurementFlags(0),
            sensor_location=BodySensorLocation.CHEST,
        )
        descs, _, _ = self._run(hr, unit="bpm")
        desc_map = {k.key: v for k, v in descs.items()}

        # energy_expended is int → keeps unit
        assert desc_map["2A37_energy_expended"].native_unit_of_measurement == "bpm"


# ---------------------------------------------------------------------------
# Deduplication across interpreted + service_data paths
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Tests that interpreted + service_data entities are deduplicated."""

    def test_service_data_skipped_when_in_skip_uuids(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """_add_service_data_entities skips UUIDs already in skip_uuids."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid_str = "00002a19-0000-1000-8000-00805f9b34fb"
        service_data = {BluetoothUUID(battery_uuid_str): bytes([0x4B])}

        coordinator._add_service_data_entities(
            "aabbccddeee01",
            service_data,
            descs,
            names,
            data,
            skip_uuids={battery_uuid_str},
        )

        # UUID was in skip_uuids → no entity created
        assert len(data) == 0

    def test_service_data_created_when_not_in_skip_uuids(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """_add_service_data_entities creates entity when UUID not in skip_uuids."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid_str = "00002a19-0000-1000-8000-00805f9b34fb"
        service_data = {BluetoothUUID(battery_uuid_str): bytes([0x4B])}

        coordinator._add_service_data_entities(
            "aabbccddeee01",
            service_data,
            descs,
            names,
            data,
            skip_uuids=set(),  # empty → nothing skipped
        )

        assert len(data) >= 1

    def test_seen_uuids_populated_by_sig_entity_path(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """After update_device, Battery UUID must appear in seen_uuids when tracked."""
        from bluetooth_sig.advertising import SIGCharacteristicData
        from bluetooth_sig.types.uuid import BluetoothUUID

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid = BluetoothUUID("00002a19-0000-1000-8000-00805f9b34fb")
        sig_data = SIGCharacteristicData(
            uuid=battery_uuid,
            characteristic_name="Battery Level",
            parsed_value=75,
        )

        seen: set[str] = set()
        coordinator._add_sig_characteristic_entity(
            "aabbccddeee01",
            sig_data,
            descs,
            names,
            data,
            seen_uuids=seen,
        )

        assert "00002a19-0000-1000-8000-00805f9b34fb" in seen

    def test_service_data_not_skipped_when_uuid_absent(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
    ) -> None:
        """Different UUIDs are not affected by skip_uuids."""
        from bluetooth_sig.types.uuid import BluetoothUUID

        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid_str = "00002a19-0000-1000-8000-00805f9b34fb"
        temp_uuid_str = "00002a6e-0000-1000-8000-00805f9b34fb"
        service_data = {BluetoothUUID(battery_uuid_str): bytes([0x4B])}

        coordinator._add_service_data_entities(
            "aabbccddeee01",
            service_data,
            descs,
            names,
            data,
            skip_uuids={
                temp_uuid_str
            },  # different UUID — battery should still be created
        )

        assert len(data) >= 1
