"""Integration tests — confirmed device unified GATT poll path.

Exercises the documented production paths for user-confirmed devices:

- **Advert-triggered poll:** ``GattDevicePollCoordinator`` receives an
  advertisement → ``needs_poll_method`` → debounced ``poll_method`` →
  self-discovering ``async_poll_gatt_with_semaphore``.
- **Initial poll on processor start:** ``async_start`` →
  ``_schedule_timer_poll(force=True)`` using ``async_last_service_info``.
- **Timer-driven poll:** interval timer when HA deduplicates identical
  adverts and no new advertisement callback fires.

These tests deliberately avoid calling ``GATTManager`` poll helpers directly
so they guard the wiring that failed in production after HA restart.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.bluetooth_sig_devices.const import MAX_PROBE_FAILURES

from .bluetooth_helpers import (
    find_sensor_states,
    inject_bluetooth_service_info,
    load_fixture,
    load_service_info,
    mock_gatt_connection,
)
from .conftest import make_device_entry, setup_device_entry

# ---------------------------------------------------------------------------
# Autouse fixtures (mirror test_integration_connected.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Allow lingering timers from the Bluetooth manager."""
    return True


@pytest.fixture(autouse=True)
def _disable_external_discovery_flows():
    """Prevent BluetoothManager from triggering flows for other integrations."""
    with patch(
        "homeassistant.components.bluetooth.manager.discovery_flow.async_create_flow"
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_connectable_advert(device: dict[str, Any]) -> dict[str, Any]:
    """Return the first non-synthetic connectable advertisement from a fixture device."""
    return next(
        a
        for a in device["advertisements"]
        if not a.get("_synthetic") and a.get("connectable", True)
    )


async def _wait_for_poll_pipeline(hass: HomeAssistant, *, rounds: int = 6) -> None:
    """Drain the event loop so debounced GATT polls can finish."""
    for _ in range(rounds):
        await hass.async_block_till_done()


async def _wait_for_probe_results(
    hass: HomeAssistant,
    gatt: Any,
    address: str,
    *,
    timeout: float = 10.0,
) -> None:
    """Wait until self-discovering poll populates ``probe_results``."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while address not in gatt.probe_results:
        if loop.time() >= deadline:
            break
        await asyncio.sleep(0.05)
        await _wait_for_poll_pipeline(hass, rounds=2)


def _simulate_restart_probe_cache_loss(
    coordinator: Any,
    address: str,
    *,
    probe_failures: int = 0,
) -> None:
    """Clear in-memory GATT probe state as after an HA restart."""
    gatt = coordinator.gatt_manager
    gatt.remove_device(address)
    if probe_failures:
        gatt.probe_failures[address] = probe_failures


def _assert_battery_entity(hass: HomeAssistant, *, expected: int = 82) -> None:
    """Assert a battery-level sensor exists with the fixture value."""
    battery_states = find_sensor_states(hass, unit="%")
    assert battery_states, "No battery-level (%) sensor entity was created"
    found = any(s.state.isdigit() and int(s.state) == expected for s in battery_states)
    assert found, (
        f"Expected battery = {expected}%, got states: {[s.state for s in battery_states]}"
    )


async def _setup_confirmed_device(
    hass: HomeAssistant,
    address: str,
    name: str,
    *,
    device_poll_interval: int = 0,
) -> MockConfigEntry:
    """Create a confirmed device entry, optionally with a poll interval override."""
    options: dict[str, int] = {}
    if device_poll_interval:
        options["device_poll_interval"] = device_poll_interval
    entry = make_device_entry(address=address, name=name, options=options)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# Fixture shortcuts
# ---------------------------------------------------------------------------


@pytest.fixture
def smart_watch_fixture() -> dict[str, Any]:
    """Return the esphome_smart_watch fixture data."""
    return load_fixture("esphome_smart_watch")


# ---------------------------------------------------------------------------
# 1. Advert-triggered self-discovery (device already confirmed)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_advert_poll_discovers_gatt_entities(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Advert callback → needs_poll → poll_method discovers and creates entities."""
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]
    advert = _first_connectable_advert(device)
    service_info = load_service_info(device, advert)

    coordinator = integration_entry.runtime_data
    await _setup_confirmed_device(hass, address=address, name=device["name"])
    _simulate_restart_probe_cache_loss(coordinator, address)
    assert address in coordinator.processor_coordinators

    with mock_gatt_connection(device):
        inject_bluetooth_service_info(hass, service_info)
        await _wait_for_probe_results(hass, coordinator.gatt_manager, address)

    assert address in coordinator.gatt_manager.probe_results
    assert coordinator.gatt_manager.probe_results[address].parseable_count > 0
    _assert_battery_entity(hass, expected=82)


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_advert_poll_despite_exhausted_probe_failures(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Poll self-discovery works even when discovery probe failures were exhausted."""
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]
    advert = _first_connectable_advert(device)
    service_info = load_service_info(device, advert)

    coordinator = integration_entry.runtime_data
    await _setup_confirmed_device(hass, address=address, name=device["name"])
    _simulate_restart_probe_cache_loss(
        coordinator, address, probe_failures=MAX_PROBE_FAILURES
    )

    with mock_gatt_connection(device):
        inject_bluetooth_service_info(hass, service_info)
        await _wait_for_probe_results(hass, coordinator.gatt_manager, address)

    assert address in coordinator.gatt_manager.probe_results
    _assert_battery_entity(hass, expected=82)


# ---------------------------------------------------------------------------
# 2. Initial forced poll on processor start (no post-setup advert)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_initial_poll_on_processor_start(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Processor async_start force-poll discovers using cached service info."""
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]
    advert = _first_connectable_advert(device)
    service_info = load_service_info(device, advert)

    coordinator = integration_entry.runtime_data

    with mock_gatt_connection(device):
        # Populate HA bluetooth cache before the processor exists.
        inject_bluetooth_service_info(hass, service_info)
        await _wait_for_poll_pipeline(hass)
        _simulate_restart_probe_cache_loss(coordinator, address)

        # Simulates persisted device config after restart — no new advert yet.
        await _setup_confirmed_device(hass, address=address, name=device["name"])
        await _wait_for_probe_results(hass, coordinator.gatt_manager, address)

    assert address in coordinator.gatt_manager.probe_results
    assert coordinator.gatt_manager.probe_results[address].parseable_count > 0
    _assert_battery_entity(hass, expected=82)


