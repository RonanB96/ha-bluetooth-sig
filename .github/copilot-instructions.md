---
description: "Bluetooth SIG Devices — core agent instructions for architecture, rules, and conventions"
applyTo: '**'
alwaysApply: true
---

# Bluetooth SIG Devices — AI Agent Instructions

Home Assistant custom integration for automatic Bluetooth sensor creation using the `bluetooth-sig-python` library. Parses standard Bluetooth SIG GATT characteristics and manufacturer data — no hardcoded maps, fully library-driven.

## Architecture

Uses a two-tier config entry model: a single hub entry owns the global BLE scanner and coordinator; per-device entries are created via discovery flow at runtime. Whether a device is supported is determined at runtime by whether the library can parse its data — there is no static device registry.

Two independent data paths feed the coordinator:
- **Advertisement path** — passive; broadcast service data UUIDs and manufacturer data
- **GATT path** — active; characteristic reading via BLE connection

Both paths produce update objects merged by `ActiveBluetoothProcessorCoordinator`. The GATT path is polled on a timer; the advertisement path is event-driven.

See `.github/instructions/ha-integration.instructions.md` for component map, key patterns, and constraints.

## Non-Negotiable Rules

- **No hardcoded UUIDs, names, or unit maps** — all metadata comes from the library at runtime
- **Entity metadata always from library** — characteristic name, unit, and parsed value come from the library; never hardcode them in the integration
- **No RSSI entities** — handled by dedicated BLE monitor integrations
- **New characteristic support requires no changes here** — add the parser in `bluetooth-sig-python`; picked up automatically via the characteristic registry
- **Library-driven discovery** — no static list of supported devices; support is determined by whether the library can parse the device's data

## Code Style

- Python ≥3.12; `type` alias syntax; Ruff (E, W, F, I, UP, B, C4, SIM); mypy strict
- UK English in user-facing strings
- `UPPER_SNAKE_CASE` constants; `frozenset` for immutable sets
- `_` prefix for private methods; `async_` prefix for async methods
- `@callback` for synchronous HA event loop callbacks

## Upstream Library Issues

When a workaround is needed due to a limitation in `bluetooth-sig-python`:

1. Add the issue to `UPSTREAM_ISSUES.md` with a description, the workaround, and status
2. Mark the workaround in code with `# UPSTREAM: see UPSTREAM_ISSUES.md`
3. Open a GitHub issue on the library repo if significant

## Sub-Instructions

These files are the source of truth for both GitHub Copilot and Cursor. Cursor loads them via symlinks in `.cursor/rules/`.

- `.github/instructions/ha-integration.instructions.md` — component map, data flow, key patterns, constraints (`custom_components/**/*.py`)
- `.github/instructions/ha-testing.instructions.md` — test tiers, helpers, fixtures (`tests/**/*.py`)
- `.github/instructions/ha-debugging.instructions.md` — build/lint commands, live HA debugging (on-demand)
