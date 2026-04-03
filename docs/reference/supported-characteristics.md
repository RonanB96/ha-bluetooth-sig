# Supported Characteristics

## How characteristics are supported

This integration does **not** maintain a hardcoded list of supported characteristics. Support is determined entirely at runtime by the [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library.

The library handles all Bluetooth data parsing — characteristic definitions, binary decoding, unit resolution, and role classification. This integration handles the Home Assistant side — turning the library's parsed output into sensor entities with correct device classes, state classes, and entity categories.

A characteristic is supported when:

1. The device broadcasts **service data** with a UUID that the library's `CharacteristicRegistry` recognises, **or**
2. The device broadcasts **manufacturer data** that one of the library's interpreters can parse, **or**
3. A **GATT probe** connects to the device and discovers readable characteristics that the library can parse

## Common examples

The library supports common SIG GATT characteristics such as Battery Level, Temperature, Humidity, Heart Rate Measurement, Blood Pressure Measurement, Body Sensor Location, and CSC Measurement, among many others.

For the full list of supported characteristics and their UUIDs, see the [bluetooth-sig-python characteristic reference](https://ronanb96.github.io/bluetooth-sig-python/reference/characteristics.html).

## Checking support for a specific characteristic

To check whether a particular UUID is supported:

1. Consult the [bluetooth-sig-python characteristic reference](https://ronanb96.github.io/bluetooth-sig-python/reference/characteristics.html) for the current characteristic registry
2. If the UUID is listed, any device advertising it will be automatically discovered by this integration

## Adding support for new characteristics

New characteristics are added in the upstream [bluetooth-sig-python](https://github.com/RonanB96/bluetooth-sig-python) library — not in this integration. The library defines how each characteristic's raw bytes are parsed, what unit it uses, and what role it has. Once the library adds a parser for a new UUID, this integration picks it up automatically on the next library update.

See the [bluetooth-sig-python guide on adding characteristics](https://ronanb96.github.io/bluetooth-sig-python/how-to/adding-characteristics.html) for details on adding new parsers.

> **Tip:** If a characteristic is being parsed but the entity has the wrong unit, device class, or role, that is a library issue. If the entity is not being created at all despite the characteristic being parsed, that is an integration issue. See [How it works](../index.md#how-it-works) for more on this separation.

## Devices using standard UUIDs with non-standard data

It is not uncommon for manufacturers to register standard Bluetooth SIG UUIDs for their characteristics but implement the data format differently from the official specification. The integration has no way to detect this — it sees a recognised UUID and attempts to parse the data according to the SIG specification.

### What happens

- **Completely different data format** — if the byte layout differs from the specification, parsing will fail. The integration logs a warning and **skips the entity entirely** — no incorrect data is shown. The device will still be discovered (the UUID is recognised), but the affected characteristic will not produce a sensor entity.
- **Extended data** — if the manufacturer adds proprietary fields after the standard data, the standard fields are parsed normally and extra bytes are ignored. This is harmless.

### What to do if your device is affected

If a device is discovered but produces no entities, or entities show `unavailable`:

1. [Enable debug logging](../how-to/enable-debug-logging.md) and look for warning messages mentioning "Could not parse" for the device's address
2. Check the manufacturer's documentation to confirm whether they follow the SIG specification for that UUID
3. If they do not, this integration cannot support that characteristic — the device needs a dedicated integration that understands its proprietary format
4. [Open an issue](https://github.com/RonanB96/ha-bluetooth-sig/issues) if you are unsure — include your debug logs and the device model

## Excluded services

The following standard BLE services are excluded from discovery because they provide protocol infrastructure rather than user-facing data:

- **GAP** (Generic Access Profile) — basic device identity
- **GATT** (Generic Attribute Profile) — protocol infrastructure
