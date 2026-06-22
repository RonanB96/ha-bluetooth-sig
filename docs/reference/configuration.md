# Configuration

## How the integration is set up

The integration uses two types of entry:

| Entry      | Created when                    | Purpose                                          |
| ---------- | ------------------------------- | ------------------------------------------------ |
| **Hub**    | You add the integration         | Runs the Bluetooth scanner and device discovery  |
| **Device** | You confirm a discovered device | Manages sensor entities for that specific device |

The hub entry is always present and is where you configure global settings. Device entries are created automatically as you confirm discovered devices.

## Options

### Hub options

These are configured on the **hub entry** (the main integration entry, not a specific device). They apply globally.

| Option                     | Key                          | Type              | Default | Range      |
| -------------------------- | ---------------------------- | ----------------- | ------- | ---------- |
| GATT poll interval         | `poll_interval`              | Integer (seconds) | 300     | 30–86,400  |
| Max concurrent connections | `max_concurrent_connections` | Integer           | 2       | 1–5        |
| Connection timeout         | `connection_timeout`         | Integer (seconds) | 30      | 10–120     |
| Max probe retries          | `max_probe_retries`          | Integer           | 3       | 1–10       |
| Stale device timeout       | `stale_device_timeout`       | Integer (seconds) | 3,600   | 300–86,400 |

- **GATT poll interval** — how often the integration connects to GATT-capable devices to read characteristic values. Can be overridden per device.
- **Max concurrent connections** — maximum simultaneous BLE connections for probing and polling. Lower values reduce radio contention; higher values speed up multi-device polling.
- **Connection timeout** — timeout for establishing a BLE connection. Increase if you have unreliable adapters or a congested BLE environment.
- **Max probe retries** — maximum attempts to probe a device's GATT services before giving up.
- **Stale device timeout** — time after which unseen devices are cleaned up from the discovery tracker. This only affects devices that have **not** been confirmed — your confirmed devices and their entities are never removed by this timeout.

### Per-device options

These are configured on individual **device entries**. They allow you to customise behaviour for specific devices.

| Option                  | Key                     | Type              | Default         | Description                                                              |
| ----------------------- | ----------------------- | ----------------- | --------------- | ------------------------------------------------------------------------ |
| Enable GATT connections | `gatt_enabled`          | Boolean           | On              | When disabled, only passive advertisement data is used for this device   |
| Poll interval override  | `device_poll_interval`  | Integer (seconds) | 0 (hub default) | Set to 0 to use the global hub default, or 30–86,400 to override        |

See [Configure device-specific options](../how-to/configure-device-options.md) for step-by-step instructions.

## Constraints

| Constraint                             | Value                                |
| -------------------------------------- | ------------------------------------ |
| Minimum Home Assistant version         | 2026.1.0 (see note below)            |
| Bluetooth scanning mode                | Passive                              |
| Maximum concurrent GATT connections    | Configurable (default 2, range 1–5)  |
| Maximum tracked devices                | 2,048 (seen), 4,096 (rejected)       |
| Stale device timeout                   | Configurable (default 1 hour)        |
| Maximum GATT probe attempts per device | Configurable (default 3, range 1–10) |

### Minimum Home Assistant version

**2026.1.0** is required. This is declared in `manifest.json`, `hacs.json`, and enforced by HACS at install time.

The integration targets the 2026.1+ Bluetooth processor APIs:

- `ActiveBluetoothProcessorCoordinator` with `needs_poll_method` / `poll_method` for GATT reads
- `PassiveBluetoothEntityKey` and passive processor entity restore
- Config entry `runtime_data` for hub/device coordinator sharing
- `after_dependencies: ["bluetooth_adapters"]` so remote BLE proxies are ready before setup

Development and CI use Python 3.12+ (`pyproject.toml`), matching Home Assistant 2026.1.

## IoT class

`local_push` — the integration receives data locally via Bluetooth advertisements pushed by devices. No cloud connectivity is used.
