"""Tests for entity_builder.py — value coercion, struct decomposition, deduplication."""

from __future__ import annotations

import datetime
import enum

from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.core.translator import BluetoothSIGTranslator
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
from bluetooth_sig.gatt.characteristics.templates.data_structures import VectorData
from bluetooth_sig.types.uuid import BluetoothUUID

from custom_components.bluetooth_sig_devices.entity_builder import (
    add_service_data_entities,
    add_sig_characteristic_entity,
    add_struct_entities,
    to_ha_state,
)

# ---------------------------------------------------------------------------
# Local test enums — used to test to_ha_state without depending on library
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


# ---------------------------------------------------------------------------
# to_ha_state tests
# ---------------------------------------------------------------------------


class TestToHaState:
    """Tests for to_ha_state.

    Covers every branch in the isinstance chain and validates the ordering
    guarantees (bool before int, IntEnum before plain int, etc.).
    """

    # --- bool (must be checked before int) ---

    def test_bool_true(self) -> None:
        result = to_ha_state(True)
        assert result is True
        assert isinstance(result, bool)

    def test_bool_false(self) -> None:
        result = to_ha_state(False)
        assert result is False
        assert isinstance(result, bool)

    def test_bool_not_coerced_to_int(self) -> None:
        """bool subclasses int — ensure we return bool, not int(1)."""
        result = to_ha_state(True)
        assert type(result) is bool

    # --- IntEnum → str() ---

    def test_intenum_returns_str(self) -> None:
        """IntEnum values must be stringified, not cast to int."""
        result = to_ha_state(_TestSensorLocation.TOP_OF_SHOE)
        assert isinstance(result, str)

    def test_intenum_without_custom_str_returns_name(self) -> None:
        """IntEnum without __str__ override → returns .name (member identifier)."""
        result = to_ha_state(_TestSensorLocation.OTHER)
        assert result == "OTHER"

    def test_intenum_with_custom_str_returns_name(self) -> None:
        """IntEnum with __str__ override → .name is still returned (not str())."""
        result = to_ha_state(_TestSensorLocationWithStr.TOP_OF_SHOE)
        assert result == "TOP_OF_SHOE"

    def test_intenum_is_not_plain_int(self) -> None:
        """IntEnum must NOT return a plain int — it should return str."""
        result = to_ha_state(_TestSensorLocation.IN_SHOE)
        assert not isinstance(result, int)

    def test_real_library_intenum_barometric_pressure_trend(self) -> None:
        """Real library IntEnum (BarometricPressureTrend) returns .name."""
        from bluetooth_sig.gatt.characteristics.barometric_pressure_trend import (
            BarometricPressureTrend,
        )

        val = BarometricPressureTrend(0)
        result = to_ha_state(val)
        assert isinstance(result, str)
        assert result == val.name

    def test_real_library_intenum_door_window_status(self) -> None:
        """Real library IntEnum (DoorWindowOpenStatus) returns .name."""
        from bluetooth_sig.gatt.characteristics.door_window_status import (
            DoorWindowOpenStatus,
        )

        val = DoorWindowOpenStatus(0)
        result = to_ha_state(val)
        assert isinstance(result, str)
        assert result == val.name

    # --- IntFlag → int() ---

    def test_intflag_returns_int(self) -> None:
        """IntFlag values should become plain int."""
        result = to_ha_state(_TestKeyboardFlags.NUM_LOCK | _TestKeyboardFlags.CAPS_LOCK)
        assert isinstance(result, int)
        assert not isinstance(result, enum.IntFlag)
        assert result == 3

    def test_intflag_single_flag_returns_int(self) -> None:
        result = to_ha_state(_TestKeyboardFlags.SCROLL_LOCK)
        assert isinstance(result, int)
        assert result == 4

    def test_intflag_zero_returns_int(self) -> None:
        result = to_ha_state(_TestKeyboardFlags(0))
        assert isinstance(result, int)
        assert result == 0

    def test_real_library_intflag_keyboard_leds(self) -> None:
        """Real library IntFlag (KeyboardLEDs)."""
        from bluetooth_sig.gatt.characteristics.boot_keyboard_output_report import (
            KeyboardLEDs,
        )

        val = KeyboardLEDs(3)  # NUM_LOCK | CAPS_LOCK
        result = to_ha_state(val)
        assert isinstance(result, int)
        assert not isinstance(result, enum.IntFlag)
        assert result == 3

    # --- plain int ---

    def test_plain_int(self) -> None:
        result = to_ha_state(42)
        assert result == 42
        assert type(result) is int

    def test_plain_int_zero(self) -> None:
        result = to_ha_state(0)
        assert result == 0
        assert type(result) is int

    def test_plain_int_negative(self) -> None:
        result = to_ha_state(-7)
        assert result == -7

    # --- float ---

    def test_float(self) -> None:
        result = to_ha_state(36.5)
        assert result == 36.5
        assert type(result) is float

    def test_float_zero(self) -> None:
        result = to_ha_state(0.0)
        assert result == 0.0
        assert type(result) is float

    def test_float_negative(self) -> None:
        result = to_ha_state(-273.15)
        assert result == -273.15

    # --- str ---

    def test_str(self) -> None:
        result = to_ha_state("hello")
        assert result == "hello"
        assert type(result) is str

    def test_str_empty(self) -> None:
        result = to_ha_state("")
        assert result == ""

    # --- fallback: str() for everything else ---

    def test_timedelta_falls_through_to_str(self) -> None:
        val = datetime.timedelta(seconds=150)
        result = to_ha_state(val)
        assert isinstance(result, str)
        assert result == str(val)

    def test_datetime_falls_through_to_str(self) -> None:
        val = datetime.datetime(2025, 6, 15, 12, 30, 0)
        result = to_ha_state(val)
        assert isinstance(result, str)
        assert result == str(val)

    def test_date_falls_through_to_str(self) -> None:
        val = datetime.date(2025, 6, 15)
        result = to_ha_state(val)
        assert isinstance(result, str)
        assert result == str(val)

    def test_none_falls_through_to_str(self) -> None:
        """None shouldn't normally reach to_ha_state but it must not crash."""
        result = to_ha_state(None)
        assert result == "None"
        assert isinstance(result, str)

    def test_dict_falls_through_to_str(self) -> None:
        """Dict must not crash — gets stringified."""
        result = to_ha_state({"key": "val"})
        assert isinstance(result, str)

    def test_list_falls_through_to_str(self) -> None:
        result = to_ha_state([1, 2, 3])
        assert isinstance(result, str)

    # --- ordering / edge cases ---

    def test_bool_wins_over_int(self) -> None:
        """bool is a subclass of int. to_ha_state must return bool, not int."""
        assert type(to_ha_state(True)) is bool
        assert type(to_ha_state(False)) is bool

    def test_intenum_wins_over_int(self) -> None:
        """IntEnum is a subclass of int. Must go through str(), not int()."""
        val = _TestSensorLocation.TOP_OF_SHOE
        result = to_ha_state(val)
        assert isinstance(result, str)

    def test_intflag_does_not_hit_intenum_branch(self) -> None:
        """IntFlag is NOT a subclass of IntEnum — should hit the int branch."""
        val = _TestKeyboardFlags.NUM_LOCK
        result = to_ha_state(val)
        # IntFlag → int branch → plain int
        assert isinstance(result, int)
        assert not isinstance(result, str)


