# Data Paths

This page explains how Bluetooth data from your devices becomes sensor state in Home Assistant. The integration uses two independent paths that work in parallel.

```mermaid
flowchart LR
  subgraph device["BLE Device"]
    radio(["📡 Radio"])
  end

  subgraph passive["Path 1 — Broadcast"]
    bcast["Service data<br>Manufacturer data"]
  end

  subgraph active["Path 2 — Connected"]
    poll["Periodic read<br><i>every 5 min</i>"]
  end

  radio -->|advertisement| bcast
  radio -->|BLE connection| poll

  subgraph integration["Integration"]
    parse["Parse &<br>Create entities"]
  end

  bcast --> parse
  poll --> parse

  parse --> ha(["🏠 Home Assistant<br>Sensor entities"])

  style passive fill:#e3f2fd,color:#000
  style active fill:#fff3e0,color:#000
```

## Path 1: Broadcast data (passive)

Most Bluetooth devices periodically broadcast small packets of data (advertisements). The integration reads these broadcasts and extracts:

- **Service data** — standard Bluetooth SIG characteristics, identified by UUID (e.g., temperature, humidity, battery level)
- **Manufacturer data** — vendor-specific payloads in recognised formats

This path is **automatic** — sensor values update every time the device broadcasts, with no connection needed. Update frequency depends on how often the device advertises (typically every 1–10 seconds).

## Path 2: Connected reads (active)

Some characteristics are only available by connecting to the device and reading them directly. If the integration detected readable characteristics during device discovery, it will periodically:

1. Connect to the device
2. Read all known characteristics
3. Update the corresponding sensor entities
4. Disconnect

The default poll interval is **5 minutes** — see [Configure the GATT poll interval](../how-to/configure-poll-interval.md) to adjust it.

To minimise connection overhead, the integration reads characteristics during the initial device probe and caches the result. The first poll returns this cached data without connecting again.

## How the paths combine

Broadcast data and connected reads typically expose different characteristics (e.g., a device might broadcast temperature but require a connection to read battery level). The integration combines both into a single unified set of sensor entities for each device.

If both paths happen to provide the same characteristic, the most recent value is used.

## How entities are created

Once data arrives from either path, the integration creates sensor entities following these rules:

```mermaid
flowchart TD
  data(["Parsed<br>characteristic"]) --> type{"Value<br>type?"}
  type -->|Single value| one["One sensor entity"]
  type -->|Multi-field struct| expand["One entity<br>per field"]

  one --> role{"Characteristic<br>role?"}
  expand --> role

  role -->|Measurement / Unknown| normal["✅ Normal entity<br>enabled by default"]
  role -->|Status / Info / Control / Feature| diag["🔧 Diagnostic entity<br>disabled by default"]

  normal --> meta["Unit + device class<br>assigned from spec"]
  diag --> meta

  style normal fill:#4caf50,color:#fff
  style diag fill:#ff9800,color:#fff
```

1. **Simple values** (a single number or string) become one sensor entity each
2. **Multi-field values** (e.g., Heart Rate Measurement with heart rate + energy expended) are expanded into one entity per field
3. **Units and device classes** are assigned automatically based on the Bluetooth SIG specification
4. **Entity visibility** depends on the characteristic's role — see [Characteristic Roles](roles.md) for details

## Entity availability and staleness

### Broadcast path

Entities updated via broadcast data become **unavailable** if no advertisement is received from the device for approximately 15 minutes. This window is managed by Home Assistant's Bluetooth component, not by this integration directly.

When a device comes back in range, it starts advertising again and entities return to **available** on the next received advertisement.

### Connected path

GATT-polled entities follow the same availability logic. If the device cannot be reached (out of range, busy, or the connection timed out), the poll is skipped and the entity retains its last known value. It becomes unavailable if the broadcast path also stops receiving advertisements within the 15-minute window.

### Why values might not update

| Condition                       | Effect                                                            |
| ------------------------------- | ----------------------------------------------------------------- |
| Device out of range             | Entity becomes unavailable after ~15 min                          |
| Device broadcasts infrequently  | Values update slowly (normal)                                     |
| GATT poll interval is long      | Values from connected reads update slowly (adjust in hub options) |
| GATT connection failed          | Poll is skipped; next attempt at next poll interval               |
| Characteristic not in broadcast | Value only updates during GATT polls                              |
