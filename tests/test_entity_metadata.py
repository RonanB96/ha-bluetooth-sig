"""Tests for entity_metadata.py — unit mapping and UUID normalisation."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass

from custom_components.bluetooth_sig_devices.entity_metadata import (
    UNIT_TO_DEVICE_CLASS,
    normalize_uuid_short,
    resolve_device_class,
)

# ---------------------------------------------------------------------------
# resolve_device_class tests
# ---------------------------------------------------------------------------


class TestResolveDeviceClass:
    """Tests for resolve_device_class mapping function."""

    def test_unambiguous_units_map_correctly(self) -> None:
        """Each entry in UNIT_TO_DEVICE_CLASS resolves as expected."""
        for unit, expected_dc in UNIT_TO_DEVICE_CLASS.items():
            result = resolve_device_class(unit, "Some Sensor")
            assert result == expected_dc, (
                f"Unit {unit!r} → {result}, expected {expected_dc}"
            )

    def test_celsius_maps_to_temperature(self) -> None:
        result = resolve_device_class("°C", "Temperature")
        assert result == SensorDeviceClass.TEMPERATURE

    def test_kelvin_maps_to_temperature(self) -> None:
        result = resolve_device_class("K", "Temperature")
        assert result == SensorDeviceClass.TEMPERATURE

    def test_percent_battery_resolved(self) -> None:
        result = resolve_device_class("%", "Battery Level")
        assert result == SensorDeviceClass.BATTERY

    def test_percent_humidity_resolved(self) -> None:
        result = resolve_device_class("%", "Humidity")
        assert result == SensorDeviceClass.HUMIDITY

    def test_percent_generic_returns_none(self) -> None:
        """Generic '%' with no battery/humidity name → None."""
        result = resolve_device_class("%", "CPU Usage")
        assert result is None

    def test_ambiguous_ppm_not_mapped_without_uuid(self) -> None:
        """ppm without a UUID is still ambiguous — unit-only lookup returns None."""
        result = resolve_device_class("ppm", "CO2 Concentration")
        assert result is None

    def test_ambiguous_mm_not_mapped(self) -> None:
        """mm is deliberately excluded — could be distance or precipitation."""
        result = resolve_device_class("mm", "Rainfall")
        assert result is None

    def test_ambiguous_m_not_mapped(self) -> None:
        """m is deliberately excluded — could be distance or time months."""
        result = resolve_device_class("m", "Distance")
        assert result is None

    def test_ambiguous_m_per_s_not_mapped(self) -> None:
        """m/s is deliberately excluded — could be SPEED or WIND_SPEED."""
        result = resolve_device_class("m/s", "Wind Speed")
        assert result is None

    def test_none_unit_returns_none(self) -> None:
        result = resolve_device_class(None, "Something")
        assert result is None

    def test_empty_unit_returns_none(self) -> None:
        result = resolve_device_class("", "Something")
        assert result is None

    def test_whitespace_unit_returns_none(self) -> None:
        result = resolve_device_class("  ", "Something")
        assert result is None

    def test_unknown_unit_returns_none(self) -> None:
        result = resolve_device_class("furlongs/fortnight", "Velocity")
        assert result is None


# ---------------------------------------------------------------------------
# normalize_uuid_short tests
# ---------------------------------------------------------------------------


class TestNormalizeUuidShort:
    """Tests for the normalize_uuid_short helper."""

    def test_full_uppercase_uuid(self) -> None:
        assert normalize_uuid_short("00002A6E-0000-1000-8000-00805F9B34FB") == "2A6E"

    def test_full_lowercase_uuid(self) -> None:
        assert normalize_uuid_short("00002a6e-0000-1000-8000-00805f9b34fb") == "2A6E"

    def test_gatt_prefixed_lowercase(self) -> None:
        assert normalize_uuid_short("gatt_2a6e") == "2A6E"

    def test_gatt_prefixed_uppercase(self) -> None:
        assert normalize_uuid_short("GATT_2A6E") == "2A6E"

    def test_already_short_uppercase(self) -> None:
        assert normalize_uuid_short("2A6E") == "2A6E"

    def test_already_short_lowercase(self) -> None:
        assert normalize_uuid_short("2a6e") == "2A6E"

    def test_battery_level_uuid(self) -> None:
        assert normalize_uuid_short("00002A19-0000-1000-8000-00805F9B34FB") == "2A19"

    def test_invalid_non_hex_returns_none(self) -> None:
        assert normalize_uuid_short("ZZZZ") is None

    def test_too_long_non_uuid_returns_none(self) -> None:
        # 8-char segment after lstrip still too long
        assert normalize_uuid_short("ABCD1234") is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_uuid_short("") is None
