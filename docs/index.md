# Bluetooth SIG Devices

A Home Assistant custom integration that automatically creates sensor entities from Bluetooth devices broadcasting standard **Bluetooth SIG GATT characteristics** and recognised manufacturer data.

No hardcoded device maps — all parsing is driven by the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library. When the library adds support for a new characteristic, this integration picks it up automatically.

## What this integration does

- Discovers Bluetooth devices advertising standard SIG service data or recognised manufacturer data
- Presents discovered devices for user confirmation before creating entities
- Creates sensor entities with correct units, device classes, and state classes — all resolved from official GATT specifications
- Combines passive advertisement monitoring with active GATT characteristic polling for maximum data coverage

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

## Documentation

This documentation follows the [Diátaxis](https://diataxis.fr/) framework:

| Section | Purpose |
|---|---|
| **[Getting Started](tutorials/getting-started.md)** | Step-by-step tutorial to install and set up the integration |
| **[How-to Guides](how-to/index.md)** | Task-oriented guides for common operations |
| **[Reference](reference/index.md)** | Technical details — entities, configuration, supported characteristics |
| **[Explanation](explanation/index.md)** | Background concepts — how discovery works, data paths, architecture |
