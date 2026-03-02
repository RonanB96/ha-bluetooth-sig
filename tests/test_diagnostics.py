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
    cached_updates: dict | None = None,
    poll_tasks: int = 0,
    pending_probes: int = 0,
) -> MagicMock:
    """Build a mock config entry with a minimal coordinator."""
    coordinator = MagicMock()
    coordinator.devices = {f"addr_{i}": MagicMock() for i in range(tracked_devices)}
    coordinator._processor_coordinators = {
        f"addr_{i}": MagicMock() for i in range(processor_coordinators)
    }
    coordinator._gatt_probe_results = probe_results or {}
    coordinator._probe_failures = probe_failures or {}
    coordinator._cached_gatt_updates = cached_updates or {}
    coordinator._gatt_poll_tasks = {f"addr_{i}": MagicMock() for i in range(poll_tasks)}
    coordinator._pending_probes = {f"addr_{i}" for i in range(pending_probes)}

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
        assert "cached_gatt_entity_counts" in result

    async def test_device_statistics_counts_correctly(
        self, hass: HomeAssistant
    ) -> None:
        """device_statistics reflects coordinator state accurately."""
        entry = _make_entry(
            tracked_devices=3,
            processor_coordinators=2,
            poll_tasks=1,
            pending_probes=1,
        )
        result = await async_get_config_entry_diagnostics(hass, entry)
        stats = result["device_statistics"]

        assert stats["tracked_devices"] == 3
        assert stats["active_processor_coordinators"] == 2
        assert stats["gatt_probed_devices"] == 0
        assert stats["gatt_poll_tasks_active"] == 1
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

    async def test_cached_gatt_entity_counts(self, hass: HomeAssistant) -> None:
        """Cached GATT updates report entity count per address."""
        cached_update = MagicMock()
        cached_update.entity_data = {"k1": 1.0, "k2": 2.0, "k3": 3.0}

        entry = _make_entry(cached_updates={"AA:BB:CC:DD:EE:FF": cached_update})
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["cached_gatt_entity_counts"] == {"AA:BB:CC:DD:EE:FF": 3}
