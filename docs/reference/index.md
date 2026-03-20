# Reference

Technical details for the Bluetooth SIG Devices integration.

- [Entities](entities.md) — sensor entity types, naming, device classes, and state classes
- [Configuration](configuration.md) — config entry structure, options, and constraints
- [Supported Characteristics](supported-characteristics.md) — how characteristics are supported and how to check coverage
- [Diagnostics](diagnostics.md) — diagnostic data structure and how to interpret it

## Supported functions

| Feature | Detail |
|---------|--------|
| **Passive BLE scanning** | Listens for advertisements continuously using Home Assistant's Bluetooth component — no connections needed for broadcast-path devices |
| **Active GATT polling** | Periodically connects to read characteristics not available in advertisements; configurable interval (default 5 min) |
| **Automatic entity creation** | Sensor entities created for every parseable characteristic, with correct units, device classes, and state classes resolved from GATT specs |
| **Multi-field expansion** | Complex characteristics (e.g., Heart Rate Measurement) are expanded into one entity per field |
| **Role-based filtering** | Control/Feature characteristics are excluded; Status/Info characteristics become disabled-by-default diagnostic entities |
| **Ephemeral address filtering** | RPA/NRPA rotating addresses are automatically filtered to prevent orphaned entities |
| **Device options** | Per-device GATT toggle and poll interval override |
| **Hub options** | Global poll interval, concurrency, connection timeout, probe retries, and stale device cleanup |
| **Stale device cleanup** | Confirmed devices can be removed; unseen unconfirmed devices are cleaned up after a configurable timeout |
| **Diagnostics** | Downloadable diagnostic snapshot for all tracked devices, probe results, and rejection reasons |
| **Dynamic device support** | New devices can be discovered and added without restarting HA or changing configuration |
