# Bluetooth SIG Devices for Home Assistant

A Home Assistant custom integration that automatically creates sensors from Bluetooth devices advertising **standard Bluetooth SIG GATT characteristics** using the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library.

## Features

- **Standard GATT Characteristics**: Parses official Bluetooth SIG GATT characteristics (Battery Level, Temperature, Heart Rate, Humidity, etc.)
- **Automatic Device Discovery**: Automatically discovers devices advertising standard service data
- **Dynamic Sensor Creation**: Creates sensors based on the GATT characteristics found in advertisements
- **Passive Scanning**: Uses Home Assistant's passive Bluetooth scanning for low overhead
- **No Configuration Required**: Single config entry automatically manages all discovered devices

## What This Integration Does

This integration parses **standard Bluetooth SIG service data** advertised by devices. It uses the official GATT characteristic specifications to interpret data.

### Supported Characteristics

Any device advertising standard GATT service data UUIDs, including:

- **Battery Level** (0x2A19)
- **Temperature** (0x2A6E)
- **Humidity** (0x2A6F)
- **Heart Rate Measurement** (0x2A37)
- **Blood Pressure** (0x2A35)
- **Body Sensor Location** (0x2A38)
- **CSC Measurement** (Cycling Speed and Cadence)
- And many more standard GATT characteristics

### What This Integration Does NOT Support

- **BTHome** – Use the dedicated [BTHome integration](https://www.home-assistant.io/integrations/bthome/)
- **Xiaomi sensors** – Use dedicated Xiaomi integrations
- **Other vendor-specific protocols** – These use proprietary data formats

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
5. The integration will automatically discover and create entities for compatible Bluetooth devices

## Removal

To remove the integration:

1. Go to Settings → Devices & Services
2. Find "Bluetooth SIG Devices" in your integrations list
3. Click on the integration
4. Click the three-dot menu (⋮) in the top right
5. Select "Delete"
6. Confirm the deletion

This will remove all entities and devices created by this integration.

## How It Works

### Architecture

The integration uses a multi-layered approach:

1. **Device Adapter**: Bridges Home Assistant's `BluetoothServiceInfoBleak` to bluetooth-sig-python's `AdvertisementData` format
2. **Coordinator**: Manages device instances, one per Bluetooth address
3. **Sensors**: Dynamically created based on:
   - Standard GATT service data in advertisements
   - Signal strength (RSSI)

### Entity Creation

Entities are created automatically when:

1. A device advertises service data with a recognised GATT characteristic UUID
2. The bluetooth-sig-python library can parse the characteristic data
3. The parsed value is suitable for a sensor entity

### Example

For a heart rate monitor advertising standard GATT data:
- `sensor.heart_rate_monitor_heart_rate` – Heart rate in BPM
- `sensor.heart_rate_monitor_body_sensor_location` – Where the sensor is worn
- `sensor.heart_rate_monitor_battery_level` – Battery percentage

## Troubleshooting

### No devices discovered

1. Ensure Bluetooth is enabled in Home Assistant
2. Check that your Bluetooth adapter is working
3. Verify devices are advertising **standard GATT service data** (not proprietary formats)
4. Check Home Assistant logs for errors

### Device not creating entities

1. The device may use a proprietary protocol (not standard GATT)
2. Enable debug logging to see what data is being received
3. Check if the characteristic UUID is supported by bluetooth-sig-python

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
