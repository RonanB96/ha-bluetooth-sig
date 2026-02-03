---
applyTo: '**'
---

# Bluetooth SIG Devices — AI Agent Instructions

Home Assistant custom integration for automatic Bluetooth sensor creation using the `bluetooth-sig-python` library.

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Component Responsibilities](#component-responsibilities)
- [Implementation Patterns](#implementation-patterns)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Common Tasks](#common-tasks)
- [Constraints and Requirements](#constraints-and-requirements)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

**Design Principle**: Single config entry with continuous auto-discovery of ALL Bluetooth devices. This is NOT a per-device config entry integration.

### Similar HA Integrations (Reference Implementations)

This integration follows patterns established by other HA Bluetooth integrations with similar use cases:

| Integration | Pattern | Source Reference |
|-------------|---------|------------------|
| **iBeacon** | Single config + global callback + dispatcher signals | `homeassistant/components/ibeacon/coordinator.py` |
| **private_ble_device** | Single config + `BluetoothCallbackMatcher(connectable=False)` | `homeassistant/components/private_ble_device/coordinator.py` |
| **ble_monitor** (HACS) | Single config + passive scanning for any advertisement | Similar community approach |

**Why this pattern (not per-device config entries):**
- Cannot predefine bluetooth matchers in `manifest.json` — supported devices are determined at runtime by library parsing success
- Would require user to manually confirm each device — impractical for environments with many BLE devices
- iBeacon integration faces same challenge: any device could be an iBeacon, discovered at runtime

### Data Flow

```
1. Integration Setup
   __init__.py → creates BluetoothSIGCoordinator
   sensor.py → registers entity_adder callback with coordinator

2. Continuous Discovery (coordinator.async_start)
   bluetooth.async_register_callback(BluetoothCallbackMatcher(connectable=False))
       ↓ every BLE advertisement (connectable AND non-connectable)
   _async_device_discovered(service_info)
       ↓ first time seeing this address?
   _has_supported_data(service_info)  ← filters unsupported devices
       ↓ has parseable GATT service data or interpretable manufacturer data?
   _ensure_device_processor(address)
       ↓
   PassiveBluetoothProcessorCoordinator (one per device address)
       ↓
   update_device() → _build_passive_bluetooth_update()
       ↓
   PassiveBluetoothDataUpdate → BluetoothSIGSensorEntity created
```

### Why This Architecture

- **No manifest matchers**: Cannot predefine supported devices; support determined at runtime by library parsing success
- **Single config entry**: User enables once, all compatible devices auto-discovered
- **Dynamic processor creation**: New devices appearing after setup are automatically tracked
- **Library-driven metadata**: Entity names, units, and parsing come from `bluetooth-sig-python`, not hardcoded maps

---

## Component Responsibilities

| File | Responsibility |
|------|----------------|
| `__init__.py` | Entry point; creates coordinator; forwards to platforms; handles unload |
| `coordinator.py` | Global discovery callback; per-device processor management; builds `PassiveBluetoothDataUpdate` |
| `device_adapter.py` | Converts HA `BluetoothServiceInfoBleak` → library `AdvertisementData` |
| `sensor.py` | Registers entity adder; defines `BluetoothSIGSensorEntity` class |
| `config_flow.py` | Single-instance config flow; checks Bluetooth availability |
| `const.py` | Only `DOMAIN = "bluetooth_sig_devices"` |

---

## Implementation Patterns

### Global Discovery Registration

The coordinator registers for ALL Bluetooth advertisements using `connectable=False`:

```python
# In coordinator.async_start()
# CRITICAL: connectable=False matches ALL devices (both connectable and non-connectable)
# Using None or {} defaults to connectable=True which misses passive BLE devices!
# Reference: homeassistant/components/bluetooth/manager.py lines 208-227
self._cancel_discovery = bluetooth.async_register_callback(
    self.hass,
    self._async_device_discovered,
    BluetoothCallbackMatcher(connectable=False),
    BluetoothScanningMode.PASSIVE,
)
```

**Why `connectable=False`?**
- When matcher is `None`, HA defaults to `connectable=True` (see `manager.py`)
- `connectable=False` receives ALL advertisements (connectable AND non-connectable)
- This is the same pattern used by `ibeacon` and `private_ble_device` integrations

### Device Filtering with `_has_supported_data()`

Not all Bluetooth devices have data we can parse. The `_has_supported_data()` method filters:

```python
def _has_supported_data(self, service_info) -> bool:
    # Check 1: Service data with known GATT characteristic UUID
    if service_info.service_data:
        for uuid_str in service_info.service_data:
            if translator.get_characteristic_info_by_uuid(uuid_str):
                return True  # Known standard characteristic

    # Check 2: Manufacturer data the library can interpret
    if service_info.manufacturer_data:
        advertisement = convert_advertisement(service_info)
        if advertisement.interpreted_data is not None:
            return True  # Library recognized this format

    return False  # Unsupported device, skip
```

### Per-Device Processor Creation

When `_ensure_device_processor()` sees a new address:

1. Creates `PassiveBluetoothProcessorCoordinator` bound to that address
2. Creates `PassiveBluetoothDataProcessor` with passthrough lambda
3. Registers entity listener via `processor.async_add_entities_listener()`
4. Starts the processor coordinator
5. Stores in `self._processor_coordinators[address]`

### Entity Metadata from Library

Never hardcode entity properties. Use library metadata:

- `char_instance.name` → entity name
- `char_instance.unit` → `native_unit_of_measurement`
- `char_instance.value_type` → determines parsing path
- `data.parsed_value` → entity state

### ValueType Handling

In `_add_sig_characteristic_entity()`, route by `ValueType`:

| ValueType | Handler | Creates |
|-----------|---------|---------|
| `INT`, `FLOAT` | `_add_simple_entity()` | Single numeric sensor |
| `STRING` | `_add_simple_entity()` | Single text sensor |
| `VARIOUS`, `BITFIELD` | `_add_struct_entities()` | Multiple sensors from struct fields |

### Struct Field Extraction

For complex types, iterate `__struct_fields__` (msgspec Struct attribute):

```python
for field_name in struct_value.__struct_fields__:
    field_value = getattr(struct_value, field_name)
    if isinstance(field_value, (int, float, str, bool)):
        # Create entity for this field
```

---

## Development Workflow

### Environment Setup

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install with all dependencies
pip install -e ".[test,dev]"

# 3. Install HA test dependency (often missing)
pip install aiousbwatcher
```

### Code Quality

```bash
# Lint and format
ruff check . --fix
ruff format .

# Type checking
mypy custom_components/bluetooth_sig_devices
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific file
pytest tests/test_coordinator.py -v

# With coverage
pytest tests/ --cov=custom_components/bluetooth_sig_devices --cov-report=term-missing
```

---

## Testing

### Test Framework

Uses `pytest-homeassistant-custom-component` — provides HA test fixtures without full installation.

### Key Fixtures in `conftest.py`

| Fixture | Purpose |
|---------|---------|
| `mock_bluetooth_setup` | Mocks `bluetooth.async_setup`, `async_scanner_count` |
| `mock_bluetooth_service_info_battery` | `BluetoothServiceInfoBleak` with Battery Level UUID (0x2A19) |
| `mock_bluetooth_service_info_temperature` | `BluetoothServiceInfoBleak` with Temperature UUID (0x2A6E) |

### Test Patterns

1. **Unit tests**: Test `coordinator.update_device()` with mock `BluetoothServiceInfoBleak`
2. **Integration tests**: Test full setup via `hass.config_entries.async_setup()`
3. **Adapter tests**: Test `HomeAssistantBluetoothAdapter.convert_advertisement()`

### Live Testing

See `tests/TESTING.md` for methods:
- Copy to test HA instance
- Symlink for development
- DevContainer setup

---

## Common Tasks

### Adding Support for New Characteristic Types

No code changes needed in this integration. Add parser to `bluetooth-sig-python` library; this integration picks it up automatically via `CharacteristicRegistry`.

### Adding Per-Device Configuration

Future pattern for bind keys, etc.:

1. Store in `entry.options` keyed by device address
2. Access in `_ensure_device_processor()` or `update_device()`
3. Add options flow for UI configuration

### Debugging Device Discovery

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.bluetooth_sig_devices: debug
```

Check logs for:
- `"Creating processor coordinator for new device %s"` — new device detected
- `"Now tracking Bluetooth device %s"` — processor started
- `"Processing device %s"` — advertisement received

---

## Constraints and Requirements

| Constraint | Value | Source |
|------------|-------|--------|
| Python version | ≥3.12 | `pyproject.toml` |
| Home Assistant version | ≥2026.1.0 | `hacs.json` |
| Config entries | Single instance only | `manifest.json` `single_config_entry: true` |
| Scanning mode | Passive | `BluetoothScanningMode.PASSIVE` |
| GATT polling | Not implemented | TODO in `device_adapter.py` |

### Dependencies

- `bluetooth-sig-python` — Core parsing library (git dependency)
- `homeassistant.components.bluetooth` — HA Bluetooth integration
- `pytest-homeassistant-custom-component` — Test framework (dev only)

---

## Troubleshooting

### No Devices Discovered

1. Verify Bluetooth scanner available: Check `bluetooth.async_scanner_count(hass, connectable=False) > 0`
2. Check sensor platform registered: Look for log `"Entity adder registered for sensor platform"`
3. Verify discovery started: Look for log `"Bluetooth SIG coordinator started"`

### Entities Not Created

1. Check library parsing: Add debug logging in `_build_passive_bluetooth_update()`
2. Verify `interpreted_data` or `service_data` present in advertisement
3. Check `CharacteristicRegistry.get_characteristic_class_by_uuid()` returns a class

### Integration Won't Load

1. Check `ConfigEntryNotReady` for Bluetooth unavailable
2. Verify `single_instance_allowed` not blocking reinstall
3. Check HA logs for import errors in dependencies

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `ha_plan.md` | Implementation rationale and design decisions |
| `README.md` | User-facing documentation |
| `tests/conftest.py` | Mock BLE fixtures with example service data |
| `tests/TESTING.md` | Live testing methods |
| `pyproject.toml` | Dependencies, linting config, test settings |
