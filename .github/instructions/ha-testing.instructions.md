---
description: "Test tiers, helpers, fixtures, and BLE injection patterns"
applyTo: "tests/**/*.py"
globs: tests/**/*.py
alwaysApply: false
---

# HA Testing — Tiers, Helpers & Fixtures

## Test Tiers

| Tier | Files | Approach |
|------|-------|----------|
| Unit | `test_coordinator.py`, `test_sensor.py`, `test_device_adapter.py`, etc. | Direct class instantiation with `MagicMock` |
| Config flow | `test_config_flow.py`, `test_discovery_flow.py` | `mock_bluetooth_disabled` or `enable_bluetooth` |
| Integration / advertising | `test_integration_advertising.py` | `enable_bluetooth` + `inject_bluetooth_service_info` + fixture replay |
| Integration / GATT | `test_integration_connected.py`, `test_integration_confirmed_device.py` | `mock_gatt_connection`; confirmed-device poll path via real `GattDevicePollCoordinator` (no direct `GATTManager` calls) |

## Key Helpers

See [`tests/bluetooth_helpers.py`](../../tests/bluetooth_helpers.py) for the full set of BLE injection and mock helpers. Key functions cover: loading fixtures, injecting advertisement events into HA, building mock BleakClient objects, and patching the GATT connection stack.

## Fixtures

JSON fixtures in `tests/fixtures/` are real ESPHome BLE advertisement captures. Each file is a list of raw advertisement frames for a single device address.

## Shared Fixtures (`tests/conftest.py`)

Standard HA test infrastructure is set up in `conftest.py`. Prefer using its fixtures over constructing coordinator/entry objects manually in individual tests.
