# Enable Debug Logging

Debug logging helps diagnose why devices are not being discovered or why entities are not updating.

## Enable

1. Go to **Settings → Devices & Services**
2. Find **Bluetooth SIG Devices**
3. Select **Enable debug logging** from the three-dot menu (⋮)

Alternatively, add the following to your `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.bluetooth_sig_devices: debug
    bluetooth_sig: debug
```

## What to look for

With debug logging enabled, the integration logs messages at each stage of its operation. Look for messages related to your issue:

| Problem                                     | What to search for in logs                                                             |
| ------------------------------------------- | -------------------------------------------------------------------------------------- |
| Device not appearing in Discovered          | Messages about the device's address — look for "discovery", "supported", or "filtered" |
| Device found but no entities created        | Messages about characteristic parsing or probe results for the device                  |
| Entities not updating / showing unavailable | Messages about connection attempts, polling, or timeouts for the device                |
| Connection errors                           | Messages about GATT connections, retries, or adapter errors                            |

Search your logs using the device's Bluetooth address (e.g., `AA:BB:CC:DD:EE:FF`) to filter to the relevant device.

## Disable

Remove the `logs:` lines from `configuration.yaml` and restart Home Assistant, or use the **Disable debug logging** option from the integration's menu.

Leaving debug logging enabled long-term increases log volume and disk usage.
