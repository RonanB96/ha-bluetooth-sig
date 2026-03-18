# Configure Device-Specific Options

Each confirmed device has its own options for GATT connection behaviour. This guide explains how to adjust them.

## When to use per-device options

- **Disable GATT** for a device that is non-connectable or causes connection errors — the integration will use only passive advertisement data
- **Override the poll interval** for a device that needs more frequent reads (e.g., a health sensor) or less frequent reads (e.g., a battery-powered environmental sensor you want to poll sparingly)

## Steps

1. Go to **Settings → Devices & Services**
2. Find **Bluetooth SIG Devices** in your integrations list
3. Select **Configure** on the **device entry** (the specific device, not the main hub entry)
4. Adjust the settings:
   - **Enable GATT connections** — toggle off to use advertisement data only
   - **Poll interval override (seconds)** — set to `0` to use the global hub default, or set a value (30–86,400) to override for this device only
5. Select **Submit**

Changes take effect immediately — no restart is required.

## How it relates to the global poll interval

The global poll interval (set on the hub entry) applies to all connectable devices by default. When you set a per-device poll interval override, that device uses its own interval instead of the global one.

| Device setting | Behaviour |
|----------------|-----------|
| Poll interval override = `0` | Uses the global hub poll interval |
| Poll interval override = `60` | Polls this device every 60 seconds, regardless of the global setting |

See [Configure the GATT poll interval](configure-poll-interval.md) for details on the global setting.

## Disabling GATT connections

When GATT connections are disabled for a device:

- The integration **stops** periodically connecting to read characteristics
- Only data received via passive Bluetooth advertisements is used
- Entities that depend on GATT-only characteristics will become unavailable
- This can help if a device causes connection errors or if you want to reduce radio usage

To re-enable GATT connections, follow the same steps above and toggle the setting back on.
