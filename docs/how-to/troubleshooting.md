# Troubleshooting

Common problems and their solutions.

## Device not discovered

**The device does not appear in the Discovered section.**

| Cause | Solution |
|---|---|
| Bluetooth adapter not working | Check **Settings → Devices & Services → Bluetooth** — your adapter should be listed and scanning |
| Device uses a proprietary protocol | This integration only supports **standard SIG GATT service data**. Devices using other protocols need their own integrations — see [unsupported protocols](../index.md#what-this-integration-does-not-support) |
| Device uses a rotating address | Devices with Resolvable Private Addresses (RPA) or Non-Resolvable Private Addresses (NRPA) are filtered out because they change too frequently to track. Check debug logs for "Filtered ephemeral address" messages |
| Device is out of range | Move the device closer to the Bluetooth adapter or add an [ESPHome BLE proxy](https://esphome.io/components/bluetooth_proxy.html) to extend coverage |
| Device was previously rejected | If the integration probed a device and found no parseable data, it will not retry. Restart Home Assistant to clear the rejection cache |
| Hub entry not set up | The integration requires the hub entry to be active. Check that **Bluetooth SIG Devices** appears as an integration (not just discovered devices) |

## Entities not updating

**Entities exist but show stale or unavailable values.**

| Cause | Solution |
|---|---|
| Device moved out of range | Availability is tied to receiving advertisements. If the device stops broadcasting, entities become unavailable after approximately 10 minutes |
| Advertisement interval is long | Some devices advertise infrequently (e.g., every 60 seconds). Values will update at the device's broadcast rate |
| GATT poll interval too high | If entities rely on GATT reads, check the [poll interval configuration](configure-poll-interval.md). The default is 5 minutes |

## GATT connection failures

**Debug logs show connection errors when polling devices.**

| Cause | Solution |
|---|---|
| Device not connectable | Some devices only broadcast advertisements and do not accept connections. GATT polling will not work for these devices |
| Radio contention | The integration limits concurrent BLE connections to 2. If other integrations are also connecting to BLE devices, contention may cause timeouts. Increase the poll interval to reduce connection frequency |
| ESPHome proxy limitations | Some ESPHome firmware versions have connection limits. Check that your proxy firmware is up to date |
| Adapter busy | A single Bluetooth adapter can handle a limited number of concurrent connections. Consider adding additional adapters or ESPHome proxies |

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
