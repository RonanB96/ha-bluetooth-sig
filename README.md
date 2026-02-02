# Bluetooth SIG Devices for Home Assistant

A Home Assistant custom integration that automatically creates sensors from Bluetooth devices using the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library.

## Features

- **Automatic Device Discovery**: Automatically discovers and creates entities for Bluetooth devices advertising data
- **Dynamic Sensor Creation**: Creates sensors based on advertising data interpretation
- **Vendor-Specific Support**: Uses bluetooth-sig-python's interpreter registry for vendor-specific data formats (BTHome, Xiaomi, etc.)
- **Standard GATT Characteristics**: Parses standard Bluetooth SIG GATT characteristics when available
- **Passive Scanning**: Uses Home Assistant's passive Bluetooth scanning for low overhead
- **No Configuration Required**: Single config entry automatically manages all discovered devices

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/RonanB96/ha-bluetooth-sig`
6. Select category: "Integration"
7. Click "Add"
8. Find "Bluetooth SIG Devices" in the integration list and install it
9. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `custom_components/bluetooth_sig_devices` directory to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Search for "Bluetooth SIG Devices"
4. Click to add the integration
5. The integration will automatically discover and create entities for Bluetooth devices

## How It Works

### Architecture

The integration uses a multi-layered approach:

1. **Device Adapter**: Bridges Home Assistant's `BluetoothServiceInfoBleak` to bluetooth-sig-python's `AdvertisementData` format
2. **Coordinator**: Manages `Device` instances from bluetooth-sig-python, one per Bluetooth address
3. **Sensors**: Dynamically created based on:
   - Interpreted advertising data (vendor-specific formats like BTHome, Xiaomi, etc.)
   - Standard GATT service data
   - Signal strength (RSSI)

### Supported Devices

The integration supports any Bluetooth device that:
- Advertises data in standard Bluetooth SIG formats
- Has vendor-specific advertising interpreters in bluetooth-sig-python
- Provides standard GATT service data in advertisements

Supported vendor formats include:
- BTHome
- Xiaomi (via bluetooth-sig-python interpreters)
- Any vendor with registered interpreters in the library

### Entity Creation

Entities are created automatically based on:

1. **Interpreted Data**: If a device's advertising data is recognized by a vendor interpreter, sensors are created for each field in the interpreted data
2. **Service Data**: Standard GATT characteristics in service data are parsed and create sensors
3. **RSSI**: Signal strength sensor (disabled by default)

### Example

For a BTHome temperature sensor, the integration might create:
- `sensor.bthome_device_temperature` - Temperature reading
- `sensor.bthome_device_humidity` - Humidity reading
- `sensor.bthome_device_battery` - Battery level
- `sensor.bthome_device_signal_strength` - RSSI (disabled by default)

## Future Enhancements

- **GATT Polling**: Active connection support for reading GATT characteristics (currently passive only)
- **Binary Sensors**: Support for binary sensor entities
- **Events**: Support for button press and other event-based entities
- **Configuration Options**: Per-device configuration (bind keys, polling intervals, etc.)
- **Device Customization**: UI for enabling/disabling specific entities per device

## Troubleshooting

### No devices discovered

1. Ensure Bluetooth is enabled in Home Assistant
2. Check that your Bluetooth adapter is working
3. Verify devices are advertising (check with a Bluetooth scanner app)
4. Check Home Assistant logs for errors

### Missing entities

1. Check if the device's advertising format is supported
2. Enable debug logging to see what data is being received
3. Check if RSSI sensor is disabled (it's disabled by default)

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.bluetooth_sig_devices: debug
    bluetooth_sig: debug
```

## Development

### Requirements

- Home Assistant 2024.1.0 or newer
- bluetooth-sig-python
- Python 3.14 or newer

### Project Structure

```
custom_components/bluetooth_sig_devices/
├── __init__.py           # Integration setup
├── config_flow.py        # Configuration flow
├── const.py              # Constants
├── coordinator.py        # Data coordinator
├── device_adapter.py     # HA ↔ bluetooth-sig-python adapter
├── manifest.json         # Integration manifest
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

- [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) - Core Bluetooth SIG library
- [Home Assistant](https://www.home-assistant.io/) - Home automation platform
- Bluetooth SIG - For Bluetooth specifications and standards

## Support

- [Issues](https://github.com/RonanB96/ha-bluetooth-sig/issues) - Report bugs or request features
- [Discussions](https://github.com/RonanB96/ha-bluetooth-sig/discussions) - Ask questions or share ideas
- [Home Assistant Community](https://community.home-assistant.io/) - General Home Assistant help
