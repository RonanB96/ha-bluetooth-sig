# Progress

## Done

- [x] Core integration architecture (hub + device config entries)
- [x] Coordinator with 4 sub-managers (GATTManager, DiscoveryTracker, SupportDetector, AdvertisementManager)
- [x] HomeAssistantBluetoothAdapter (ClientManagerProtocol bridge)
- [x] Passive advertisement data path (update_method → entity builder → PassiveBluetoothDataUpdate)
- [x] Active GATT polling data path (poll_method → characteristic reads → PassiveBluetoothDataUpdate)
- [x] Entity builder with role gating, value coercion, struct expansion
- [x] Entity metadata resolution (unit → device class, per-field unit from GSS)
- [x] BLE address classification (BlueZ + ESPHome, ephemeral filtering)
- [x] Discovery flow (integration_discovery source, user confirmation)
- [x] Config flow (hub step, YAML import, options for poll_interval)
- [x] Diagnostics (coordinator snapshot API)
- [x] Memory-bounded tracking (LRU eviction, stale cleanup, probe failure limits)
- [x] Test suite: unit, config flow, integration/advertising, integration/GATT
- [x] Architecture documentation in copilot-instructions.md and memory-bank

## Doing

- [ ] Quality improvements and test coverage expansion

## Next

- [ ] Binary sensor platform support (new platform file, extend `_build_passive_bluetooth_update()`)
- [ ] HA quality scale progression (see `quality_scale.yaml`)
- [ ] Additional manufacturer data interpreter support (upstream library work)