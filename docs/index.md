# Bluetooth SIG Devices

A Home Assistant custom integration that automatically creates sensor entities from Bluetooth devices broadcasting standard **Bluetooth SIG GATT** (Generic Attribute Profile) **characteristics** and recognised manufacturer data. In plain terms: if your Bluetooth device follows the official Bluetooth standard for reporting sensor data, this integration can read it automatically.

No hardcoded device maps — all parsing is driven by the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library. When the library adds support for a new characteristic, this integration picks it up automatically.

## What this integration does

- Discovers Bluetooth devices advertising standard SIG service data or recognised manufacturer data
- Presents discovered devices for user confirmation before creating entities
- Creates sensor entities with correct units, device classes, and state classes — all resolved from official GATT specifications
- Combines passive advertisement monitoring with active GATT characteristic polling for maximum data coverage

## How it works

This integration is built on two components that work together:

| Component | What it does |
|---|---|
| [**bluetooth-sig-python**](https://github.com/RonanB96/bluetooth-sig-python) (library) | Parses raw Bluetooth bytes into structured data. Provides the characteristic registry, role classification, unit resolution, and manufacturer data interpretation. New characteristic support is added to the library — this integration picks it up automatically. |
| **This integration** | Discovers BLE devices in Home Assistant, manages configuration entries, creates sensor entities, handles GATT polling, and maps the library's parsed output to Home Assistant entity properties (device class, state class, entity category). |

## What this integration does NOT support

| Protocol | Use instead |
|---|---|
| BTHome | [BTHome integration](https://www.home-assistant.io/integrations/bthome/) |
| Xiaomi BLE sensors | Dedicated Xiaomi integrations |
| Other vendor-specific protocols | Protocol-specific integrations |

## Requirements

- Home Assistant **2026.1.0** or later
- A Bluetooth adapter (built-in, USB dongle, or [ESPHome BLE proxy](https://esphome.io/components/bluetooth_proxy.html))
- Bluetooth devices broadcasting **standard SIG GATT service data**

## Planned features

The integration is currently **read-only** — it monitors and measures, but does not control devices.

Support for **writing to writable Bluetooth characteristics** is planned. When implemented, characteristics with Control and Feature roles (e.g., resetting an energy counter or setting an alert level) will become actionable Home Assistant entities such as buttons, number inputs, and selects. This will require new entity platforms beyond the current sensor-only approach.

Until then, Control and Feature characteristics are not exposed as entities. See [Characteristic Roles](explanation/roles.md) for details.

## Documentation

This documentation follows the [Diátaxis](https://diataxis.fr/) framework:

| Section | Purpose |
|---|---|
| **[Getting Started](tutorials/getting-started.md)** | Step-by-step tutorial to install and set up the integration |
| **[How-to Guides](how-to/index.md)** | Task-oriented guides for common operations |
| **[Reference](reference/index.md)** | Technical details — entities, configuration, supported characteristics |
| **[Explanation](explanation/index.md)** | Background concepts — how discovery works, data paths, architecture |
