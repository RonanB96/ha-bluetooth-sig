# Discovery Flow Diagnostic Plan

## Context
3 devices appear in HA's "Discovered" UI — `discovery_flow.async_create_flow()` is working correctly.
The previous agent was wrong about discovery not firing.

**Goal**: Add INFO-level logging at every hand-off stage so the full end-to-end flow can be confirmed via `ha core logs`. Then reload the integration (not restart HA) and verify.

## Reference Pattern (sensorpush, xiaomi_ble, govee_ble — all gold/platinum)
```
1. async_setup_entry() creates PassiveBluetoothProcessorCoordinator
2. async_forward_entry_setups(entry, PLATFORMS)
3. sensor platform registers processor + entity listener
4. entry.async_on_unload(coordinator.async_start())  ← LAST
```

**Key rule**: `async_start()` must be called AFTER platforms have subscribed processors.
Our code does this correctly within `create_device_processor()` — listener → register → start.

## Steps

### 1. Add INFO logging to config_flow.py ✅
- `async_step_integration_discovery()`: log receipt of discovery flow (address + name)
- `async_step_integration_discovery_confirm()`: log user confirmation before `async_create_entry`

### 2. Add INFO logging to __init__.py ✅
- `_async_setup_device_entry()`: log entry + after `async_forward_entry_setups`

### 3. Upgrade coordinator.py logging at key decision points ✅
- `create_device_processor()`: DEBUG → INFO for "Creating processor coordinator"
- `_ensure_device_processor()`: INFO at each early-return (processor exists, config entry exists, discovery already triggered)
- `_build_passive_bluetooth_update()`: INFO with entity count before returning

### 4. Reduce DEBUG noise flood ✅
- Added `_seen_devices` set — each device logged once at INFO on first sighting
- Added `_rejected_devices` set — fully-evaluated unsupported devices skip reprocessing
- Removed per-call DEBUG from `_has_supported_data()` and `device_adapter.convert_advertisement()`

### 5. Upgrade probe outcome logging to INFO ✅
- Probe timeout, failure, and no-parseable messages upgraded from DEBUG to INFO

### 6. Fix CurrentTimeCharacteristic bug ✅
- `device_adapter.py` line 552: `char_class(properties=properties)` fails for some
  characteristic classes (e.g. `CurrentTimeCharacteristic`) that don't accept `properties` kwarg
- Fix: Wrapped in try/except TypeError with fallback to `char_class()`

### 7. Fix blocking I/O warning ✅
- bluetooth-sig library loads YAML files synchronously via `registry/utils.py:26`
- Fix: Added `prewarm_registries()` static method that loads all registry caches
- Called via `hass.async_add_executor_job()` in `_async_setup_hub_entry()` BEFORE
  creating the coordinator (whose `__init__` also triggers YAML loading)
- Warms: CharacteristicRegistry, GattServiceRegistry, UnitsRegistry (both module-level
  singleton and `get_instance()` singleton — they're separate objects!)

## Verified Discoveries

After 3 HA restarts with progressively better logging, confirmed **4 unique device discoveries**:

| # | Address | Name | Source | Parseable Chars |
|---|---------|------|--------|-----------------|
| 1 | C7:34:0F:86:37:04 | SBF77 | Advertisement data | N/A (service data) |
| 2 | 70:4A:1F:D1:C9:38 | (unnamed) | GATT probe | 2 |
| 3 | A4:C1:38:B0:35:69 | LYWSD03MMC | GATT probe | 6 |
| 4 | C4:DD:57:75:5C:F6 | dummy-health-monitor | GATT probe | 5 |

### Probe Outcomes for Other Devices
- **50:FD:D5:58:21:79** (Dryer): GATT probe — no parseable characteristics
- **50:FD:D5:FA:DB:EA** (Washer): GATT probe — timed out (attempt 2/3)
- **24:E5:1D:6F:9D:4D**: GATT probe — no parseable characteristics
- **4B:6D:BD:38:49:49**: Probe failed — CurrentTimeCharacteristic bug (now fixed)
- **E3:EB:40:E0:04:D7**: GATT probe — timed out
- **68:FC:CA:CE:DB:91**: Connection failed — "br-connection-key-missing"
- Multiple random MAC devices: "No BLE device available" — out of range

### Bug: SBF77 Fires Discovery on Every Restart
- SBF77 fires a discovery flow on every restart because `_discovery_triggered` is in-memory
- HA's config flow system deduplicates at the flow level, so this doesn't create duplicate entries
- Not a real bug, just slightly noisy

## Expected Log Chain After Confirming a Device
```
1. [config_flow] Discovery flow received for XX:XX:XX (DeviceName)
2. [config_flow] User confirmed device XX:XX:XX — creating entry
3. [__init__]    Setting up device entry for XX:XX:XX
4. [__init__]    Sensor platform forwarded for XX:XX:XX
5. [coordinator] Creating processor coordinator for XX:XX:XX
6. [coordinator] Now tracking Bluetooth device XX:XX:XX
7. [coordinator] Device XX:XX:XX: first update — N entities
8. [coordinator] Device XX:XX:XX: update contains N entities
```

## Diagnosis Based on Results
- **N=0 entities** → `_build_passive_bluetooth_update()` isn't producing entities from the advertisement data. Next: investigate what `_has_supported_data()` matched on vs what `_build_passive_bluetooth_update()` receives.
- **Step 7 never fires** → `PassiveBluetoothProcessorCoordinator` isn't receiving advertisements for that address. Transient (device stopped advertising) or BLE scanner issue.
- **Step 5 never fires** → sensor platform forwarding failed. Check for errors in `async_setup_entry`.
- **Step 1 never fires** → the config flow isn't receiving the discovery. Check `strings.json` for missing step definition or `manifest.json` for missing `config_flow: true`.
