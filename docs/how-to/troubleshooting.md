# Troubleshooting

Common problems and their solutions.

## Device not discovered

**The device does not appear in the Discovered section.**

| Cause | Solution |
|---|---|
| Bluetooth adapter not working | Check **Settings → Devices & Services → Bluetooth** — your adapter should be listed and scanning |
| Device uses a proprietary protocol | This integration only supports **standard SIG GATT service data** and **recognised manufacturer data formats**. Devices using other protocols (BTHome, Xiaomi, etc.) need their own integrations — see [unsupported protocols](../index.md#what-this-integration-does-not-support) |
| Device uses a rotating address | Devices with Resolvable Private Addresses (RPA) or Non-Resolvable Private Addresses (NRPA) are filtered out because they change too frequently to track. Check debug logs for "Filtered ephemeral address" messages |
| Device is out of range | Move the device closer to the Bluetooth adapter or add an another adapter like a [ESPHome BLE proxy](https://esphome.io/components/bluetooth_proxy.html) to extend coverage |
| Device was previously rejected | If the integration probed a device and found no parseable data, it will not retry until the stale device timeout expires (default: 1 hour, [configurable](../reference/configuration.md#hub-options)). Restarting Home Assistant also clears the rejection cache |
| Hub entry not set up | The integration requires the hub entry to be active. Check that **Bluetooth SIG Devices** appears as an integration (not just discovered devices) |

## Entities not updating

**Entities exist but show stale or unavailable values.**

| Cause | Solution |
|---|---|
| Device moved out of range | Availability is tied to receiving advertisements. If the device stops broadcasting, entities become unavailable after approximately 15 minutes (the Home Assistant Bluetooth framework's stale advertisement timeout) |
| Advertisement interval is long | Some devices advertise infrequently (e.g., every 60 seconds). Values will update at the device's broadcast rate |
| GATT poll interval too high | If entities rely on GATT reads, check the [poll interval configuration](configure-poll-interval.md). The default is 5 minutes |

## GATT connection failures

**Debug logs show connection errors when polling devices.**

| Cause | Solution |
|---|---|
| Device not connectable | Some devices only broadcast advertisements and do not accept connections. GATT polling will not work for these devices |
| Radio contention | The integration limits concurrent BLE connections (default: 2, [configurable](../reference/configuration.md#hub-options)). If other integrations are also connecting to BLE devices, contention may cause timeouts. Increase the poll interval or the connection limit to reduce contention |
| ESPHome proxy limitations | Some ESPHome firmware versions have connection limits. Check that your proxy firmware is up to date |
| Adapter busy | A single Bluetooth adapter can handle a limited number of concurrent connections. Consider adding additional adapters or ESPHome proxies |

## Device confirmed but entities are slow to appear

**You confirmed a device in the Discovered section but not all expected sensor entities appeared immediately.**

| Cause | Solution |
|---|---|
| GATT probe has not completed yet | If the device was discovered via advertisement data, the GATT probe runs as a background task after discovery. Once the probe connects, it reads all characteristic values and caches them — entities appear as soon as the probe finishes. If the device is connectable and in range, this typically takes a few seconds |
| Device went out of range before probe | If the device moved out of range before the probe could run, GATT entities will appear the next time the device is in range and the probe succeeds |

> **Note:** If a confirmed device produces **zero** entities, that is a bug — please [report it](https://github.com/RonanB96/ha-bluetooth-sig/issues) with your debug logs.

## Entity shows unavailable immediately

**An entity is created but immediately shows as unavailable.**

| Cause | Solution |
|---|---|
| Device went out of range | The device may have moved or powered off between discovery and entity setup. Wait for it to come back into range — entities will recover automatically when the next advertisement is received |
| GATT probe failed | If the GATT probe could not connect to the device (e.g., device out of range, adapter busy), the integration retries up to the configured max probe retries (default: 3). After all retries are exhausted, no further probes are attempted until the stale device timeout clears the failure count (default: 1 hour) or Home Assistant is restarted. Check [GATT connection failures](#gatt-connection-failures) for causes |

## Diagnostic entities disabled

**Some entities appear in the entity registry but are disabled by default.**

This is intentional. Characteristics with a `STATUS` or `INFO` role are classified as **diagnostic entities** and are disabled by default in Home Assistant. To enable them:

1. Go to **Settings → Devices & Services → Entities**
2. Find the disabled entity
3. Select it and toggle **Enable** on

## Getting help

If you cannot resolve the issue:

1. [Enable debug logging](enable-debug-logging.md) and reproduce the problem
2. Check the [GitHub issues](https://github.com/RonanB96/ha-bluetooth-sig/issues) for known problems
3. Open a new issue with your debug logs and a description of the problem
