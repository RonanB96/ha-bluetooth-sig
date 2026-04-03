# Bluetooth SIG Devices for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/RonanB96/ha-bluetooth-sig?style=for-the-badge)](https://github.com/RonanB96/ha-bluetooth-sig/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/RonanB96/ha-bluetooth-sig/hacs.yml?branch=main&label=HACS%20Validation&style=for-the-badge)](https://github.com/RonanB96/ha-bluetooth-sig/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/RonanB96/ha-bluetooth-sig?style=for-the-badge)](LICENSE)

A Home Assistant custom integration that automatically creates sensors from Bluetooth devices advertising **standard Bluetooth SIG GATT characteristics** using the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library.

No hardcoded device maps — all parsing is fully library-driven. When the library adds support for a new characteristic, this integration picks it up automatically.

> This integration only supports standard Bluetooth SIG protocols. Devices using proprietary formats (BTHome, Xiaomi, etc.) require their own dedicated integrations.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RonanB96&repository=ha-bluetooth-sig&category=integration)

1. Click the badge above, or open HACS → Integrations → ⋮ → Custom repositories and add `RonanB96/ha-bluetooth-sig` as an **Integration**
2. Download **Bluetooth SIG Devices** from HACS
3. Restart Home Assistant

### Manual

Copy `custom_components/bluetooth_sig_devices` into your `<config>/custom_components/` directory and restart Home Assistant.

## Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bluetooth_sig_devices)

After installation, add the **Bluetooth SIG Devices** integration in **Settings → Devices & Services**, or click the badge above. Discovered devices will appear for one-click confirmation.

See the [Getting Started tutorial](docs/tutorials/getting-started.md) for detailed steps.

## Features

- **Automatic discovery** — detects devices broadcasting standard SIG service data or recognised manufacturer data
- **Dynamic sensor creation** — entities with correct units, device classes, and state classes resolved from GATT specifications
- **Passive scanning** — uses Home Assistant's passive Bluetooth infrastructure for low overhead
- **Active GATT polling** — periodically connects to read characteristics not available in advertisements
- **Zero per-device configuration** — discovered devices are presented for one-click confirmation

## Documentation

Full documentation follows the [Diátaxis](https://diataxis.fr/) framework:

| Section | Purpose |
|---|---|
| [**Getting Started**](docs/tutorials/getting-started.md) | Step-by-step installation and setup |
| [**How-to Guides**](docs/how-to/index.md) | Task-oriented guides (poll interval, debug logging, removal) |
| [**Reference**](docs/reference/index.md) | Entities, configuration, supported characteristics, diagnostics |
| [**Explanation**](docs/explanation/index.md) | How discovery works, data paths, architecture overview |

## Troubleshooting

See the [troubleshooting guide](docs/how-to/troubleshooting.md) for common issues, or [enable debug logging](docs/how-to/enable-debug-logging.md) to diagnose problems.

## Contributing

Issues and pull requests are welcome on [GitHub](https://github.com/RonanB96/ha-bluetooth-sig). For adding support for new Bluetooth characteristics, contribute to the upstream [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library — this integration will pick up changes automatically.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Credits

- [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) – Core Bluetooth SIG parsing library
- [Home Assistant](https://www.home-assistant.io/) – Home automation platform
- [Bluetooth SIG](https://www.bluetooth.com/) – For Bluetooth specifications and GATT standards
