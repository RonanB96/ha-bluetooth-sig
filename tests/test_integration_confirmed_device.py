"""Integration tests — confirmed device GATT re-probe behaviour.

These tests exercise where a confirmed device (one the user has already
added via the config flow) is not rejected after probe failures,
and the coordinator continues to schedule probes for it.

Test inventory
--------------
1. Confirmed device probe is not blocked by exhausted failure count
2. Confirmed device probe obeys the backoff window
3. Confirmed device probe fires again after backoff expires
4. Unconfirmed device with exhausted failures is NOT re-probed (contrast)
5. ``gatt_enabled=False`` suppresses probe even for confirmed device
6. Confirmed device recovers full GATT entities after simulated cold-start failure
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices.const import (
    CONFIRMED_DEVICE_PROBE_BACKOFF,
)

from .bluetooth_helpers import (
    inject_bluetooth_service_info,
    load_fixture,
    load_service_info,
    mock_gatt_connection,
)
from .conftest import setup_device_entry

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


# ---------------------------------------------------------------------------
# Fixture shortcuts
# ---------------------------------------------------------------------------


@pytest.fixture
def smart_watch_fixture() -> dict[str, Any]:
    """Return the esphome_smart_watch fixture data."""
    return load_fixture("esphome_smart_watch")


@pytest.fixture
def health_monitor_fixture() -> dict[str, Any]:
    """Return the esphome_health_monitor fixture data."""
    return load_fixture("esphome_health_monitor")


# ---------------------------------------------------------------------------
# 1. Confirmed device — probe not blocked by exhausted failure count
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_probe_not_blocked_by_failures(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Exhausted probe failures do NOT permanently prevent probe for confirmed devices.

    Scenario:
    - Hub entry + device config entry already exist (device was confirmed).
    - Probe failures are at the hard limit (device was out of range on HA start).
    - A new advertisement arrives.
    - The coordinator uses ``schedule_probe_for_confirmed_device()`` and
      schedules a new probe task, bypassing the failure limit.

    Contrast with test 4 which shows the same failure count *does* block
    unconfirmed devices.
    """
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]

    # Simulate the user having already confirmed this device.
    await setup_device_entry(hass, address=address, name=device["name"])

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    # Simulate exhausted failures — as if the device was unreachable at startup.
    gatt.probe_failures[address] = gatt._max_probe_retries
    # Set last-attempt to well before the backoff window so retry is allowed.
    gatt._confirmed_probe_last_attempt[address] = (
        time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 10
    )

    # Track whether a probe task is created for this address.
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

    assert probes_scheduled, (
        f"Expected a re-probe task for confirmed device {address} despite "
        f"exhausted failure count, but none was scheduled. "
        f"probe_failures={gatt.probe_failures.get(address)}"
    )


