"""Tests for diagnostics."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.bluetooth_sig_devices.diagnostics import (
    async_get_config_entry_diagnostics,
)


def _make_entry(
    options: dict | None = None,
    tracked_devices: int = 0,
    processor_coordinators: int = 0,
    probe_results: dict | None = None,
    probe_failures: dict | None = None,
    pending_probes: int = 0,
) -> MagicMock:
    """Build a mock config entry with a minimal coordinator.

    The coordinator mock provides ``get_diagnostics_snapshot()`` returning
    a dict in the same shape as the real implementation.
    """
    _probe_results = probe_results or {}
    _probe_failures = probe_failures or {}

    # Build the snapshot dict that the real coordinator would return
    probe_results_data: dict[str, dict] = {}
    for addr, result in _probe_results.items():
        probe_results_data[addr] = {
            "parseable_characteristics": result.parseable_count,
            "has_support": result.has_support(),
            "probe_failures": _probe_failures.get(addr, 0),
        }

    snapshot = {
        "device_statistics": {
            "tracked_devices": tracked_devices,
            "active_processor_coordinators": processor_coordinators,
            "gatt_probed_devices": len(_probe_results),
            "pending_probes": pending_probes,
            "seen_devices": 0,
            "rejected_devices": 0,
            "discovery_triggered": 0,
            "filtered_ephemeral_count": 0,
        },
        "gatt_probe_results": probe_results_data,
        "probe_failures": dict(_probe_failures),
        "known_characteristics": {},
    }

    coordinator = MagicMock()
    coordinator.get_diagnostics_snapshot.return_value = snapshot

    entry = MagicMock()
    entry.options = options or {}
    entry.runtime_data = coordinator
    return entry


class TestAsyncGetConfigEntryDiagnostics:
    """Tests for async_get_config_entry_diagnostics."""

    async def test_empty_coordinator_returns_valid_structure(
        self, hass: HomeAssistant
    ) -> None:
        """Diagnostics returns required keys even with no devices."""
        entry = _make_entry()
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert "options" in result
        assert "device_statistics" in result
        assert "gatt_probe_results" in result
        assert "probe_failures" in result
        assert "known_characteristics" in result

    async def test_device_statistics_counts_correctly(
        self, hass: HomeAssistant
    ) -> None:
        """device_statistics reflects coordinator state accurately."""
        entry = _make_entry(
            tracked_devices=3,
            processor_coordinators=2,
            pending_probes=1,
        )
        result = await async_get_config_entry_diagnostics(hass, entry)
        stats = result["device_statistics"]

        assert stats["tracked_devices"] == 3
        assert stats["active_processor_coordinators"] == 2
        assert stats["gatt_probed_devices"] == 0
        assert stats["pending_probes"] == 1

    async def test_options_are_passed_through(self, hass: HomeAssistant) -> None:
        """Options from the config entry appear verbatim in diagnostics."""
        entry = _make_entry(options={"poll_interval": 300})
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["options"] == {"poll_interval": 300}

    async def test_gatt_probe_results_are_included(self, hass: HomeAssistant) -> None:
        """GATT probe results are serialised per-address."""
        probe = MagicMock()
        probe.parseable_count = 5
        probe.has_support.return_value = True

        entry = _make_entry(
            probe_results={"AA:BB:CC:DD:EE:FF": probe},
            probe_failures={"AA:BB:CC:DD:EE:FF": 1},
        )
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert "AA:BB:CC:DD:EE:FF" in result["gatt_probe_results"]
        probe_data = result["gatt_probe_results"]["AA:BB:CC:DD:EE:FF"]
        assert probe_data["parseable_characteristics"] == 5
        assert probe_data["has_support"] is True
        assert probe_data["probe_failures"] == 1

    async def test_probe_failures_included_even_without_probe_results(
        self, hass: HomeAssistant
    ) -> None:
        """Probe failure counts appear even when there are no successful probes."""
        entry = _make_entry(probe_failures={"AA:BB:CC:DD:EE:FF": 3})
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["probe_failures"] == {"AA:BB:CC:DD:EE:FF": 3}
