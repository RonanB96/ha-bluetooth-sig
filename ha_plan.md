# Implementation Guide: HA Bluetooth SIG Devices Integration

## Core Concept

**Fully automatic. Zero maps. Zero per-characteristic code.**

The `bluetooth-sig-python` library provides **everything** needed for HA entities:

| What HA Needs | Library Provides |
|---------------|------------------|
| Entity name | `char.name` |
| Unit of measurement | `char.unit` |
| Parsed value | `char.parse_value(raw)` |

The integration simply passes library data to HA. When the library adds new characteristics, they work automatically.

**No hardcoded maps. No per-characteristic code. Fully automatic.**

---

## File Structure

```
ha-bluetooth-sig-devices/
├── custom_components/
│   └── bluetooth_sig_devices/
│       ├── __init__.py
│       ├── manifest.json
│       ├── const.py              # Just DOMAIN, nothing else
│       ├── config_flow.py
│       ├── coordinator.py
│       └── sensor.py
└── hacs.json
```

---

## Implementation

The integration must follow HA's Bluetooth integration guidelines. Refer to the [HA Bluetooth documentation](https://developers.home-assistant.io/docs/bluetooth/) for details on creating Bluetooth integrations.

### const.py

Define the integration's DOMAIN constant.

### manifest.json

Standard HA integration manifest with dependencies on the `bluetooth` component and requirements including `bluetooth-sig`.

### config_flow.py

Implement a config flow for device discovery and setup, following HA's config flow patterns for Bluetooth devices.

### coordinator.py

Create a data update coordinator that handles both advertisement parsing and GATT polling. For advertisement-based devices, parse the advertisement payload using the library's advertisement parsers. For GATT devices, poll BLE devices for characteristic data, using the library's CharacteristicRegistry to identify and parse supported characteristics.

### sensor.py

Define sensor entities that represent the parsed data from either advertisements or GATT characteristics, using the coordinator's data to populate entity states and attributes.

---

## How It Works

The integration supports two approaches for SIG standard devices:

1. **Advertisement Parsing**: For devices that broadcast SIG standard advertisement data, parse the advertisement payload to extract sensor values directly from the broadcast data.

2. **GATT Characteristic Reading**: For connectable GATT devices, scan for supported services and characteristics, then read and parse the characteristic values.

BLE devices are discovered via HA owned bluetooth system. Depending on the device type, the integration either parses advertisement data or queries the CharacteristicRegistry for parser instances. If supported, it parses the raw bytes and creates HA sensor entities with metadata (name, unit) provided by the library.

**No mapping tables. Library → HA directly.**

---

## Why This Scales

| Scenario | Old Approach (Maps) | This Approach |
|----------|---------------------|---------------|
| Library adds characteristic | Edit DEVICE_CLASS_MAP, UNIT_MAP | Nothing - works automatically |
| 200+ characteristics | 200+ map entries | 0 map entries |
| Maintenance | Grows with library | Constant (zero) |
| Unit for "Temperature" | Hardcode "°C" | `char.unit` returns "°C" |

---

## Summary

| What | Source |
|------|--------|
| Entity name | `char.name` (library) |
| Unit | `char.unit` (library) |
| Value | `char.parse_value(raw)` (library) |
| Primary field | `char.spec.primary_field` (library) |

**Zero hardcoded maps. Zero per-characteristic code. Fully automatic.**
