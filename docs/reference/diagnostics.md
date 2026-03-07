# Diagnostics

Diagnostic data helps when reporting issues or understanding what the integration is doing. If you open a GitHub issue, attaching your diagnostics file helps maintainers diagnose problems without needing access to your system.

## Accessing diagnostics

1. Go to **Settings → Devices & Services**
2. Find **Bluetooth SIG Devices**
3. Select the three-dot menu (⋮) on the hub entry
4. Choose **Download diagnostics**

## Diagnostic data structure

### `options`

The current configuration options for the hub entry (e.g., `poll_interval`).

### `device_statistics`

Aggregate counters for the integration's discovery and tracking state:

| Field                           | Description                                                  |
| ------------------------------- | ------------------------------------------------------------ |
| `tracked_devices`               | Devices with active processor coordinators                   |
| `active_processor_coordinators` | Number of per-device processors currently running            |
| `gatt_probed_devices`           | Devices that have been successfully GATT-probed              |
| `pending_probes`                | GATT probes currently in progress                            |
| `seen_devices`                  | Total unique addresses observed                              |
| `rejected_devices`              | Addresses evaluated with no parseable SIG data               |
| `discovery_triggered`           | Discovery flows that have been fired for user confirmation   |
| `filtered_ephemeral_count`      | Advertisements filtered due to rotating addresses (RPA/NRPA) |

### `gatt_probe_results`

Per-device GATT probe outcomes, keyed by MAC address:

| Field                       | Description                                      |
| --------------------------- | ------------------------------------------------ |
| `parseable_characteristics` | Number of characteristics the library can parse  |
| `has_support`               | Whether any parseable characteristics were found |
| `probe_failures`            | Number of failed probe attempts for this device  |

### `probe_failures`

Per-device failure counts for GATT probe attempts. After 3 failures, the device will not be probed again.

### `known_characteristics`

Per-device list of discovered characteristic names (from both advertisements and GATT probes). Useful for understanding what data a device is exposing.
