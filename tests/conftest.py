"""pytest configuration for Bluetooth SIG Devices integration tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Generator[None]:
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_bluetooth_service_info() -> BluetoothServiceInfoBleak:
    """Mock BluetoothServiceInfoBleak for testing."""

    return BluetoothServiceInfoBleak(
        name="Test Device",
        address="AA:BB:CC:DD:EE:FF",
        rssi=-60,
        manufacturer_data={0x004C: b"\x02\x15test"},
        service_data={"0000180f-0000-1000-8000-00805f9b34fb": b"\x64"},
        service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"],
        source="local",
        advertisement=MagicMock(),
        device=MagicMock(),
        time=0,
        connectable=True,
        tx_power=None,
    )


@pytest.fixture
def mock_bluetooth_adapters() -> Generator[None]:
    """Mock bluetooth adapters."""
    with patch(
        "homeassistant.components.bluetooth.async_scanner_count", return_value=1
    ):
        yield


@pytest.fixture(autouse=True)
def mock_bluetooth_setup() -> Generator[None]:
    """Mock the bluetooth component setup to avoid hardware access."""
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
    ):
        yield
