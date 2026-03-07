# Bluetooth SIG Devices for Home Assistant

A Home Assistant custom integration that automatically creates sensors from Bluetooth devices advertising **standard Bluetooth SIG GATT characteristics** using the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library.

No hardcoded device maps — all parsing is fully library-driven. When the library adds support for a new characteristic, this integration picks it up automatically.

## Features

- **Automatic discovery** — detects devices broadcasting standard SIG service data or recognised manufacturer data
- **Dynamic sensor creation** — entities with correct units, device classes, and state classes resolved from GATT specifications
- **Passive scanning** — uses Home Assistant's passive Bluetooth infrastructure for low overhead
- **Active GATT polling** — periodically connects to read characteristics not available in advertisements
- **Zero per-device configuration** — discovered devices are presented for one-click confirmation

> This integration only supports standard Bluetooth SIG protocols. Devices using proprietary formats (BTHome, Xiaomi, etc.) require their own dedicated integrations.

## Quick Start

1. Install via [HACS](https://hacs.xyz/) or copy `custom_components/bluetooth_sig_devices` manually
2. Add the **Bluetooth SIG Devices** integration in Settings → Devices & Services
3. Confirm discovered devices as they appear

See the [Getting Started tutorial](docs/tutorials/getting-started.md) for detailed steps.

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

## Development

### Requirements

- Home Assistant 2026.1.0 or newer
- bluetooth-sig-python
- Python 3.12 or newer

### Project Structure

```
custom_components/bluetooth_sig_devices/
├── __init__.py           # Integration setup
├── config_flow.py        # Configuration flow
├── const.py              # Constants
├── coordinator.py        # Data coordinator
├── device_adapter.py     # HA ↔ bluetooth-sig-python adapter
├── manifest.json         # Integration manifest
├── quality_scale.yaml    # Integration quality tracking
└── sensor.py             # Sensor platform
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Credits

- [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) – Core Bluetooth SIG parsing library
- [Home Assistant](https://www.home-assistant.io/) – Home automation platform
- [Bluetooth SIG](https://www.bluetooth.com/) – For Bluetooth specifications and GATT standards

## Support

- [Issues](https://github.com/RonanB96/ha-bluetooth-sig/issues) – Report bugs or request features
- [Discussions](https://github.com/RonanB96/ha-bluetooth-sig/discussions) – Ask questions or share ideas
