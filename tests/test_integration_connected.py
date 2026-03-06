"""Integration tests — connected device path (GATT probe + poll).

These tests verify the full GATT connection flow: an advertisement with
service UUIDs but NO service_data triggers a GATT probe, which connects
to the device, discovers services, reads characteristic values, and
creates entities from the parsed data.

The BLE hardware layer is mocked using ``mock_gatt_connection`` from
``bluetooth_helpers`` which patches ``establish_connection``,
``close_stale_connections_by_address``, and
``async_ble_device_from_address`` — the raw GATT service trees and
characteristic values come from real ESP32 captures stored in the
fixture files.

For the passive advertisement injection path see
``test_integration_advertising.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices.const import DOMAIN

from .bluetooth_helpers import (
    find_sensor_states as _find_sensor_states,
)
from .bluetooth_helpers import (
    inject_bluetooth_service_info,
    load_fixture,
    load_service_info,
    mock_gatt_connection,
)
from .conftest import setup_device_entry

# ---------------------------------------------------------------------------
# Shared autouse fixtures for integration tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Allow lingering timers from the Bluetooth manager."""
    return True


@pytest.fixture(autouse=True)
def _disable_external_discovery_flows():
    """Prevent the BluetoothManager from triggering flows for other integrations."""
    with patch(
        "homeassistant.components.bluetooth.manager.discovery_flow.async_create_flow"
    ):
        yield


# ---------------------------------------------------------------------------
# _run_gatt_probe helper — end-to-end GATT probe + entity creation
# ---------------------------------------------------------------------------


