# Known Limitations

This page documents the known limitations and constraints of the Bluetooth SIG Devices integration.

## Protocol coverage

**Only standard Bluetooth SIG protocols are supported.**

The integration parses characteristics and service data defined in the official Bluetooth SIG GATT specification. Devices using proprietary data formats — even if they look like BLE sensors — are not supported by this integration. These include:

- BTHome devices (use the BTHome integration)
- Xiaomi MiBeacon / BLE devices (use the Xiaomi BLE integration)
- Govee, Inkbird, Thermoplus, and other brand-specific formats (use their dedicated integrations)
- Custom firmware devices unless they expose standard SIG characteristics

If you are unsure whether a device uses SIG-standard protocols, check its Bluetooth service UUIDs. Standard SIG characteristics use the pattern `0000XXXX-0000-1000-8000-00805f9b34fb`.

## Read-only

The integration is **read-only**. It monitors and measures characteristics but cannot write to them. This means:

- Alert levels, settings, and configuration characteristics cannot be changed from Home Assistant
- Control Point characteristics (e.g., resetting energy counters, triggering measurements) have no corresponding entity
- Feature/capability characteristics are not exposed as entities

Support for writable characteristics is planned for a future release.

## Rotating Bluetooth addresses

Devices that use **Resolvable Private Addresses (RPA)** or **Non-Resolvable Private Addresses (NRPA)** are filtered out automatically. These are privacy-preserving addresses that rotate periodically to prevent tracking. Common examples:

- Recent Apple mobile devices and accessories when not bonded
- Some Android devices
- Some fitness trackers and smartwatches

If your device is using a rotating address, it will not appear in the Discovered section. There is currently no workaround; bonding the device to your Bluetooth adapter may cause it to use a stable address in some cases.

## GATT probe limits and failures

During device discovery, each candidate device is probed a maximum of 3 times (configurable). If all probes fail — due to the device being out of range, not accepting connections, or radio contention — the device is marked as unsupported for the current session and will not be probed again until Home Assistant restarts. This limit protects against wasting BLE adapter slots on fundamentally unsupported devices.

This limit **does not apply to devices that have already been confirmed by the user**. A device with an existing config entry is always retried if GATT probing has not yet produced a result — for example, if the device was out of range when Home Assistant started. Retries are throttled (default: once every 5 minutes) to avoid flooding the BLE adapter.

Probing is limited to 2 concurrent connections (configurable) to avoid overwhelming the Bluetooth radio. In environments with many BLE devices, probes may be queued and slow.

## GATT connection reliability

BLE connections are inherently less reliable than Wi-Fi or Zigbee:

- Radio contention with other Bluetooth devices (headphones, mice, keyboards) can cause connection failures
- ESPHome Bluetooth proxies have limited connection capacity — most support only a small number of simultaneous connections
- Some devices refuse connections when they are already communicating with another central device (e.g., a phone paired to a fitness tracker)

A failed GATT connection does not cause entities to become unavailable — the poll is skipped and retried at the next interval.

## Entity discovery timing

Entities are not created until the integration has received data from a device. For:

- **Broadcast-path characteristics** — entities appear on the first received advertisement after confirming the device
- **GATT-path characteristics** — entities appear after the first successful poll, which may take up to 5 minutes (the default poll interval) after confirmation

If you have just confirmed a device and see no entities, wait for the first poll cycle to complete.

## One integration instance

Only one hub entry is allowed per Home Assistant instance. The integration is designed to run a single coordinator that handles all device discovery and tracking. Multiple hub entries are not supported.