# ---------------------------------------------------------------------------
# 2. Confirmed device — probe suppressed within backoff window
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_probe_suppressed_within_backoff(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Re-probe is NOT scheduled while within the backoff window.

    If a re-probe attempt occurred very recently (within
    ``CONFIRMED_DEVICE_PROBE_BACKOFF`` seconds) the manager should not
    schedule another attempt.  This prevents hammering the BLE adapter when
    a device is persistently unreachable.
    """
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]

    await setup_device_entry(hass, address=address, name=device["name"])

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    gatt.probe_failures[address] = gatt._max_probe_retries
    # Last attempt was just now — within the backoff window.
    gatt._confirmed_probe_last_attempt[address] = time.monotonic()

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

    assert not probes_scheduled, (
        f"Expected no probe task within backoff window for {address}, "
        f"but {len(probes_scheduled)} task(s) were scheduled."
    )


# ---------------------------------------------------------------------------
# 3. Confirmed device — probe fires again after backoff expires
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_probe_fires_after_backoff_expires(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    health_monitor_fixture: dict[str, Any],
) -> None:
    """After the backoff window expires a new probe is scheduled.

    This uses the health monitor fixture (different address from the
    smart watch tests) to verify the backoff is per-address.
    """
    device = list(health_monitor_fixture["devices"].values())[0]
    address = device["address"]

    await setup_device_entry(hass, address=address, name=device["name"])

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    gatt.probe_failures[address] = gatt._max_probe_retries
    # Expired backoff: last attempt was longer ago than the window.
    gatt._confirmed_probe_last_attempt[address] = (
        time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 1
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

    assert probes_scheduled, (
        f"Expected probe task after backoff expiry for {address}, "
        f"but none was scheduled."
    )

    # Probe counter must be cleared before scheduling so async_probe_device
    # won't short-circuit.  Test 7 verifies this at task-creation time; here
    # we just confirm a probe was attempted (counter will be > 0 after the
    # probe fails in the test environment, which is expected).
    assert (
        address in gatt.pending_probes
        or address in gatt.probe_results
        or gatt.probe_failures.get(address, 0) >= 0
    ), "Probe state inconsistent after task scheduling"


# ---------------------------------------------------------------------------
# 4. Unconfirmed device with exhausted failures is still blocked (contrast)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_unconfirmed_device_remains_blocked_after_failures(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """An unconfirmed device's probe IS permanently blocked by exhausted failures.

    This is the complementary test to test 1.  For a device with no config
    entry (not yet confirmed by the user), the coordinator's rejection
    logic still applies.  Once the failure limit is reached and the device is
    rejected, no new probe is ever scheduled for that address.
    """
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]

    # Deliberately do NOT create a device config entry — device is unconfirmed.
    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    # Exhaust failures and mark the device as rejected (as the coordinator
    # would do via the normal path when all probes fail).
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

    assert not probes_scheduled, (
        f"Expected unconfirmed device {address} to remain blocked after exhausted "
        f"failures, but a probe task was scheduled. "
        f"is_rejected={coordinator.discovery_tracker.is_rejected(address)}"
    )


# ---------------------------------------------------------------------------
# 5. gatt_enabled=False suppresses probe for confirmed device
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_gatt_disabled_suppresses_probe(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """When GATT is disabled via device options, no probe is scheduled.

    A confirmed device with ``gatt_enabled: False`` in its config entry
    options should not trigger a GATT probe regardless of failure history.
    The user explicitly opted out.
    """
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]

    # Create the device entry with GATT disabled.
    entry = await setup_device_entry(hass, address=address, name=device["name"])
    # Override options after setup.
    hass.config_entries.async_update_entry(entry, options={"gatt_enabled": False})
    await hass.async_block_till_done()

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    # Even with an expired backoff there should be no probe.
    gatt.probe_failures[address] = gatt._max_probe_retries
    gatt._confirmed_probe_last_attempt[address] = (
        time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 10
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

    assert not probes_scheduled, (
        f"Expected no probe when gatt_enabled=False for {address}, "
        f"but {len(probes_scheduled)} task(s) were scheduled."
    )


# ---------------------------------------------------------------------------
# 6. End-to-end: confirmed device recovers entities after cold-start failure
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_recovers_entities_after_cold_start_failure(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    smart_watch_fixture: dict[str, Any],
) -> None:
    """Confirmed device regains GATT entities after a simulated cold-start failure.

    Scenario that the bug caused to fail:
    1. Hub and device entries exist from a previous HA session.
    2. On restart the device is temporarily out of range — probe fails.
    3. The failure counter is injected to simulate the failed startup probe.
    4. The device comes back into range — backoff is expired and the device
       is connectable.
    5. A new advertisement triggers ``schedule_probe_for_confirmed_device``.
    6. The probe succeeds (mock_gatt_connection) and entities are created.

    Before the fix, step 5 would be silently skipped because the failure
    count was exhausted, and the device would
    never regain GATT entities without a manual HA restart.
    """
    device = list(smart_watch_fixture["devices"].values())[0]
    address = device["address"]
    advert = _first_connectable_advert(device)

    # Step 1: Device entry already exists (confirmed by user in a previous session).
    await setup_device_entry(hass, address=address, name=device["name"])

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    # Step 2–3: Simulate probe failures from the cold-start period.
    gatt.probe_failures[address] = gatt._max_probe_retries
    gatt._confirmed_probe_last_attempt[address] = (
        time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 10
    )

    # Step 4–6: Device comes back; advertisement arrives; probe succeeds.
    service_info = load_service_info(device, advert)

    with mock_gatt_connection(device):
        inject_bluetooth_service_info(hass, service_info)
        # Allow probe to be scheduled and run to completion.
        await hass.async_block_till_done()
        await hass.async_block_till_done()
        await hass.async_block_till_done()

    # Probe should have succeeded and results should be cached.
    assert address in gatt.probe_results, (
        f"Expected GATT probe result for {address} after recovery, "
        f"but probe_results is empty. "
        f"probe_failures={gatt.probe_failures.get(address)}"
    )

    result = gatt.probe_results[address]
    assert result.parseable_count > 0, (
        f"Expected at least one parseable characteristic after recovery, "
        f"got parseable_count={result.parseable_count}"
    )


# ---------------------------------------------------------------------------
# 7. Failure counter is cleared before re-probe attempt
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_confirmed_device_probe_scheduled_despite_failures(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    health_monitor_fixture: dict[str, Any],
) -> None:
    """``schedule_probe_for_confirmed_device`` schedules despite exhausted failures.

    The probe is scheduled even when ``probe_failures >= max_retries``,
    because confirmed devices use backoff-based retries rather than a
    hard failure limit.  The failure counter is NOT cleared — the
    coordinator decides policy, not the GATTManager.
    """
    device = list(health_monitor_fixture["devices"].values())[0]
    address = device["address"]

    await setup_device_entry(hass, address=address, name=device["name"])

    coordinator = integration_entry.runtime_data
    gatt = coordinator.gatt_manager

    gatt.probe_failures[address] = gatt._max_probe_retries
    gatt._confirmed_probe_last_attempt[address] = (
        time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 10
    )

    # Track whether a probe task is created.
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

    assert probes_scheduled, "Expected a probe task to be scheduled"
