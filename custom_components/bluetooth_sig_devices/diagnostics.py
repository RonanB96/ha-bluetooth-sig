"""Diagnostics support for the Bluetooth SIG Devices integration."""

from __future__ import annotations

from typing import Any, TypedDict

from homeassistant.core import HomeAssistant

from . import BluetoothSIGConfigEntry


class _GATTProbeData(TypedDict):
    parseable_characteristics: int
    has_support: bool
    probe_failures: int


class _DeviceStatistics(TypedDict):
    tracked_devices: int
    active_processor_coordinators: int
    gatt_probed_devices: int
    gatt_poll_tasks_active: int
    pending_probes: int


class _DiagnosticsData(TypedDict):
    options: dict[str, Any]
    device_statistics: _DeviceStatistics
    gatt_probe_results: dict[str, _GATTProbeData]
    probe_failures: dict[str, int]
    cached_gatt_entity_counts: dict[str, int]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: BluetoothSIGConfigEntry,
) -> _DiagnosticsData:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    probe_results: dict[str, _GATTProbeData] = {
        addr: _GATTProbeData(
            parseable_characteristics=result.parseable_count,
            has_support=result.has_support(),
            probe_failures=coordinator._probe_failures.get(addr, 0),
        )
        for addr, result in coordinator._gatt_probe_results.items()
    }

    return _DiagnosticsData(
        options=dict(entry.options),
        device_statistics=_DeviceStatistics(
            tracked_devices=len(coordinator.devices),
            active_processor_coordinators=len(coordinator._processor_coordinators),
            gatt_probed_devices=len(coordinator._gatt_probe_results),
            gatt_poll_tasks_active=len(coordinator._gatt_poll_tasks),
            pending_probes=len(coordinator._pending_probes),
        ),
        gatt_probe_results=probe_results,
        probe_failures=dict(coordinator._probe_failures),
        cached_gatt_entity_counts={
            addr: len(update.entity_data)
            for addr, update in coordinator._cached_gatt_updates.items()
        },
    )
