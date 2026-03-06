"""Tests for device identity — coordinator DeviceInfo contract.

These tests verify the critical contract between this integration and
the Home Assistant passive BLE framework that enables device merging
with other BLE integrations (e.g. xiaomi_ble, switchbot, govee_ble).

The contract:
1. Entity keys must use ``device_id=None`` so the framework assigns
   ``identifiers={("bluetooth", address)}`` and
   ``connections={("bluetooth", address)}``.
2. DeviceInfo returned in PassiveBluetoothDataUpdate must NOT include
   ``identifiers`` or ``connections`` — the framework adds these.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.bluetooth_sig_devices.coordinator import (
    BluetoothSIGCoordinator,
)

# ============================================================================
# Unit tests — coordinator DeviceInfo contract
# ============================================================================


class TestDeviceInfoDoesNotSetIdentifiersOrConnections:
    """Coordinator must NOT set identifiers/connections in DeviceInfo.

    The passive BLE framework adds them automatically when device_id is
    None, and ONLY when the framework adds them do they use the correct
    ("bluetooth", address) tuple that enables cross-integration merging.

    If the coordinator sets its own identifiers (e.g.
    (DOMAIN, address)), the framework would merge them but the device
    registry would use the domain-scoped identifier — which does NOT
    match other integrations like xiaomi_ble.
    """

    def test_advertisement_update_no_identifiers(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """update_device() must not include identifiers in DeviceInfo."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        device_info = result.devices[None]
        assert "identifiers" not in device_info, (
            "DeviceInfo must not set identifiers — "
            "the passive BLE framework handles this when device_id is None"
        )

    def test_advertisement_update_no_connections(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """update_device() must not include connections in DeviceInfo."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        device_info = result.devices[None]
        assert "connections" not in device_info, (
            "DeviceInfo must not set connections — "
            "the passive BLE framework handles this when device_id is None"
        )

    def test_temperature_update_no_identifiers(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_temperature: BluetoothServiceInfoBleak,
    ) -> None:
        """DeviceInfo contract holds for temperature characteristic too."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_temperature)

        device_info = result.devices[None]
        assert "identifiers" not in device_info
        assert "connections" not in device_info

    def test_humidity_update_no_identifiers(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_humidity: BluetoothServiceInfoBleak,
    ) -> None:
        """DeviceInfo contract holds for humidity characteristic too."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_humidity)

        device_info = result.devices[None]
        assert "identifiers" not in device_info
        assert "connections" not in device_info

    def test_device_name_still_set(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """DeviceInfo still includes the device name despite no identifiers."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        device_info = result.devices[None]
        assert device_info.get("name") == "Test Battery Device"


class TestEntityKeysUseNoneDeviceId:
    """All entity keys must use device_id=None to enable framework-managed identity.

    When device_id is None, PassiveBluetoothProcessorEntity sets:
    - identifiers = {("bluetooth", address)}
    - connections = {("bluetooth", address)}
    - unique_id = f"{address}-{key}"

    When device_id is truthy, the framework sets:
    - identifiers = {("bluetooth", f"{address}-{device_id}")}
    - NO connections
    - unique_id = f"{address}-{key}-{device_id}"

    Only the None path enables cross-integration device merging.
    """

    def test_battery_entity_keys_have_none_device_id(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Battery Level entity keys must use device_id=None."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        for entity_key in result.entity_data:
            assert entity_key.device_id is None, (
                f"Entity key {entity_key} has device_id={entity_key.device_id!r}, "
                f"expected None for cross-integration device merging"
            )

    def test_temperature_entity_keys_have_none_device_id(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_temperature: BluetoothServiceInfoBleak,
    ) -> None:
        """Temperature entity keys must use device_id=None."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_temperature)

        for entity_key in result.entity_data:
            assert entity_key.device_id is None, (
                f"Entity key {entity_key} has device_id={entity_key.device_id!r}, "
                f"expected None"
            )

    def test_heart_rate_struct_entity_keys_have_none_device_id(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_heart_rate: BluetoothServiceInfoBleak,
    ) -> None:
        """Struct (Heart Rate Measurement) entity keys must use device_id=None."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_heart_rate)

        for entity_key in result.entity_data:
            assert entity_key.device_id is None, (
                f"Struct entity key {entity_key} has "
                f"device_id={entity_key.device_id!r}, expected None"
            )

    def test_csc_measurement_struct_entity_keys_have_none_device_id(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_csc_measurement: BluetoothServiceInfoBleak,
    ) -> None:
        """CSC Measurement struct entity keys must use device_id=None."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_csc_measurement)

        for entity_key in result.entity_data:
            assert entity_key.device_id is None, (
                f"CSC entity key {entity_key} has "
                f"device_id={entity_key.device_id!r}, expected None"
            )

    def test_all_entity_descriptions_match_data_keys(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_bluetooth_service_info_battery: BluetoothServiceInfoBleak,
    ) -> None:
        """Every entity_data key must also appear in entity_descriptions."""
        coordinator = BluetoothSIGCoordinator(mock_hass, mock_config_entry)
        result = coordinator.update_device(mock_bluetooth_service_info_battery)

        for key in result.entity_data:
            assert key in result.entity_descriptions, (
                f"Entity key {key} in entity_data but missing from entity_descriptions"
            )
            assert key in result.entity_names, (
                f"Entity key {key} in entity_data but missing from entity_names"
            )
