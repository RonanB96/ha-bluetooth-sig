# Project Brief

## Purpose

Home Assistant custom integration that automatically creates sensor entities for any Bluetooth device broadcasting standard SIG GATT characteristics or recognised manufacturer data. Fully library-driven — the integration itself contains no hardcoded device maps; all parsing, naming, and unit assignment come from the `bluetooth-sig-python` library's GATT registries.

## Target Users

- Home Assistant users with BLE-capable hardware (built-in adapter, ESPHome BLE proxy, or similar)
- Users who own Bluetooth devices that broadcast standard SIG services (environment sensors, health monitors, smart watches, mesh nodes)
- Developers extending Bluetooth SIG GATT support in the upstream `bluetooth-sig-python` library

## Value Proposition

- **Zero configuration per device** — the integration discovers supported devices and presents them for confirmation; no YAML editing or manual UUID entry required
- **Automatic characteristic parsing** — new SIG characteristics are supported the moment the library adds a parser, with no integration code changes
- **Dual data paths** — combines passive advertisement monitoring with active GATT polling for maximum data coverage
- **Memory-bounded and resilient** — LRU eviction, stale cleanup, probe failure limits, and ephemeral address filtering prevent resource exhaustion
