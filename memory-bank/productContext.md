# Product Context

## Overview

`bluetooth_sig_devices` is a Home Assistant custom integration that sits between HA's Bluetooth stack and the `bluetooth-sig-python` parsing library. It registers a global BLE scanner, detects devices broadcasting parseable SIG data, guides the user through a discovery confirmation flow, then continuously translates BLE advertisements and GATT characteristic reads into HA sensor entities.

## Core Features

- **Automatic discovery** — global `BluetoothCallbackMatcher(connectable=False)` catches all advertisements; `SupportDetector` evaluates service data, manufacturer data, and GATT probes to determine support
- **Two independent data paths** — passive advertisement parsing and active GATT characteristic polling, merged by the HA framework into a unified entity set
- **Library-driven entity construction** — entity names, units, device classes, and state classes are resolved entirely from `bluetooth-sig-python` registries and GSS field specs
- **Role-based entity gating** — MEASUREMENT/UNKNOWN → normal sensors; STATUS/INFO → diagnostic entities; CONTROL/FEATURE → suppressed
- **Struct field expansion** — complex multi-field characteristics (msgspec Structs) are recursively expanded into per-field entities with correct per-field units
- **BLE address classification** — ephemeral addresses (RPA, NRPA) are filtered to prevent tracking flickering devices
- **Bounded resource usage** — LRU eviction (2048 seen, 4096 rejected), stale cleanup (1-hour timeout, 15-minute interval), probe failure limits (3 per device)

## Technical Stack

- **Runtime:** Python ≥3.12, Home Assistant ≥2026.1.0
- **BLE layer:** `bleak` (via HA's `habluetooth`), `bleak-retry-connector` for connection retries
- **Parsing library:** `bluetooth-sig-python` (`bluetooth-sig>=0.2.0`) — GATT registries, characteristic parsers, manufacturer data interpreters
- **HA framework classes:** `ActiveBluetoothProcessorCoordinator`, `PassiveBluetoothDataProcessor`, `PassiveBluetoothProcessorEntity`
- **Tooling:** Ruff (lint/format), mypy (strict), pytest with HA test helpers

## Key Dependencies

| Dependency | Role |
|---|---|
| `bluetooth-sig` | GATT characteristic parsing, registry lookups, manufacturer data interpretation |
| `bleak-retry-connector` | Resilient BLE GATT connections with automatic retries |
| `homeassistant.components.bluetooth` | Global BLE scanner, `BluetoothServiceInfoBleak`, discovery flow primitives |