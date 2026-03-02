"""Pytest fixtures for bluetooth_sig_devices tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.bluetooth_sig_devices.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Generator[None]:
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_bluetooth_disabled() -> Generator[None]:
    """Fully disable the Bluetooth component for config-entry / config-flow tests.

    Patches ``async_setup`` and ``async_setup_entry`` so that HA never
    attempts real hardware or D-Bus access when loading the ``bluetooth``
    dependency.  Also patches ``async_scanner_count`` at the component level
    AND at the config-flow import site so availability checks pass.

    Do NOT use this in tests that also request the ``enable_bluetooth``
    fixture — ``enable_bluetooth`` needs the real (framework-mocked) Bluetooth
    setup to create a live ``BluetoothManager``.
    """
    with (
        patch(
            "homeassistant.components.bluetooth.async_setup",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "homeassistant.components.bluetooth.async_setup_entry",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "homeassistant.components.bluetooth.async_scanner_count",
            return_value=1,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.config_flow.async_scanner_count",
            return_value=1,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.__init__.bluetooth.async_scanner_count",
            return_value=1,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_bluetooth_setup() -> Generator[None]:
    """Prevent unit tests from hitting the real Bluetooth manager.

    Only patches ``async_ble_device_from_address`` so that coordinator
    methods that look up a ``BLEDevice`` receive ``None`` instead of
    triggering a ``RuntimeError`` from ``habluetooth.get_manager()``.

    This is a lightweight autouse patch that does NOT mock
    ``async_setup_entry`` or ``async_scanner_count``, so it is compatible
    with the ``enable_bluetooth`` fixture used in integration tests.
    """
    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address",
        return_value=None,
    ):
        yield


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Return a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.domain = DOMAIN
    entry.data = {}
    entry.options = {}
    return entry


@pytest.fixture
def mock_bluetooth_service_info_battery() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with Battery Level characteristic."""
    # Battery Level UUID: 0x2A19
    return BluetoothServiceInfoBleak(
        name="Test Battery Device",
        address="AA:BB:CC:DD:EE:01",
        rssi=-65,
        manufacturer_data={},
        service_data={
            "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x4B]),  # 75%
        },
        service_uuids=["00002a19-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_temperature() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with Temperature characteristic."""
    # Temperature UUID: 0x2A6E
    return BluetoothServiceInfoBleak(
        name="Test Temperature Sensor",
        address="AA:BB:CC:DD:EE:02",
        rssi=-55,
        manufacturer_data={},
        service_data={
            "00002a6e-0000-1000-8000-00805f9b34fb": bytes([0x64, 0x09]),  # 24.04°C
        },
        service_uuids=["00002a6e-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_humidity() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with Humidity characteristic."""
    # Humidity UUID: 0x2A6F
    return BluetoothServiceInfoBleak(
        name="Test Humidity Sensor",
        address="AA:BB:CC:DD:EE:03",
        rssi=-60,
        manufacturer_data={},
        service_data={
            "00002a6f-0000-1000-8000-00805f9b34fb": bytes([0x3A, 0x13]),  # 49.38%
        },
        service_uuids=["00002a6f-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_heart_rate() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with Heart Rate characteristic."""
    # Heart Rate Measurement UUID: 0x2A37
    return BluetoothServiceInfoBleak(
        name="Test Heart Rate Monitor",
        address="AA:BB:CC:DD:EE:04",
        rssi=-70,
        manufacturer_data={},
        service_data={
            "00002a37-0000-1000-8000-00805f9b34fb": bytes([0x00, 0x48]),  # 72 BPM
        },
        service_uuids=["00002a37-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_rssi_only() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with only RSSI (no parseable data)."""
    return BluetoothServiceInfoBleak(
        name="Generic BLE Device",
        address="AA:BB:CC:DD:EE:05",
        rssi=-80,
        manufacturer_data={0x004C: bytes([0x01, 0x02, 0x03])},  # Apple (proprietary)
        service_data={},
        service_uuids=[],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_csc_measurement() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with CSC Measurement characteristic (complex struct)."""
    # CSC Measurement UUID: 0x2A5B - Cycling Speed and Cadence
    # Data format: [flags, cumulative_wheel_rev[4], last_wheel_event_time[2], cumulative_crank_rev[2], last_crank_event_time[2]]
    # Flags: 0x03 = wheel revolution + crank revolution present
    return BluetoothServiceInfoBleak(
        name="Test CSC Sensor",
        address="AA:BB:CC:DD:EE:07",
        rssi=-65,
        manufacturer_data={},
        service_data={
            "00002a5b-0000-1000-8000-00805f9b34fb": bytes(
                [
                    0x03,  # flags: wheel + crank data present
                    0x10,
                    0x00,
                    0x00,
                    0x00,  # cumulative wheel revolutions: 16
                    0x20,
                    0x00,  # last wheel event time: 32
                    0x30,
                    0x00,  # cumulative crank revolutions: 48
                    0x40,
                    0x00,  # last crank event time: 64
                ]
            ),
        },
        service_uuids=["00002a5b-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_csc_feature() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with CSC Feature characteristic (bitfield)."""
    # CSC Feature UUID: 0x2A5C - bitfield indicating supported features
    # Bit 0: Wheel Revolution Data Supported
    # Bit 1: Crank Revolution Data Supported
    # Bit 2: Multiple Sensor Locations Supported
    return BluetoothServiceInfoBleak(
        name="Test CSC Feature",
        address="AA:BB:CC:DD:EE:08",
        rssi=-70,
        manufacturer_data={},
        service_data={
            "00002a5c-0000-1000-8000-00805f9b34fb": bytes(
                [0x07, 0x00]
            ),  # All features supported (bits 0,1,2 set) - 2 bytes
        },
        service_uuids=["00002a5c-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_service_info_body_sensor_location() -> BluetoothServiceInfoBleak:
    """Create mock BluetoothServiceInfoBleak with Body Sensor Location characteristic (enum/int)."""
    # Body Sensor Location UUID: 0x2A38 - enum value
    return BluetoothServiceInfoBleak(
        name="Test Body Sensor",
        address="AA:BB:CC:DD:EE:09",
        rssi=-75,
        manufacturer_data={},
        service_data={
            "00002a38-0000-1000-8000-00805f9b34fb": bytes([0x01]),  # Chest location
        },
        service_uuids=["00002a38-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )
