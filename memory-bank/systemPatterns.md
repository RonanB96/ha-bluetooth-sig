# System Patterns

## Architectural Patterns

### Composition over Inheritance
The coordinator composes four managers rather than inheriting from a base class. Each manager is constructed with a back-reference to the coordinator for cross-cutting queries but never references sibling managers directly. This enforces the coordinator as the sole orchestration point.

### Two-Tier Config Entry
Hub entry (singleton, no address) owns the global scanner. Device entries (one per MAC, created via discovery flow) own per-device processors. The hub entry's `runtime_data` holds the coordinator; device entries' `runtime_data` also holds the same coordinator reference. Platform setup (`sensor.py`) discriminates by checking for `"address"` in `entry.data`.

### Passive Bluetooth Processor Framework
`ActiveBluetoothProcessorCoordinator` (HA framework) manages the entity lifecycle: it calls `update_method` on each advertisement, evaluates `needs_poll_method`, and invokes `poll_method` when polling is due. The integration only needs to produce `PassiveBluetoothDataUpdate` objects — the framework handles entity registration, availability, and state updates.

### Stateless Entity Construction
`entity_builder.py` and `entity_metadata.py` are pure-function modules with no internal state. They transform parsed library data into HA entity descriptions using registry lookups. This makes them trivially testable and ensures entity metadata is always fresh from the library.

## Design Patterns

### Factory Closures
`create_device_processor()` produces `_needs_poll` and `_poll_gatt` closures that capture the device address. The HA framework calls these closures on every advertisement event — each closure knows which device it belongs to without requiring a dispatch table.

### Dual-Layer Advertisement Conversion
`AdvertisementManager.convert_advertisement()` performs two steps: (1) `_build_ad_structures()` for fast structural mapping (always succeeds), (2) `_parse_payloads()` for interpreter invocation (heavy but cached). This separation means structural data is always available even if interpretation fails.

### Role-Based Entity Gating
Characteristic roles from the library (`MEASUREMENT`, `STATUS`, `INFO`, `CONTROL`, `FEATURE`, `UNKNOWN`) drive entity visibility. `SKIP_ROLES` suppresses control/feature characteristics from appearing as sensors. `DIAGNOSTIC_ROLES` marks status/info as `EntityCategory.DIAGNOSTIC` (disabled by default in the entity registry).

### Value Type Routing
Parsed values are routed based on their Python type: primitives → `add_simple_entity()`, msgspec Structs → `add_struct_entities()` (recursive), raw service data bytes → `add_service_data_entities()` (translator parse). This dispatch avoids a single monolithic handler.

## Concurrency Controls

| Mechanism | Location | Purpose |
|---|---|---|
| `asyncio.Semaphore(2)` | `GATTManager._probe_semaphore` | Limits concurrent BLE connections to 2 |
| `pending_probes: set` | `GATTManager` | Prevents duplicate probe tasks for the same address |
| `probe_failures: dict[str, int]` | `GATTManager` | Stops probing after 3 failures per device |
| `_initial_gatt_cache` | `GATTManager` | Avoids second connection after probe; first poll returns cached data |

## Memory Bounds

| Mechanism | Limit | Location |
|---|---|---|
| `seen_devices` cap | 2048 | `DiscoveryTracker` — LRU eviction of oldest 25% when exceeded |
| `rejected_devices` cap | 4096 | `DiscoveryTracker` — hard cap, oldest silently overwritten |
| Stale cleanup | 1-hour timeout, 15-min interval | `DiscoveryTracker.async_cleanup_stale_devices()` |
| Ephemeral filter | On every advertisement | `is_static_address()` rejects RPA/NRPA before any tracking |

## Common Idioms

- **`@callback` decorator** on synchronous methods called from the HA event loop (e.g., `_async_device_discovered`)
- **`async_` prefix** on all async methods; `_` prefix on private methods
- **`type` alias syntax** for config entry types (`type BluetoothSIGConfigEntry = ConfigEntry[...]`)
- **`frozenset` for immutable constant sets** (e.g., `STATIC_ADDRESS_TYPES`, `EXCLUDED_SERVICE_NAMES`)
- **Executor offloading** for blocking operations (`prewarm_registries()`, registry lookups in service discovery)