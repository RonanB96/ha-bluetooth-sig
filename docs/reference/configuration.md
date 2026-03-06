# Configuration

## How the integration is set up

The integration uses two types of entry:

| Entry      | Created when                    | Purpose                                          |
| ---------- | ------------------------------- | ------------------------------------------------ |
| **Hub**    | You add the integration         | Runs the Bluetooth scanner and device discovery  |
| **Device** | You confirm a discovered device | Manages sensor entities for that specific device |

The hub entry is always present and is where you configure global settings. Device entries are created automatically as you confirm discovered devices.

## Options

Options are available only on the **hub entry** (not on individual device entries).

| Option             | Key             | Type              | Default | Range     |
| ------------------ | --------------- | ----------------- | ------- | --------- |
| GATT poll interval | `poll_interval` | Integer (seconds) | 300     | 30–86,400 |

The poll interval controls how often the integration connects to GATT-capable devices to read characteristic values. It applies globally to all connectable devices.

## Constraints

| Constraint                             | Value                          |
| -------------------------------------- | ------------------------------ |
| Minimum Home Assistant version         | 2026.1.0                       |
| Bluetooth scanning mode                | Passive                        |
| Maximum concurrent GATT connections    | 2                              |
| Maximum tracked devices                | 2,048 (seen), 4,096 (rejected) |
| Stale device timeout                   | 1 hour                         |
| Maximum GATT probe attempts per device | 3                              |

## IoT class

`local_push` — the integration receives data locally via Bluetooth advertisements pushed by devices. No cloud connectivity is used.

## Dependencies

| Package                              | Purpose                                                                         |
| ------------------------------------ | ------------------------------------------------------------------------------- |
| `bluetooth-sig` (≥0.2.0)             | GATT characteristic parsing, registry lookups, manufacturer data interpretation |
| `bleak-retry-connector` (≥3.0.0)     | Resilient BLE GATT connections with automatic retries                           |
| `homeassistant.components.bluetooth` | Home Assistant's Bluetooth scanner and callback infrastructure                  |
