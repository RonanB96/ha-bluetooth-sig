# Decision Log

| Date | Decision | Rationale |
|------|----------|-----------||
| — | **Two-tier config entry** (hub + per-device) | Supported devices determined at runtime; hub owns scanner, device entries own processors; matches iBeacon/private_ble_device pattern |
| — | **Coordinator → sub-manager delegation** | Single-responsibility; each manager testable in isolation; coordinator is pure orchestration |
| — | **Library-driven entity metadata** | No hardcoded maps; new characteristics supported via library update only |
| — | **Dual independent data paths** (advertisement + GATT) | Some devices only broadcast; others need GATT reads; framework merges both paths by entity key |
| — | **Factory closures for poll methods** | Each device needs address-specific poll logic; closures capture address at creation time |
| — | **Ephemeral address filtering** | RPA/NRPA rotate frequently; filtering prevents unbounded tracking and spurious discovery |
| — | **GATT initial read cache** | Read characteristics during probe connection; first poll returns cache, saving a BLE connection |
| — | **Registry pre-warming in executor** | Avoid blocking event loop during YAML registry loading (~200ms) |
| — | **Role-based entity gating** | CONTROL/FEATURE characteristics should not appear as sensors; STATUS/INFO are diagnostic-only |
| — | **`connectable=False` matcher** | Receives ALL advertisements including non-connectable passive devices; default `None` misses them |
| — | **Semaphore-limited GATT concurrency** | Max 2 concurrent BLE connections prevents radio contention and adapter exhaustion |
| — | **LRU eviction for tracking sets** | Caps at 2048 seen / 4096 rejected; prevents unbounded memory growth in BLE-dense environments |