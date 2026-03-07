# Configure the GATT Poll Interval

The integration periodically connects to Bluetooth devices that support GATT characteristic reads. This guide explains how to adjust the polling frequency.

## When to change the poll interval

- **Decrease the interval** (e.g., 30–60 seconds) if you need near-real-time data from GATT-only characteristics that are not broadcast in advertisements.
- **Increase the interval** (e.g., 900–3600 seconds) to reduce BLE radio usage, extend device battery life, or avoid connection contention with other integrations.

The default is **300 seconds** (5 minutes). The allowed range is **30–86,400 seconds** (30 seconds to 24 hours).

## Steps

1. Go to **Settings → Devices & Services**
2. Find **Bluetooth SIG Devices** in your integrations list
3. Select **Configure** on the **hub entry** (the main integration entry, not a specific device)
4. Adjust the **Poll interval (seconds)** value
5. Select **Submit**

The change takes effect immediately — no restart is required.

> **Note:** The poll interval is a global setting that applies to all connectable devices managed by this integration. Per-device intervals are not currently supported.

## How polling works

- Polling only applies to devices where the integration has successfully probed GATT characteristics during discovery.
- Advertisement-only devices (non-connectable) are not affected by this setting — they update passively whenever they broadcast.
- The integration limits concurrent BLE connections to 2 to avoid radio contention.