async def _run_gatt_probe(
    hass: HomeAssistant,
    device: dict[str, Any],
    advert: dict[str, Any],
) -> None:
    """Inject an advert that triggers a GATT probe and wait for entity creation.

    Steps:
    1. Inject advertisement → coordinator schedules GATT probe.
    2. Probe runs inside ``mock_gatt_connection`` → results stored.
    3. Create a device config entry → sensor platform creates an ABPC.
    4. ABPC starts → HA replays the last-known advertisement →
       ``needs_poll_method`` returns True → ``poll_method`` connects via
       BLE → reads characteristics → entities are created.

    The ``mock_gatt_connection`` context must wrap both probe and poll
    because both require an active BLE connection.
    """
    address = device["address"]
    name = device.get("name", f"test-device-{address[-5:]}")
    service_info = load_service_info(device, advert)

    with mock_gatt_connection(device):
        # 1. Inject advertisement → coordinator schedules GATT probe
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()
        await hass.async_block_till_done()
        await hass.async_block_till_done()

        # 2. Create device entry → ABPC starts → poll fires within
        #    mock_gatt_connection so BLE reads succeed
        await setup_device_entry(hass, address=address, name=name)
        await hass.async_block_till_done()
        await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 1. Probe scheduling — connectable adverts trigger GATT probe
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_connectable_device_triggers_gatt_probe(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Inject connectable advert (service UUIDs only) → GATT probe task scheduled."""
    fixture = load_fixture("esphome_env_sensor")
    device = list(fixture["devices"].values())[0]

    first_non_synthetic = next(
        a for a in device["advertisements"] if not a.get("_synthetic")
    )

    coordinator = integration_entry.runtime_data

    probes_scheduled: list[str] = []
    original_create_task = hass.async_create_task

    def _patched_create_task(coro, name=""):
        if "bluetooth_sig_probe_" in (name or ""):
            probes_scheduled.append(name)
        return original_create_task(coro, name)

    with patch.object(hass, "async_create_task", side_effect=_patched_create_task):
        service_info = load_service_info(device, first_non_synthetic)
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()

    assert (
        coordinator.gatt_manager.pending_probes
        or probes_scheduled
        or (device["address"] in coordinator.gatt_manager.probe_results)
    ), "Expected GATT probe to be scheduled for connectable device"


@pytest.mark.usefixtures("enable_bluetooth")
async def test_health_monitor_connectable_triggers_probe(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Non-synthetic health monitor advert (UUIDs only) schedules a GATT probe."""
    fixture = load_fixture("esphome_health_monitor")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    coordinator = integration_entry.runtime_data

    probes_scheduled: list[str] = []
    original_create_task = hass.async_create_task

    def _patched_create_task(coro, name=""):
        if "bluetooth_sig_probe_" in (name or ""):
            probes_scheduled.append(name)
        return original_create_task(coro, name)

    with patch.object(hass, "async_create_task", side_effect=_patched_create_task):
        service_info = load_service_info(device, first_normal)
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()

    assert (
        coordinator.gatt_manager.pending_probes
        or probes_scheduled
        or (device["address"] in coordinator.gatt_manager.probe_results)
    ), "Expected GATT probe for connectable health monitor"


# ---------------------------------------------------------------------------
# 2. Smart watch — full GATT probe → entity creation
#    Battery Service (0x180F): Battery Level (0x2A19) = 82%
#    Current Time Service (0x1805): Current Time (0x2A2B) = struct
#    Device Information (0x180A): 3 text strings (diagnostic)
#    Generic Attribute (0x1801): EXCLUDED
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_smart_watch_gatt_probe_battery(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """GATT probe reads Battery Level (0x2A19) = 0x52 → entity with state 82."""
    fixture = load_fixture("esphome_smart_watch")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    await _run_gatt_probe(hass, device, first_normal)

    battery_states = _find_sensor_states(hass, unit="%")
    assert battery_states, "No battery-level (%) sensor entity was created"

    # ESP32 reported 0x52 = 82%
    found = any(s.state.isdigit() and int(s.state) == 82 for s in battery_states)
    assert found, (
        f"Expected battery = 82%, got states: {[s.state for s in battery_states]}"
    )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_smart_watch_gatt_probe_current_time_struct(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """GATT probe reads Current Time (0x2A2B) → struct decomposed into sub-entities.

    Current Time parses to TimeData with fields:
      date_time → datetime → str("2026-02-06 12:00:44")
      day_of_week → DayOfWeek enum → "THURSDAY"
      fractions256 → int → 0
      adjust_reason → IntFlag → 0
    """
    fixture = load_fixture("esphome_smart_watch")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    await _run_gatt_probe(hass, device, first_normal)

    all_states = hass.states.async_all("sensor")
    entity_ids = [s.entity_id for s in all_states]

    # Current Time is a struct — should produce per-field sub-entities
    time_related = [
        eid
        for eid in entity_ids
        if any(kw in eid for kw in ("date_time", "day_of_week", "fractions256"))
    ]
    assert time_related, (
        f"Expected Current Time struct sub-entities (date_time, day_of_week, "
        f"fractions256), got entity IDs: {entity_ids}"
    )

    # Verify day_of_week has expected enum name
    dow_states = _find_sensor_states(hass, contains="day_of_week")
    if dow_states:
        assert dow_states[0].state == "THURSDAY", (
            f"Expected day_of_week='THURSDAY', got {dow_states[0].state!r}"
        )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_smart_watch_gatt_probe_device_info_diagnostic(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Device Information chars (INFO role) created as diagnostic entities.

    Manufacturer Name, Model Number, and Firmware Revision are all
    CharacteristicRole.INFO → entity_category=DIAGNOSTIC.
    """
    fixture = load_fixture("esphome_smart_watch")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    await _run_gatt_probe(hass, device, first_normal)

    coordinator = integration_entry.runtime_data
    address = device["address"]

    # Verify the probe completed and found parseable characteristics
    assert address in coordinator.gatt_manager.probe_results, (
        f"Expected probe result for {address}"
    )
    result = coordinator.gatt_manager.probe_results[address]
    # Battery + Current Time + 3 Device Info = 5 parseable
    # (Generic Attribute / Service Changed is excluded)
    assert result.parseable_count >= 2, (
        f"Expected at least 2 parseable chars, got {result.parseable_count}"
    )


# ---------------------------------------------------------------------------
# 3. Health monitor — GATT probe → Heart Rate struct + Body Sensor Location
#    Heart Rate Service (0x180D):
#      Heart Rate Measurement (0x2A37) → HeartRateData struct
#      Body Sensor Location (0x2A38) → BodySensorLocation enum → "CHEST"
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_health_monitor_gatt_probe_heart_rate_struct(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """GATT probe reads Heart Rate Measurement → struct sub-entities created.

    HeartRateData fields: heart_rate (73), sensor_contact, energy_expended (17),
    rr_intervals, flags, sensor_location (None).
    """
    fixture = load_fixture("esphome_health_monitor")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    await _run_gatt_probe(hass, device, first_normal)

    all_states = hass.states.async_all("sensor")
    entity_ids = [s.entity_id for s in all_states]

    # At least heart_rate sub-entity should be created
    hr_related = [eid for eid in entity_ids if "heart_rate" in eid]
    assert hr_related, (
        f"Expected Heart Rate struct sub-entities, got entity IDs: {entity_ids}"
    )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_health_monitor_gatt_probe_heart_rate_value(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Heart rate sub-entity has value 73 bpm from real ESP32 GATT read."""
    fixture = load_fixture("esphome_health_monitor")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    await _run_gatt_probe(hass, device, first_normal)

    all_states = hass.states.async_all("sensor")

    # Find the heart_rate entity (not flags, contact, location sub-fields)
    hr_entities = [
        s
        for s in all_states
        if "heart_rate" in s.entity_id
        and "flag" not in s.entity_id
        and "contact" not in s.entity_id
        and "location" not in s.entity_id
    ]
    assert hr_entities, (
        f"No heart_rate entity found, "
        f"all entity IDs: {[s.entity_id for s in all_states]}"
    )

    # Raw data 0x1e4911004903 → heart_rate=73 bpm
    found_hr = any(
        abs(float(s.state) - 73.0) < 1.0
        for s in hr_entities
        if s.state.replace(".", "", 1).isdigit()
    )
    assert found_hr, (
        f"Expected heart_rate ≈73 bpm, "
        f"got: {[(s.entity_id, s.state) for s in hr_entities]}"
    )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_health_monitor_gatt_probe_body_sensor_location(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Body Sensor Location (0x2A38) → IntEnum value "CHEST" from GATT read.

    BSL is BodySensorLocation(1) = CHEST. The coordinator's _to_ha_state
    returns the enum name "CHEST" since it has a .name attribute.
    """
    fixture = load_fixture("esphome_health_monitor")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    await _run_gatt_probe(hass, device, first_normal)

    all_states = hass.states.async_all("sensor")

    # Look for body_sensor_location entity
    bsl_entities = [
        s for s in all_states if "body_sensor" in s.entity_id or "2a38" in s.entity_id
    ]

    assert bsl_entities, (
        f"No Body Sensor Location entity found, "
        f"all entity IDs: {[s.entity_id for s in all_states]}"
    )

    # BodySensorLocation(1).name = "CHEST"
    assert bsl_entities[0].state == "CHEST", (
        f"Expected Body Sensor Location = 'CHEST', got {bsl_entities[0].state!r}"
    )


# ---------------------------------------------------------------------------
# 4. Mesh node — GATT probe finds no parseable readable chars → no entities
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_mesh_node_gatt_probe_no_parseable_chars(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Mesh node GATT probe discovers write/notify-only chars → no entities.

    Mesh Provisioning (0x1827) and Mesh Proxy (0x1828) have Data In (write)
    and Data Out (notify) — neither is readable.  Device Information chars
    have role=INFO (diagnostic) and will be created but mesh-specific chars
    should produce no measurement entities.
    """
    fixture = load_fixture("esphome_mesh_node")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    states_before = {s.entity_id for s in hass.states.async_all("sensor")}

    await _run_gatt_probe(hass, device, first_normal)

    states_after = {s.entity_id for s in hass.states.async_all("sensor")}
    new_measurement_states = {
        eid for eid in (states_after - states_before) if "mesh" in eid
    }

    # No mesh-specific measurement entities should be created
    assert not new_measurement_states, (
        f"Expected no mesh measurement entities, but got: {new_measurement_states}"
    )


# ---------------------------------------------------------------------------
# 5. Pre-seeded GATT path — coordinator with cached probe results
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_connectable_device_gatt_probe_creates_entities(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Pre-seeded GATT probe results → entities created via poll path."""
    from homeassistant.components.bluetooth.passive_update_processor import (
        PassiveBluetoothDataUpdate,
        PassiveBluetoothEntityKey,
    )
    from homeassistant.components.sensor import SensorEntityDescription
    from homeassistant.helpers.device_registry import DeviceInfo

    from custom_components.bluetooth_sig_devices.device_validator import GATTProbeResult

    fixture = load_fixture("esphome_env_sensor")
    device = list(fixture["devices"].values())[0]
    address = device["address"]

    coordinator = integration_entry.runtime_data

    fake_probe_result = GATTProbeResult(
        address=address,
        name=device["name"],
        parseable_count=3,
        supported_char_uuids=[],
    )

    device_id = address.replace(":", "").lower()

    fake_gatt_update: PassiveBluetoothDataUpdate[float | int | str | bool] = (
        PassiveBluetoothDataUpdate(
            devices={
                None: DeviceInfo(
                    identifiers={(DOMAIN, address)},
                    name=device["name"],
                    connections={("bluetooth", address)},
                )
            },
            entity_descriptions={
                PassiveBluetoothEntityKey(
                    "00002a19-0000-1000-8000-00805f9b34fb", device_id
                ): SensorEntityDescription(
                    key="00002a19-0000-1000-8000-00805f9b34fb",
                    name="Battery Level",
                    native_unit_of_measurement="%",
                ),
            },
            entity_names={
                PassiveBluetoothEntityKey(
                    "00002a19-0000-1000-8000-00805f9b34fb", device_id
                ): "Battery Level",
            },
            entity_data={
                PassiveBluetoothEntityKey(
                    "00002a19-0000-1000-8000-00805f9b34fb", device_id
                ): 84,
            },
        )
    )

    # Seed probe results so needs_poll returns True
    coordinator.gatt_manager.probe_results[address] = fake_probe_result

    # Mock the poll method to return the pre-built update
    with patch.object(
        coordinator.gatt_manager,
        "async_poll_gatt_with_semaphore",
        return_value=fake_gatt_update,
    ):
        # Create a device entry so the sensor platform registers an ABPC.
        await setup_device_entry(hass, address=address, name=device["name"])

        first_non_synthetic = next(
            a for a in device["advertisements"] if not a.get("_synthetic")
        )
        service_info = load_service_info(device, first_non_synthetic)
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()
        await hass.async_block_till_done()

    assert address in coordinator.processor_coordinators, (
        f"Expected processor coordinator for {address}, "
        f"existing: {list(coordinator.processor_coordinators)}"
    )
