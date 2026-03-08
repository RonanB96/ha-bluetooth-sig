"""Tests for the sensor platform."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.bluetooth_sig_devices.sensor import (
    BluetoothSIGSensorEntity,
    async_setup_entry,
)

from .conftest import DEVICE_ADDRESS, make_device_entry, make_hub_entry


class TestBluetoothSIGSensorEntityAvailable:
    """Tests for the available property with once-only logging."""

    @pytest.fixture()
    def entity(self) -> BluetoothSIGSensorEntity:
        """Return a fresh entity instance with mocked parent available."""
        inst: BluetoothSIGSensorEntity = object.__new__(BluetoothSIGSensorEntity)
        inst._unavailable_logged = False  # noqa: SLF001
        inst.entity_description = MagicMock()
        inst.entity_description.key = "test_key"
        return inst

    def _call_available(
        self, entity: BluetoothSIGSensorEntity, parent_available: bool
    ) -> bool:
        with patch(
            "homeassistant.components.bluetooth.passive_update_processor"
            ".PassiveBluetoothProcessorEntity.available",
            new_callable=PropertyMock,
            return_value=parent_available,
        ):
            return BluetoothSIGSensorEntity.available.fget(entity)  # type: ignore[attr-defined]

    def test_available_true_no_log(
        self, entity: BluetoothSIGSensorEntity, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When available is True and no prior unavailability, nothing is logged."""
        result = self._call_available(entity, parent_available=True)

        assert result is True
        assert entity._unavailable_logged is False  # noqa: SLF001
        assert "unavailable" not in caplog.text
        assert "back online" not in caplog.text

    def test_available_false_logs_once(
        self, entity: BluetoothSIGSensorEntity, caplog: pytest.LogCaptureFixture
    ) -> None:
        """First unavailability is logged and flag is set."""
        result = self._call_available(entity, parent_available=False)

        assert result is False
        assert entity._unavailable_logged is True  # noqa: SLF001
        assert "unavailable" in caplog.text
        assert "test_key" in caplog.text

    def test_available_false_does_not_log_twice(
        self, entity: BluetoothSIGSensorEntity, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Second consecutive unavailability does not log again."""
        entity._unavailable_logged = True  # already logged  # noqa: SLF001

        with caplog.at_level("INFO"):
            self._call_available(entity, parent_available=False)

        assert "unavailable" not in caplog.text

    def test_recovery_logs_once_and_resets_flag(
        self, entity: BluetoothSIGSensorEntity, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Recovery from unavailable logs 'back online' and resets the flag."""
        entity._unavailable_logged = True  # noqa: SLF001  # simulate prior unavailability

        result = self._call_available(entity, parent_available=True)

        assert result is True
        assert entity._unavailable_logged is False  # noqa: SLF001
        assert "back online" in caplog.text
        assert "test_key" in caplog.text

    def test_recovery_does_not_log_when_flag_not_set(
        self, entity: BluetoothSIGSensorEntity, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Returning to available without prior unavailability does not log."""
        entity._unavailable_logged = False  # noqa: SLF001

        with caplog.at_level("INFO"):
            self._call_available(entity, parent_available=True)

        assert "back online" not in caplog.text

    def test_full_cycle(
        self, entity: BluetoothSIGSensorEntity, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Available → unavailable → available logs correct messages in order."""
        self._call_available(entity, parent_available=True)
        assert entity._unavailable_logged is False  # noqa: SLF001

        self._call_available(entity, parent_available=False)
        assert entity._unavailable_logged is True  # noqa: SLF001
        assert "unavailable" in caplog.text

        caplog.clear()
        self._call_available(entity, parent_available=True)
        assert entity._unavailable_logged is False  # noqa: SLF001
        assert "back online" in caplog.text


class TestBluetoothSIGSensorEntityNativeValue:
    """Tests for the native_value property."""

    def _make_entity_with_value(self, value: object) -> BluetoothSIGSensorEntity:
        entity: BluetoothSIGSensorEntity = object.__new__(BluetoothSIGSensorEntity)
        entity.processor = MagicMock()
        entity.entity_key = MagicMock()
        entity.processor.entity_data.get.return_value = value
        return entity

    def test_returns_float(self) -> None:
        """Float values are returned directly."""
        entity = self._make_entity_with_value(23.5)
        assert entity.native_value == 23.5

    def test_returns_int(self) -> None:
        """Int values are returned directly."""
        entity = self._make_entity_with_value(42)
        assert entity.native_value == 42

    def test_returns_str(self) -> None:
        """String values are returned directly."""
        entity = self._make_entity_with_value("Running")
        assert entity.native_value == "Running"

    def test_returns_bool(self) -> None:
        """Bool values are returned directly."""
        entity = self._make_entity_with_value(True)
        assert entity.native_value is True

    def test_returns_none_for_non_primitive(self) -> None:
        """Non-primitive values (e.g. None, objects) return None."""
        entity = self._make_entity_with_value(None)
        assert entity.native_value is None

    def test_returns_none_for_unknown_object(self) -> None:
        """Arbitrary objects are not returned — None is returned instead."""
        entity = self._make_entity_with_value(object())
        assert entity.native_value is None


class TestSensorPlatformGating:
    """Verify that entities are created only for per-device entries."""

    async def test_hub_entry_creates_no_entities(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The sensor platform returns early for hub entries — no entities."""
        hub = make_hub_entry()
        hub.add_to_hass(hass)

        mock_async_add = MagicMock()

        await async_setup_entry(hass, hub, mock_async_add)

        # No entities added
        mock_async_add.assert_not_called()

    async def test_device_entry_creates_processor(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A per-device entry calls create_device_processor on the coordinator."""
        # Set up a mock coordinator on runtime_data
        mock_coordinator = MagicMock()
        dev = make_device_entry()
        dev.add_to_hass(hass)
        dev.runtime_data = mock_coordinator

        mock_async_add = MagicMock()
        await async_setup_entry(hass, dev, mock_async_add)

        mock_coordinator.create_device_processor.assert_called_once_with(
            DEVICE_ADDRESS, dev, mock_async_add, BluetoothSIGSensorEntity
        )