# ---------------------------------------------------------------------------
# 3. Timer-driven poll when adverts are deduplicated
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_timer_poll_without_new_advert(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Interval timer re-polls when no further advertisement callbacks fire."""
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]
    advert = _first_connectable_advert(device)
    service_info = load_service_info(device, advert)
    poll_interval = 30

    coordinator = integration_entry.runtime_data

    with mock_gatt_connection(device) as mock_client:
        inject_bluetooth_service_info(hass, service_info)
        await _wait_for_poll_pipeline(hass)
        _simulate_restart_probe_cache_loss(coordinator, address)

        await _setup_confirmed_device(
            hass,
            address=address,
            name=device["name"],
            device_poll_interval=poll_interval,
        )
        await _wait_for_probe_results(hass, coordinator.gatt_manager, address)

        assert address in coordinator.gatt_manager.probe_results
        reads_after_start = mock_client.read_gatt_char.await_count

        # Identical advert is deduplicated — no new processor callback.
        inject_bluetooth_service_info(hass, service_info)
        await _wait_for_poll_pipeline(hass)

        # Timer poll uses cached service info; advance its monotonic timestamp so
        # needs_poll sees an elapsed interval (fixture advert times are not monotonic).
        fresh_service_info = load_service_info(device, advert)
        proc = coordinator.processor_coordinators[address]
        assert proc._last_poll is not None
        fresh_service_info.time = proc._last_poll + poll_interval + 1

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.bluetooth"
            ".async_last_service_info",
            return_value=fresh_service_info,
        ):
            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(seconds=poll_interval + 1)
            )
            await _wait_for_poll_pipeline(hass, rounds=10)

    assert mock_client.read_gatt_char.await_count > reads_after_start, (
        "Expected timer-driven GATT read after poll interval elapsed"
    )
    _assert_battery_entity(hass, expected=82)


# ---------------------------------------------------------------------------
# 4. gatt_enabled=False suppresses poll path
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_gatt_disabled_skips_poll(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """When GATT is disabled via device options, poll discovery does not run."""
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]
    service_info = load_service_info(device, _first_connectable_advert(device))

    entry = await setup_device_entry(hass, address=address, name=device["name"])
    hass.config_entries.async_update_entry(entry, options={"gatt_enabled": False})
    await hass.async_block_till_done()

    coordinator = integration_entry.runtime_data
    _simulate_restart_probe_cache_loss(coordinator, address)

    with mock_gatt_connection(device):
        inject_bluetooth_service_info(hass, service_info)
        await _wait_for_poll_pipeline(hass)

    assert address not in coordinator.gatt_manager.probe_results


# ---------------------------------------------------------------------------
# 5. Unconfirmed device contrast — exhausted failures still block discovery
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_unconfirmed_device_remains_blocked_after_failures(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """An unconfirmed device's discovery probe stays blocked after exhaustion."""
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    gatt.probe_failures[address] = gatt._max_probe_retries
    coordinator.discovery_tracker.mark_rejected(
        address, "all GATT probe attempts exhausted"
    )

    probes_scheduled: list[str] = []
    original_create_task = hass.async_create_task

    def _watch_create_task(coro: Any, name: str = "") -> Any:
        if f"bluetooth_sig_probe_{address}" in (name or ""):
            probes_scheduled.append(name)
        return original_create_task(coro, name)

    service_info = load_service_info(device, _first_connectable_advert(device))

    with patch.object(hass, "async_create_task", side_effect=_watch_create_task):
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()

    assert not probes_scheduled
    assert coordinator.discovery_tracker.is_rejected(address)
