# Getting Started

This tutorial walks you through installing and setting up the Bluetooth SIG Devices integration from scratch.

## Prerequisites

Before you begin, make sure you have:

- A working Home Assistant installation (version **2026.1.0** or later)
- A Bluetooth adapter connected to your Home Assistant host — this can be:
  - A built-in Bluetooth adapter
  - A USB Bluetooth dongle
  - An [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
- At least one Bluetooth device that broadcasts standard SIG GATT service data (e.g., a heart rate monitor, environment sensor, or battery-reporting device)

> **Tip:** You can check whether Bluetooth is working in Home Assistant under **Settings → Devices & Services → Bluetooth**. You should see your adapter listed and scanning.

## Step 1: Install the integration

### Option A: Via HACS (recommended)

1. Open **HACS** in your Home Assistant sidebar
2. Go to **Integrations**
3. Select the three-dot menu (⋮) in the top right and choose **Custom repositories**
4. Enter the repository URL: `https://github.com/RonanB96/ha-bluetooth-sig`
5. Set the category to **Integration** and select **Add**
6. Search for **Bluetooth SIG Devices** in the HACS integration list
7. Select **Download** and confirm
8. **Restart Home Assistant** (Settings → System → Restart)

### Option B: Manual installation

1. Download the latest release from the [GitHub releases page](https://github.com/RonanB96/ha-bluetooth-sig/releases)
2. Copy the `custom_components/bluetooth_sig_devices` folder into your Home Assistant `config/custom_components/` directory
3. **Restart Home Assistant**

## Step 2: Add the integration

1. Go to **Settings → Devices & Services**
2. Select **Add Integration** (bottom right)
3. Search for **Bluetooth SIG Devices**
4. Select it and confirm the setup

This creates the **hub entry** — a single integration instance that scans for compatible Bluetooth devices. No device-specific configuration is needed at this stage.

## Step 3: Discover and confirm devices

Once the hub is running, the integration listens for Bluetooth advertisements. When it detects a compatible device:

1. A **discovery notification** appears under **Settings → Devices & Services → Discovered**
2. The notification shows the device name and which characteristics were detected
3. Select **Configure** to review the device
4. Select **Submit** to confirm and add the device

After confirmation, sensor entities are created automatically based on the characteristics the device advertises.

> **Note:** Only devices broadcasting **standard Bluetooth SIG GATT service data** are discovered. Devices using proprietary protocols will not appear — see [What this integration does NOT support](../index.md#what-this-integration-does-not-support).

## Step 4: View your entities

1. Go to **Settings → Devices & Services**
2. Find **Bluetooth SIG Devices** in your integrations list
3. Select the device you confirmed
4. You will see sensor entities for each detected characteristic (e.g., Temperature, Humidity, Battery Level, Heart Rate)

Entity names follow the pattern: `sensor.<device_name>_<characteristic_name>`

For example, a heart rate monitor might create:
- `sensor.heart_rate_monitor_heart_rate` — Heart rate in BPM
- `sensor.heart_rate_monitor_body_sensor_location` — Where the sensor is worn
- `sensor.heart_rate_monitor_battery_level` — Battery percentage

## What happens next

- **Passive updates:** Sensor values update automatically each time the device broadcasts an advertisement — no polling needed.
- **Active polling (connectable devices):** If the integration detects readable data during device probing, it will also periodically connect to the device and read those values (known as GATT polling). The default poll interval is 5 minutes.
- **New devices:** The integration continues scanning in the background. New compatible devices will appear in the Discovered section as they are detected.

## Next steps

- [Configure the poll interval](../how-to/configure-poll-interval.md) for GATT-connected devices
- [Enable debug logging](../how-to/enable-debug-logging.md) if devices are not appearing
- [Understand how discovery works](../explanation/discovery.md) for more detail on device detection
