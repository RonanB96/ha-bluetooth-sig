---
description: "Integration code, components, data flow, and BLE device handling"
applyTo: "custom_components/**/*.py"
globs: custom_components/**/*.py
alwaysApply: false
---

# HA Integration — Component Map, Patterns & Constraints

## Data Flow

`__init__.py` creates `BluetoothSIGCoordinator` (hub entry) → `async_start()` registers global BT callback → `_async_device_discovered()` → `DiscoveryOrchestrator.ensure_device_processor()` (fires discovery flow / schedules GATT probe / rejects) → after user confirms: `create_device_processor()` → `ActiveBluetoothProcessorCoordinator` → `data_pipeline.update_device()` → `PassiveBluetoothDataUpdate` → `BluetoothSIGSensorEntity`.

The GATT poll is dual-triggered:
- **Event-driven:** `needs_poll_method` on each advertisement callback (prompt poll when a device returns to range)
- **Timer-driven:** `async_track_time_interval` per confirmed device at the effective poll interval (steady-state polling for GATT-only devices whose adverts are deduplicated by HA)

**Reference integrations:** iBeacon, private_ble_device — same hub + `BluetoothCallbackMatcher(connectable=False)` pattern. OralB, Xiaomi BLE — same `ActiveBluetoothProcessorCoordinator` + `needs_poll_method` / `poll_method` pattern.

## Component Responsibilities

| File | Responsibility |
|------|----------------|
| `__init__.py` | Dispatches hub vs device setup; creates coordinator; forwards to sensor platform; handles unload and device removal |
| `coordinator.py` | Orchestrates processor lifecycle and GATT poll closures; delegates discovery to `DiscoveryOrchestrator` and advertisement pipeline to `data_pipeline` |
| `discovery_orchestrator.py` | Routes BLE devices to confirmed/unconfirmed paths; fires discovery flows; handles GATT probe success/failure callbacks |
| `data_pipeline.py` | Stateless advertisement pipeline: converts `BluetoothServiceInfoBleak` → `PassiveBluetoothDataUpdate`; creates `Device` on first sighting |
| `advertisement_converter.py` | Stateless advertisement conversion; 3-tier parsing (raw PDU → manual → platform enrichment); manufacturer/model extraction |
| `advertisement_manager.py` | Per-device advertisement tracking state, RSSI, callbacks; re-exports conversion functions from `advertisement_converter` |
| `support_detector.py` | Determines if a BLE device has parseable SIG data; characteristic tracking and summary building |
| `entity_builder.py` | Stateless entity construction from parsed library data; role gating; value coercion (`to_ha_state`) |
| `entity_metadata.py` | Pure-function entity metadata resolution: unit→device class mapping, UUID normalisation, field unit lookup |
| `gatt_manager.py` | GATT probing, concurrency semaphore, probe scheduling and failure tracking; delegates characteristic reading to `gatt_poller` |
| `gatt_poller.py` | GATT characteristic reading functions; shared by probe-time and poll-time paths |
| `discovery_tracker.py` | Seen/rejected/stale device tracking, LRU eviction, cleanup timer |
| `device_adapter.py` | `ClientManagerProtocol` impl; GATT connection lifecycle and I/O; delegates advertisement conversion to `AdvertisementManager` |
| `device_validator.py` | BLE address classification (`classify_ble_address`, `is_static_address`); `GATTProbeResult` dataclass |
| `sensor.py` | Entity adder via `create_device_processor()`; `BluetoothSIGSensorEntity` with availability logging |
| `config_flow.py` | Hub step, YAML import, integration_discovery confirm; `OptionsFlow` for poll_interval |
| `diagnostics.py` | Device statistics via coordinator's public `get_diagnostics_snapshot()` API |
| `const.py` | Domain, config keys, timeouts, probe limits, BLE address types |

## Key Patterns

- **Global discovery:** `BluetoothCallbackMatcher(connectable=False)` + `PASSIVE` scanning — `connectable=False` receives ALL adverts (connectable and non-connectable); default `None` misses passive devices
- **Role-based entity gating:** `MEASUREMENT`/`UNKNOWN` → normal entity; `STATUS`/`INFO`/`CONTROL`/`FEATURE` → `EntityCategory.DIAGNOSTIC` disabled by default (`DIAGNOSTIC_ROLES` frozenset in `entity_builder`)
- **Value routing:** Primitives → `add_simple_entity()`; msgspec Structs → `add_struct_entities()` with recursion and field-name prefixes; per-field units via `resolve_field_unit()` → GSS `FieldSpec.unit_id` → `UnitsRegistry`
- **Value coercion** (`to_ha_state`): `bool` → `bool`, `IntFlag` → `int`, `enum` → `.name`, primitives pass through, fallback → `str()`
- **Device class resolution:** `UNIT_TO_DEVICE_CLASS` dict in `entity_metadata`; disambiguates `"%"` by name (battery vs humidity); `CUMULATIVE_FIELD_NAMES` → `TOTAL_INCREASING`
- **GATT probe/poll:** `GATTManager.async_probe_device()` → `GATTProbeResult`; poll scheduling via `ActiveBluetoothProcessorCoordinator` (advert callbacks) plus per-device GATT poll timer in `coordinator.py`. Confirmed-device GATT work preempts discovery probes when connection slots are contended.
- **Public diagnostics API:** `coordinator.get_diagnostics_snapshot()` returns all diagnostic data; `coordinator.is_device_active()` checks processor status
- **Registry pre-warming:** `prewarm_registries()` static method run in executor during setup

## BLE Address Classification

`classify_ble_address()` in `device_validator.py`. Metadata formats checked in order:

| Source | Key | Values |
|--------|-----|--------|
| BlueZ native | `device.details["props"]["AddressType"]` | `"public"` / `"random"` |
| ESPHome proxy (bleak-esphome) | `device.details["address_type"]` | `0` (public) / `1` (random) |

Random addresses are sub-classified by the top 2 bits of the first MAC octet (BT Core Spec §1.3):

| Range | Type | Outcome |
|-------|------|---------|
| `0x40–0x7F` | RPA | Filtered as ephemeral |
| `0x00–0x3F` | NRPA | Filtered as ephemeral |
| `0xC0–0xFF` | Random Static | Treated as stable |
| Public / Unknown (no metadata) | — | Treated as stable |

When no metadata is present, a MAC-based heuristic is applied: first octet in the RPA or NRPA range → ephemeral; otherwise → `UNKNOWN` (stable).

## Constraints

| Constraint | Value |
|------------|-------|
| Config entries | Hub + N device entries (no `single_config_entry`) |
| Scanning mode | `BluetoothScanningMode.PASSIVE` |
| GATT probe concurrency | `MAX_CONCURRENT_PROBES` (const) |
| GATT poll interval | Configurable via `OptionsFlow`; bounded in `const.py` |

## Common Tasks

- **New platform** (e.g., `binary_sensor`): Add to `PLATFORMS` in `__init__.py`, create platform file following `sensor.py`, extend `_build_passive_bluetooth_update()` in coordinator
- **Debug logging:** See [docs/how-to/enable-debug-logging.md](../../docs/how-to/enable-debug-logging.md)
- **Key references:** `ha_plan.md` (design rationale), `quality_scale.yaml` (HA quality tracking)
