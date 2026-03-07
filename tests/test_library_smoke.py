"""Smoke tests for the bluetooth-sig library dependency.

These tests verify that the ``bluetooth-sig`` library APIs this integration
relies on behave as expected.  They test the *library*, not our integration
code, and exist purely to catch upstream breakage early.
"""

from __future__ import annotations

from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry


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
