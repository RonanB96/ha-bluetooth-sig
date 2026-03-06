# Supported Characteristics

## How characteristics are supported

This integration does **not** maintain a hardcoded list of supported characteristics. Support is determined entirely at runtime by the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library.

A characteristic is supported when:

1. The device broadcasts **service data** with a UUID that the library's `CharacteristicRegistry` recognises, **or**
2. The device broadcasts **manufacturer data** that one of the library's interpreters can parse, **or**
3. A **GATT probe** connects to the device and discovers readable characteristics that the library can parse

## Common examples

These are examples of standard SIG GATT characteristics that the library currently supports. This list is not exhaustive — check the library documentation for the full registry.

| UUID | Characteristic | Typical unit |
|---|---|---|
| 0x2A19 | Battery Level | % |
| 0x2A6E | Temperature | °C |
| 0x2A6F | Humidity | % |
| 0x2A37 | Heart Rate Measurement | bpm |
| 0x2A35 | Blood Pressure Measurement | mmHg |
| 0x2A38 | Body Sensor Location | (enum name) |
| 0x2A5B | CSC Measurement | (multi-field struct) |

## Checking support for a specific characteristic

To check whether a particular UUID is supported:

1. Consult the [bluetooth-sig-python documentation](https://ronanb96.github.io/bluetooth-sig-python/) for the current characteristic registry
2. If the UUID is listed, any device advertising it will be automatically discovered by this integration

## Adding support for new characteristics

New characteristics are added in the upstream `bluetooth-sig-python` library — not in this integration. Once the library adds a parser for a new UUID, this integration picks it up automatically on the next library update.

See the [bluetooth-sig-python contributing guide](https://github.com/RonanB96/bluetooth-sig-python) for details on adding new parsers.

## Excluded services

The following standard BLE services are excluded from discovery because they provide protocol infrastructure rather than user-facing data:

- **GAP** (Generic Access Profile) — basic device identity
- **GATT** (Generic Attribute Profile) — protocol infrastructure