# ---------------------------------------------------------------------------
# Recursive struct decomposition tests (using real bluetooth-sig library types)
# ---------------------------------------------------------------------------


def _run_struct_test(
    struct_value: object,
    char_name: str = "Test Char",
    uuid: str = "2A37",
    unit: str | None = "bpm",
    is_diagnostic: bool = False,
) -> tuple[dict, dict, dict]:
    """Call add_struct_entities and return (descs, names, data) dicts."""
    descs: dict = {}
    names: dict = {}
    data: dict = {}
    add_struct_entities(
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


class TestAddStructEntities:
    """Tests for add_struct_entities recursive decomposition."""

    _run = staticmethod(_run_struct_test)

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
        """VectorData leaf values go through to_ha_state (float passthrough)."""
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
        # tuple → expanded per-element float entities
        assert val_map["2A37_rr_intervals_0"] == 0.8
        assert val_map["2A37_rr_intervals_1"] == 0.9
        # 6 fields + 1 extra from tuple expansion (2 elements instead of 1)
        assert len(data) == 7

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
        """Passing a non-struct to add_struct_entities creates no entities."""
        _, _, data = self._run(42)
        assert len(data) == 0


# ---------------------------------------------------------------------------
# Struct field unit inheritance fix tests
# ---------------------------------------------------------------------------


class TestStructFieldUnitInheritance:
    """Tests that non-numeric struct fields do not inherit parent unit."""

    _run = staticmethod(_run_struct_test)

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

    def test_tuple_field_expanded_elements_inherit_unit(self) -> None:
        """Tuple elements are numeric floats — they inherit the parent unit."""
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

        # rr_intervals expanded: each element is a float → inherits unit
        assert desc_map["2A37_rr_intervals_0"].native_unit_of_measurement == "bpm"
        assert desc_map["2A37_rr_intervals_1"].native_unit_of_measurement == "bpm"

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

    def test_service_data_skipped_when_in_skip_uuids(self) -> None:
        """add_service_data_entities skips UUIDs already in skip_uuids."""
        translator = BluetoothSIGTranslator()
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid_str = "00002a19-0000-1000-8000-00805f9b34fb"
        service_data = {BluetoothUUID(battery_uuid_str): bytes([0x4B])}

        add_service_data_entities(
            "aabbccddeee01",
            service_data,
            translator,
            descs,
            names,
            data,
            skip_uuids={battery_uuid_str},
        )

        # UUID was in skip_uuids → no entity created
        assert len(data) == 0

    def test_service_data_created_when_not_in_skip_uuids(self) -> None:
        """add_service_data_entities creates entity when UUID not in skip_uuids."""
        translator = BluetoothSIGTranslator()
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid_str = "00002a19-0000-1000-8000-00805f9b34fb"
        service_data = {BluetoothUUID(battery_uuid_str): bytes([0x4B])}

        add_service_data_entities(
            "aabbccddeee01",
            service_data,
            translator,
            descs,
            names,
            data,
            skip_uuids=set(),  # empty → nothing skipped
        )

        assert len(data) >= 1

    def test_seen_uuids_populated_by_sig_entity_path(self) -> None:
        """After add_sig_characteristic_entity, UUID must appear in seen_uuids."""
        battery_uuid = BluetoothUUID("00002a19-0000-1000-8000-00805f9b34fb")
        sig_data = SIGCharacteristicData(
            uuid=battery_uuid,
            characteristic_name="Battery Level",
            parsed_value=75,
        )

        descs: dict = {}
        names: dict = {}
        data: dict = {}
        seen: set[str] = set()

        add_sig_characteristic_entity(
            "aabbccddeee01",
            sig_data,
            descs,
            names,
            data,
            seen_uuids=seen,
        )

        assert "00002a19-0000-1000-8000-00805f9b34fb" in seen

    def test_service_data_not_skipped_when_uuid_absent(self) -> None:
        """Different UUIDs are not affected by skip_uuids."""
        translator = BluetoothSIGTranslator()
        descs: dict = {}
        names: dict = {}
        data: dict = {}

        battery_uuid_str = "00002a19-0000-1000-8000-00805f9b34fb"
        temp_uuid_str = "00002a6e-0000-1000-8000-00805f9b34fb"
        service_data = {BluetoothUUID(battery_uuid_str): bytes([0x4B])}

        add_service_data_entities(
            "aabbccddeee01",
            service_data,
            translator,
            descs,
            names,
            data,
            skip_uuids={
                temp_uuid_str
            },  # different UUID — battery should still be created
        )

        assert len(data) >= 1
