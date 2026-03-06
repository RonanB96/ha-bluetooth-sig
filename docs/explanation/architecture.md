# Architecture Overview

This page explains how the integration is structured and why certain design choices were made. It is intended for users who want to understand the overall approach — for developer-level details, see the [copilot-instructions.md](https://github.com/RonanB96/ha-bluetooth-sig/blob/main/.github/copilot-instructions.md) in the repository.

## How the integration is organised

The integration has one central component that coordinates everything:

```mermaid
block-beta
  columns 4
  coord["Coordinator"]:4
  scan["Scanning &<br>Discovery"]
  conn["Connection<br>Management"]
  track["Device<br>Tracking"]
  conv["Data<br>Conversion"]

  coord --> scan
  coord --> conn
  coord --> track
  coord --> conv
```

- **Scanning and discovery** — listens for Bluetooth broadcasts and determines which devices are supported
- **Connection management** — handles connecting to devices for probing and periodic reads, with limits to prevent overloading the Bluetooth adapter
- **Device tracking** — remembers which devices have been seen, confirmed, or rejected, and cleans up stale entries over time
- **Data conversion** — translates raw Bluetooth data into the format the parsing library expects

Each of these concerns is handled independently. When you see a device in the Discovered section, all four worked together to get it there.

## Per-device setup

For each device you confirm, the integration creates:

```mermaid
flowchart LR
  subgraph per["Per confirmed device"]
    bridge["Connection<br>Bridge"]
    proc["Update<br>Processor"]
    subgraph ent["Sensor Entities"]
      e1["Temperature"]
      e2["Battery"]
      e3["..."]
    end
    bridge --> proc --> ent
  end
  bt(["Bluetooth<br>Adapter"]) --> bridge
  ent --> ha(["Home Assistant<br>Dashboard"])
```

- A **connection bridge** between Home Assistant's Bluetooth stack and the parsing library
- A **processor** that receives broadcast updates and manages poll timing
- **Sensor entities** — one per characteristic (or per field within a multi-field characteristic)

## Two types of config entry

The integration creates two types of entry in Home Assistant:

```mermaid
flowchart TD
  hub["Hub Entry<br><i>one per installation</i><br>Bluetooth scanner + global settings"]
  hub -->|discovers| d1["Device Entry<br><i>Thermometer</i>"]
  hub -->|discovers| d2["Device Entry<br><i>Heart Rate Monitor</i>"]
  hub -->|discovers| d3["Device Entry<br><i>...</i>"]
```

- **Hub entry** — one per installation. This is what you create when you first add the integration. It runs the Bluetooth scanner and holds global settings (like the poll interval).
- **Device entries** — one per confirmed device. These are created automatically when you accept a discovered device.

This approach is needed because the integration cannot know in advance which devices you own — it discovers them at runtime based on what data they broadcast.

## Design principles

**No hardcoded device lists**: All characteristic parsing, naming, and unit assignment come from the upstream parsing library. When the library adds support for a new Bluetooth characteristic, this integration supports it automatically — no update needed here.

**Resource limits**: In environments with many Bluetooth devices, the integration limits how many devices it tracks, how many connections it opens simultaneously, and how long it remembers devices that are no longer in range. This prevents it from consuming excessive memory or radio time.

**Two data paths**: Broadcast monitoring and connected reads operate independently. This means a device that only broadcasts still works perfectly, and a device that requires connections gets polled without affecting broadcast-only devices.

## Code architecture

For contributors and advanced users, this diagram shows how the source files relate to each other:

```mermaid
flowchart TD
  init["__init__"] --> coord["coordinator"]
  init --> const["const"]
  coord --> adv["advertisement_manager"]
  coord --> gatt["gatt_manager"]
  coord --> disc["discovery_tracker"]
  coord --> supp["support_detector"]
  coord --> eb["entity_builder"]
  coord --> da["device_adapter"]
  coord --> dv["device_validator"]
  gatt --> da
  gatt --> dv
  gatt --> eb
  supp --> adv
  eb --> em["entity_metadata"]
  sensor["sensor"] --> coord
  diag["diagnostics"] --> const
  cf["config_flow"] --> const

  classDef core fill:#4a90d9,color:#fff
  classDef mgr fill:#7cb342,color:#fff
  classDef util fill:#ff9800,color:#fff
  classDef plat fill:#ab47bc,color:#fff

  class init,coord core
  class adv,gatt,disc,supp mgr
  class eb,em,da,dv,const util
  class sensor,diag,cf plat
```

<sup>🟦 Core &nbsp; 🟩 Managers &nbsp; 🟧 Utilities &nbsp; 🟪 Platforms / Flows</sup>
