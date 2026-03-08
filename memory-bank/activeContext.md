# Active Context

## Current Branch

`ha_testing` — active testing branch with PR #2 open against `main`.

## Current Goals

- Architecture documentation: populating memory-bank files and enhancing copilot-instructions.md with composition hierarchy, lifecycle phases, and data transformation pipeline
- Integration is feature-complete for the sensor platform; focus is on documentation, testing, and quality improvements

## Recent Work

- Refactored monolithic coordinator into coordinator + 4 sub-managers (GATTManager, DiscoveryTracker, SupportDetector, AdvertisementManager)
- Added BLE address classification (BlueZ + ESPHome metadata formats)
- Implemented two independent data paths (advertisement + GATT polling)
- Added memory-bounded tracking with LRU eviction and stale cleanup
- Created comprehensive test suite across 4 tiers (unit, config flow, integration/advertising, integration/GATT)

## Current Blockers

- None