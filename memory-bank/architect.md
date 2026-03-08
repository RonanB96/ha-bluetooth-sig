# System Architect

## Overview

Architectural decisions and design rationale for the `bluetooth_sig_devices` Home Assistant integration. Each decision is recorded with the problem it solves, the chosen approach, and why alternatives were rejected.

## Architectural Decisions

### AD-1: Two-Tier Config Entry Pattern

**Problem:** Supported devices are determined at runtime by library parsing success — they cannot be enumerated statically in a manifest. A single config entry per device would require the user to manually add each device.

**Decision:** Use a hub entry (`unique_id=DOMAIN`, no `address` key) for the global BLE scanner and coordinator, plus per-device entries (`unique_id=address`) created via `discovery_flow` after user confirmation.

**Rationale:** Matches the iBeacon and private_ble_device reference integrations. The hub entry ensures the scanner starts once; device entries give the user control over which devices to enable. `_is_hub_entry(entry)` discriminates by checking `"address" not in entry.data`.

### AD-2: Coordinator → Sub-Manager Delegation

**Problem:** A monolithic coordinator would be too complex to test and maintain, with GATT connection management, discovery tracking, support detection, and advertisement conversion all interleaved.

**Decision:** `BluetoothSIGCoordinator` delegates to four composed managers (`GATTManager`, `DiscoveryTracker`, `SupportDetector`, `AdvertisementManager`), each with a single concern. No manager references another directly — all cross-cutting flows through the coordinator.

**Rationale:** Single-responsibility principle. Each manager can be unit-tested in isolation with a mocked coordinator. The coordinator acts purely as an orchestration layer.

### AD-3: Library-Driven Entity Metadata

**Problem:** Hardcoding characteristic names, units, and device classes would require integration changes for every new Bluetooth SIG characteristic.

**Decision:** All entity metadata (name, unit, device class, state class) is resolved at runtime from `bluetooth-sig-python` registries: `CharacteristicRegistry`, `UnitsRegistry`, GSS `FieldSpec`, and manufacturer data interpreters.

**Rationale:** New characteristic support is a library-only change — the integration picks it up automatically. No integration code changes needed for new devices.

### AD-4: Dual Independent Data Paths

**Problem:** Some BLE devices only broadcast advertisements; others require active GATT connections to read all characteristics. A single approach would miss data from one category.

**Decision:** Two completely independent paths: (1) passive advertisement parsing via `update_method`, (2) active GATT polling via `poll_method`. Both produce `PassiveBluetoothDataUpdate` objects that the HA framework merges by entity key.

**Rationale:** Matches the OralB and Xiaomi BLE reference patterns. Entity keys (UUID-based) are naturally disjoint between paths, so merging is conflict-free.

### AD-5: Address-Specific Closure Pairing

**Problem:** The HA framework's `ActiveBluetoothProcessorCoordinator` expects `needs_poll_method` and `poll_method` callables, but each device needs its own polling logic based on its address and probe results.

**Decision:** `create_device_processor()` produces factory closures that capture the device address. Each closure independently checks probe results and poll intervals for its captured address.

**Rationale:** Avoids a lookup table or dispatch pattern — the framework calls the closure directly with no address resolution needed. Clean functional composition.

### AD-6: Ephemeral Address Filtering

**Problem:** Resolvable Private Addresses (RPA) and Non-Resolvable Private Addresses (NRPA) rotate every ~15 minutes. Tracking them would create unbounded device entries.

**Decision:** `classify_ble_address()` in `device_validator.py` checks BlueZ and ESPHome metadata formats, then sub-classifies random addresses by the top 2 bits of the first MAC octet per BT Core Spec §1.3. RPA and NRPA are rejected; Public, Random Static, and Unknown (no metadata) are treated as stable.

**Rationale:** Prevents memory growth and spurious discovery flows. Unknown addresses are assumed stable because rejecting them would block devices behind backends that don't expose address type metadata.

### AD-7: GATT Probe Caching and Initial Read

**Problem:** GATT probing requires a BLE connection. Once connected, disconnecting and reconnecting for the first poll wastes battery and radio time.

**Decision:** `GATTManager._read_chars_connected()` reads all characteristics during the probe while the connection is still open, caching the result in `_initial_gatt_cache`. The first `poll_method` call returns this cache (no semaphore, no connection). Subsequent polls connect normally.

**Rationale:** Reduces the number of BLE connections from 2 to 1 for initial setup. The semaphore is not needed for the cached read since no actual connection occurs.

### AD-8: Registry Pre-Warming

**Problem:** The `bluetooth-sig-python` library loads YAML registry files on first access. Doing this on the event loop would block HA during setup.

**Decision:** `prewarm_registries()` is a static method that runs in the executor during hub entry setup, before the coordinator starts.

**Rationale:** Moves ~200ms of YAML parsing off the event loop. Subsequent registry accesses are instant.

