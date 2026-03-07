---
applyTo: '**'
---

# Bluetooth SIG Devices — AI Agent Instructions

Home Assistant custom integration for automatic Bluetooth sensor creation using the `bluetooth-sig-python` library. Parses standard Bluetooth SIG GATT characteristics and manufacturer data — **no hardcoded maps, fully library-driven**.

## Table of Contents

- [Architecture](#architecture)
- [Component Responsibilities](#component-responsibilities)
- [Key Patterns](#key-patterns)
- [Code Style](#code-style)
- [Build and Test](#build-and-test)
- [Constraints](#constraints)
- [Common Tasks](#common-tasks)

---

## Architecture

### Two-Tier Config Entry Pattern

**Not** a single-config-entry integration. Uses hub entry (no `address`, `unique_id=DOMAIN`) for the global BLE scanner + coordinator, plus per-device entries (`{"address": "AA:BB:..."}`, `unique_id=address`) created via `discovery_flow`. `_is_hub_entry(entry)` checks `"address" not in entry.data`.

**Discovery:** Coordinator detects supported device → `discovery_flow.async_create_flow(source="integration_discovery")` → user confirms → device config entry → sensor platform calls `create_device_processor()`.

**Reference integrations:** iBeacon, private_ble_device — same hub + `BluetoothCallbackMatcher(connectable=False)` pattern. Needed because supported devices are determined at runtime by library parsing success.

### Data Flow

`__init__.py` creates `BluetoothSIGCoordinator` (hub entry) → `async_start()` registers global BT callback → `_async_device_discovered()` → `_ensure_device_processor()` (fires discovery flow / schedules GATT probe / rejects) → after user confirms: `create_device_processor()` → `ActiveBluetoothProcessorCoordinator` → `update_device()` → `_build_passive_bluetooth_update()` → `PassiveBluetoothDataUpdate` → `BluetoothSIGSensorEntity`.

### Two Independent Data Paths

1. **Advertisement path** (passive) — broadcast service data UUIDs and manufacturer data, handled by the coordinator's `update_method` callback
2. **GATT path** (active) — characteristic reading via BLE connection, handled by the coordinator's `poll_method` async callback

Both paths are completely separate and independent. Each produces `PassiveBluetoothDataUpdate` objects that the `ActiveBluetoothProcessorCoordinator` merges via `PassiveBluetoothDataUpdate.update()`. The GATT poll is triggered by advertisement events when `needs_poll_method` returns True (probe results exist and `poll_age >= poll_interval`).

**Reference integrations:** OralB, Xiaomi BLE — same `ActiveBluetoothProcessorCoordinator` + `needs_poll_method` / `poll_method` pattern.

---

## Component Responsibilities

| File | Responsibility |
|------|----------------|
| `__init__.py` | Dispatches hub vs device setup; creates coordinator; forwards to `PLATFORMS = [Platform.SENSOR]`; handles unload and device removal |
| `coordinator.py` | Orchestrates BLE discovery, processor lifecycle, update pipeline; delegates to sub-managers |
| `advertisement_manager.py` | `AdvertisementManager` — advertisement conversion (`BluetoothServiceInfoBleak` → `AdvertisementData`), per-device tracking state, RSSI, callbacks, manufacturer/model extraction |
| `support_detector.py` | `SupportDetector` — determines if a BLE device has parseable SIG data; characteristic tracking and summary building |
| `entity_builder.py` | Stateless entity construction from parsed bluetooth-sig library data; role gating; value coercion (`to_ha_state`) |
| `entity_metadata.py` | Pure-function entity metadata resolution: unit→device class mapping, UUID normalisation, field unit lookup |
| `gatt_manager.py` | `GATTManager` — GATT probing and on-demand characteristic reading; concurrency semaphore; no longer owns polling lifecycle |
| `discovery_tracker.py` | `DiscoveryTracker` — seen/rejected/stale device tracking, LRU eviction, cleanup timer |
| `device_adapter.py` | `HomeAssistantBluetoothAdapter` — `ClientManagerProtocol` impl; GATT connection lifecycle and I/O; delegates advertisement conversion to `AdvertisementManager` |
| `device_validator.py` | BLE address classification (`classify_ble_address`, `is_static_address`); `GATTProbeResult` dataclass |
| `sensor.py` | Entity adder via `create_device_processor()`; `BluetoothSIGSensorEntity` with availability logging |
| `config_flow.py` | Hub step, YAML import, integration_discovery confirm; `OptionsFlow` for poll_interval |
| `diagnostics.py` | Device statistics via coordinator's public `get_diagnostics_snapshot()` API |
| `const.py` | Domain, config keys, timeouts, probe limits, BLE address types |

---

## Key Patterns

- **Global discovery:** `BluetoothCallbackMatcher(connectable=False)` + `PASSIVE` scanning — `connectable=False` receives ALL adverts (connectable and non-connectable); default `None` misses passive devices
- **Role-based entity gating:** `MEASUREMENT`/`UNKNOWN` → normal entity; `STATUS`/`INFO` → `EntityCategory.DIAGNOSTIC`; `CONTROL`/`FEATURE` → skipped (`SKIP_ROLES` in `entity_builder`)
- **Value routing:** Primitives → `add_simple_entity()`; msgspec Structs → `add_struct_entities()` with recursion and field-name prefixes; per-field units via `resolve_field_unit()` → GSS `FieldSpec.unit_id` → `UnitsRegistry`
- **Value coercion** (`to_ha_state` in `entity_builder`): `bool` → `bool`, `IntFlag` → `int`, `enum` → `.name`, primitives pass through, fallback → `str()`
- **Device class resolution:** `UNIT_TO_DEVICE_CLASS` dict in `entity_metadata`; disambiguates `"%"` by name (battery vs humidity); `CUMULATIVE_FIELD_NAMES` → `TOTAL_INCREASING`
- **Entity metadata always from library:** `char_instance.name`, `.unit`, `data.parsed_value`, `spec.primary_field` — never hardcode
- **GATT probe/poll:** `GATTManager.async_probe_device()` → `GATTProbeResult`; `async_probe_and_setup()` with semaphore; `async_poll_gatt_with_semaphore()` called by `ActiveBluetoothProcessorCoordinator`'s `poll_method` closure. Polling lifecycle owned by the framework, not `GATTManager`.
- **Discovery tracking:** `DiscoveryTracker` manages seen/rejected/stale device sets with LRU eviction and periodic cleanup
- **Advertisement management:** `AdvertisementManager` owns conversion (`BluetoothServiceInfoBleak` → `AdvertisementData`), per-device tracking, RSSI, callbacks; composed into `HomeAssistantBluetoothAdapter`; static helpers `get_manufacturer_name`/`get_model_name` used by coordinator
- **Support detection:** `SupportDetector` consolidates checking service data, manufacturer data, and GATT probes; produces `CharacteristicInfo` lists and summaries; composed into coordinator
- **Registry pre-warming:** `prewarm_registries()` static method run in executor during setup
- **No RSSI entities** — handled by other BLE monitor integrations
- **BLE address classification:** `classify_ble_address()` in `device_validator.py` checks **two metadata formats**: (1) BlueZ native: `device.details["props"]["AddressType"]` → `"public"`/`"random"`, (2) ESPHome proxy (via bleak-esphome): `device.details["address_type"]` → `0` (public) / `1` (random). Random addresses are sub-classified by top 2 bits of the first MAC octet per BT Core Spec §1.3. RPA (0x40–0x7F) and NRPA (0x00–0x3F) are filtered as ephemeral; Public, Random Static (0xC0–0xFF), and Unknown (no metadata) are treated as stable.
- **Public diagnostics API:** `coordinator.get_diagnostics_snapshot()` returns all diagnostic data; `coordinator.is_device_active()` checks processor status

---

## Code Style

- Python ≥3.12; uses `type` alias syntax (`type BluetoothSIGConfigEntry = ConfigEntry[...]`)
- Ruff: rules E, W, F, I, UP, B, C4, SIM; line-length 88; ignores E501
- mypy strict mode
- UK English in user-facing strings ("recognised" not "recognized")
- `UPPER_SNAKE_CASE` constants; `frozenset` for immutable sets
- `_` prefix for private methods; `async_` prefix for async methods
- `@callback` decorator for synchronous HA event loop callbacks

---

## Build and Test

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test,dev]" && pip install aiousbwatcher

# Lint, format, type-check
ruff check . --fix && ruff format .
mypy custom_components/bluetooth_sig_devices

# Tests
pytest tests/ -v
pytest tests/ --cov=custom_components/bluetooth_sig_devices --cov-report=term-missing
```

### Live HA Debugging

The HA instance runs in a supervised Docker environment. **Always read real logs before diagnosing issues** — never guess at root causes.

```bash
# Read recent HA Core logs (primary debugging command)
ha core logs
ha core logs --lines 5000

# Filter for this integration's log lines
ha core logs 2>&1 | grep -i "bluetooth_sig_devices"
ha core logs --lines 5000 2>&1 | grep -i "bluetooth_sig" | grep -iE "firing|discovery|flow|trigger"

# Restart HA Core after code changes (picks up custom_components)
ha core restart

# HA config directory (configuration.yaml, custom_components symlink, etc.)
# Location: /homeassistant/

# Execute commands inside the HA Core Docker container
docker exec homeassistant <command>
# e.g. check installed package versions:
docker exec homeassistant pip show bleak-esphome
```

**Key log namespaces to filter:**
- `habluetooth.wrappers` — BLE connection path selection (upstream)

### Test Tiers

1. **Unit** (`test_coordinator.py`, `test_sensor.py`, `test_device_adapter.py`) — direct class instantiation with `MagicMock`
2. **Config flow** (`test_config_flow.py`, `test_discovery_flow.py`) — `mock_bluetooth_disabled` or `enable_bluetooth`
3. **Integration/advertising** (`test_integration_advertising.py`) — `enable_bluetooth` + `inject_bluetooth_service_info` + fixture replay
4. **Integration/GATT** (`test_integration_connected.py`) — `mock_gatt_connection`; autouse fixture patches `ActiveBluetoothProcessorCoordinator`

Key test helpers in `tests/bluetooth_helpers.py`: `load_fixture()`, `load_service_info()`, `iter_service_infos()`, `inject_bluetooth_service_info()`, `build_mock_bleak_client()`, `mock_gatt_connection()`. JSON fixtures in `tests/fixtures/` are real ESPHome BLE advertisement captures.

---

## Constraints

| Constraint | Value |
|------------|-------|
| Python | ≥3.12 |
| Home Assistant | ≥2026.1.0 |
| Config entries | Hub + N device entries (no `single_config_entry`) |
| Scanning mode | `BluetoothScanningMode.PASSIVE` |
| GATT probe concurrency | 2 (`MAX_CONCURRENT_PROBES`) |
| GATT poll interval | 30–86400s (default 300s) |
| Dependencies | `bluetooth-sig>=0.2.0`, `bleak-retry-connector>=3.0.0`, `homeassistant.components.bluetooth` |

---

## Common Tasks

- **New characteristic support:** No changes here — add parser in `bluetooth-sig-python`; picked up automatically via `CharacteristicRegistry`
- **New platform** (e.g., `binary_sensor`): Add to `PLATFORMS` in `__init__.py`, create platform file following `sensor.py`, extend `_build_passive_bluetooth_update()` in coordinator
- **Debug logging:** Set `custom_components.bluetooth_sig_devices: debug` and `bluetooth_sig: debug` in HA logger config
- **Key references:** `ha_plan.md` (design rationale), `tests/conftest.py` (fixtures), `tests/bluetooth_helpers.py` (BLE injection), `tests/fixtures/` (captures), `quality_scale.yaml` (HA quality tracking)
