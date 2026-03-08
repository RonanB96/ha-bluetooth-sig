"""Diagnostics support for the Bluetooth SIG Devices integration."""

from __future__ import annotations

from typing import Any, TypedDict

from homeassistant.core import HomeAssistant

from . import BluetoothSIGConfigEntry
from .const import (
    BLEAddress,
    DeviceStatistics,
    DiagnosticsSnapshot,
    GATTProbeSnapshotData,
)


class _DiagnosticsData(TypedDict):
    """Shape returned to the HA diagnostics panel."""

    options: dict[str, Any]
    device_statistics: DeviceStatistics
    gatt_probe_results: dict[BLEAddress, GATTProbeSnapshotData]
    probe_failures: dict[BLEAddress, int]
    known_characteristics: dict[BLEAddress, list[str]]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: BluetoothSIGConfigEntry,
) -> _DiagnosticsData:
    """Return diagnostics for a config entry.

    Uses the coordinator's public ``get_diagnostics_snapshot()`` API
    rather than reaching into private attributes.
    """
    coordinator = entry.runtime_data
    snapshot: DiagnosticsSnapshot = coordinator.get_diagnostics_snapshot()

    return _DiagnosticsData(
        options=dict(entry.options),
        device_statistics=snapshot["device_statistics"],
        gatt_probe_results=snapshot["gatt_probe_results"],
        probe_failures=snapshot["probe_failures"],
        known_characteristics=snapshot["known_characteristics"],
    )
