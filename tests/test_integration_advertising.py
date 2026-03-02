"""Integration tests — advertising data path (passive BLE advertisements).

These tests verify the full stack from BLE advertisement injection through
the real HomeAssistant Bluetooth dispatch pipeline to entity creation and
state reporting.  All tests use the *advertisement* path only: service_data
is present in the injected ``BluetoothServiceInfoBleak`` objects, so the
coordinator parses characteristic values directly from the advert payload.

No BLE connection or GATT service discovery is involved here.  For the
connected-device (GATT probe + poll) path see ``test_integration_connected.py``.
"""

from __future__ import annotations

import copy
import struct
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_sig_devices.const import DOMAIN

from .bluetooth_helpers import (
    inject_bluetooth_service_info,
    iter_service_infos,
    load_fixture,
    load_service_info,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def integration_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a real integration config entry for end-to-end tests."""
    entry = MockConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Bluetooth SIG Devices",
        data={},
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _find_sensor_states(
    hass: HomeAssistant,
    *,
    contains: str | None = None,
    unit: str | None = None,
) -> list[Any]:
    """Return sensor states, optionally filtered by entity_id substring or unit."""
    states = hass.states.async_all("sensor")
    if contains:
        states = [s for s in states if contains.lower() in s.entity_id.lower()]
    if unit:
        states = [s for s in states if s.attributes.get("unit_of_measurement") == unit]
    return states


# ---------------------------------------------------------------------------
# 1. Env-sensor — passive service-data advertisements
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_env_sensor_battery_entity_created(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Inject env-sensor GATT-enriched advert → battery entity created with real value."""
    fixture = load_fixture("esphome_env_sensor")
    device = list(fixture["devices"].values())[0]
    synthetic = next(a for a in device["advertisements"] if a.get("_synthetic"))

    service_info = load_service_info(device, synthetic)
    inject_bluetooth_service_info(hass, service_info)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    battery_states = _find_sensor_states(hass, unit="%")
    assert battery_states, "No battery-level (%) sensor entity was created"

    expected_battery = struct.unpack_from(
        "<B",
        bytes.fromhex(
            synthetic["service_data"]["00002a19-0000-1000-8000-00805f9b34fb"]
        ),
    )[0]
    states_map = {s.state for s in battery_states}
    assert str(expected_battery) in states_map or any(
        abs(int(s.state) - expected_battery) <= 1
        for s in battery_states
        if s.state.isdigit()
    ), f"Expected battery ≈{expected_battery}%, got states: {states_map}"


@pytest.mark.usefixtures("enable_bluetooth")
async def test_env_sensor_temperature_entity_created(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Inject env-sensor GATT-enriched advert → temperature entity created."""
    fixture = load_fixture("esphome_env_sensor")
    device = list(fixture["devices"].values())[0]
    synthetic = next(a for a in device["advertisements"] if a.get("_synthetic"))

    service_info = load_service_info(device, synthetic)
    inject_bluetooth_service_info(hass, service_info)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    temp_states = _find_sensor_states(hass, unit="°C")
    assert temp_states, "No temperature (°C) sensor entity was created"

    raw_temp = bytes.fromhex(
        synthetic["service_data"]["00002a6e-0000-1000-8000-00805f9b34fb"]
    )
    expected_temp = struct.unpack_from("<h", raw_temp)[0] / 100.0

    found = any(
        abs(float(s.state) - expected_temp) < 1.0
        for s in temp_states
        if s.state.replace(".", "", 1).lstrip("-").isdigit()
    )
    assert found, (
        f"Expected temperature ≈{expected_temp:.2f}°C, "
        f"got states: {[s.state for s in temp_states]}"
    )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_env_sensor_humidity_entity_created(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Inject env-sensor GATT-enriched advert → humidity entity created."""
    fixture = load_fixture("esphome_env_sensor")
    device = list(fixture["devices"].values())[0]
    synthetic = next(a for a in device["advertisements"] if a.get("_synthetic"))

    service_info = load_service_info(device, synthetic)
    inject_bluetooth_service_info(hass, service_info)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    hum_states = _find_sensor_states(hass, unit="%")
    raw_hum = bytes.fromhex(
        synthetic["service_data"]["00002a6f-0000-1000-8000-00805f9b34fb"]
    )
    expected_hum = struct.unpack_from("<H", raw_hum)[0] / 100.0

    found = any(
        abs(float(s.state) - expected_hum) < 1.0
        for s in hum_states
        if s.state.replace(".", "", 1).isdigit()
    )
    assert found, (
        f"Expected humidity ≈{expected_hum:.2f}%, "
        f"got % states: {[s.state for s in hum_states]}"
    )


# ---------------------------------------------------------------------------
# 2. Full replay — all advertisements in order
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_env_sensor_full_replay_creates_entities(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Replay all advertisements in order; entity count should grow."""
    initial_count = len(hass.states.async_all("sensor"))

    for service_info in iter_service_infos("esphome_env_sensor"):
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()

    final_states = hass.states.async_all("sensor")
    assert len(final_states) > initial_count, (
        "No new sensor entities were created after replaying all advertisements"
    )


# ---------------------------------------------------------------------------
# 3. State update on second injection
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_env_sensor_state_update_on_second_injection(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Inject two advertisements with different temperatures; state should update."""
    fixture = load_fixture("esphome_env_sensor")
    device = list(fixture["devices"].values())[0]
    synthetic = next(a for a in device["advertisements"] if a.get("_synthetic"))

    service_info_1 = load_service_info(device, synthetic)
    inject_bluetooth_service_info(hass, service_info_1)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    temp_states_1 = _find_sensor_states(hass, unit="°C")
    assert temp_states_1, "No temperature entity after first injection"

    synthetic_v2 = copy.deepcopy(synthetic)
    different_temp = struct.pack("<h", 2000)  # 20.00°C
    synthetic_v2["service_data"]["00002a6e-0000-1000-8000-00805f9b34fb"] = (
        different_temp.hex()
    )
    synthetic_v2["timestamp"] = synthetic["timestamp"] + 5.0

    service_info_2 = load_service_info(device, synthetic_v2)
    inject_bluetooth_service_info(hass, service_info_2)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    temp_states_2 = _find_sensor_states(hass, unit="°C")
    assert temp_states_2, "No temperature entity after second injection"
    state_after_second = temp_states_2[0].state

    try:
        assert abs(float(state_after_second) - 20.0) < 1.0, (
            f"Expected state ≈20.0°C after second injection, got {state_after_second!r}"
        )
    except ValueError:
        pytest.fail(f"Temperature state is not a number: {state_after_second!r}")


# ---------------------------------------------------------------------------
# 4. Unsupported device filtering — proprietary manufacturer data
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_proprietary_device_creates_no_entities(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Proprietary manufacturer data that the library cannot parse → no entities."""
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

    proprietary_address = "AA:BB:CC:DD:EE:40"

    ble_device = BLEDevice(
        address=proprietary_address,
        name="dummy-proprietary-beacon",
        details={},
    )
    adv_data = AdvertisementData(
        local_name="dummy-proprietary-beacon",
        manufacturer_data={
            0x1234: bytes([0x01, 0x01, 0xEF, 0xBE, 0xAD, 0xDE, 0x00, 0x00, 0x00])
        },
        service_data={},
        service_uuids=["12345678-1234-5678-1234-56789abcdef0"],
        rssi=-80,
        tx_power=None,
        platform_data=(),
    )
    service_info = BluetoothServiceInfoBleak(
        name="dummy-proprietary-beacon",
        address=proprietary_address,
        rssi=-80,
        manufacturer_data={
            0x1234: bytes([0x01, 0x01, 0xEF, 0xBE, 0xAD, 0xDE, 0x00, 0x00, 0x00])
        },
        service_data={},
        service_uuids=["12345678-1234-5678-1234-56789abcdef0"],
        source="local",
        device=ble_device,
        advertisement=adv_data,
        connectable=True,
        time=0.0,
        tx_power=None,
    )

    states_before = {s.entity_id for s in hass.states.async_all("sensor")}

    inject_bluetooth_service_info(hass, service_info)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    states_after = {s.entity_id for s in hass.states.async_all("sensor")}
    new_states = states_after - states_before

    assert not new_states, (
        f"Expected no entities for proprietary device, but got: {new_states}"
    )


# ---------------------------------------------------------------------------
# 5. Conftest fixtures through real dispatch path
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_conftest_battery_fixture_through_real_pipeline(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    mock_bluetooth_service_info_battery: Any,
) -> None:
    """Existing conftest battery fixture injected through real HA BT pipeline."""
    states_before = len(hass.states.async_all("sensor"))

    inject_bluetooth_service_info(hass, mock_bluetooth_service_info_battery)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    states_after = hass.states.async_all("sensor")
    assert len(states_after) > states_before, (
        "No entity created for battery fixture through real BT dispatch"
    )

    battery_states = _find_sensor_states(hass, unit="%")
    assert battery_states, "No battery (%) state created"
    assert battery_states[0].state == "75", (
        f"Expected battery=75%, got {battery_states[0].state!r}"
    )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_conftest_temperature_fixture_through_real_pipeline(
    hass: HomeAssistant,
    integration_entry: MockConfigEntry,
    mock_bluetooth_service_info_temperature: Any,
) -> None:
    """Existing conftest temperature fixture injected through real HA BT pipeline."""
    inject_bluetooth_service_info(hass, mock_bluetooth_service_info_temperature)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    temp_states = _find_sensor_states(hass, unit="°C")
    assert temp_states, "No temperature (°C) state created"
    try:
        assert abs(float(temp_states[0].state) - 24.04) < 0.1, (
            f"Expected temperature≈24.04°C, got {temp_states[0].state!r}"
        )
    except ValueError:
        pytest.fail(f"Temperature state is not a number: {temp_states[0].state!r}")


# ---------------------------------------------------------------------------
# 6. Smart watch — normal adverts (no service_data) produce no entities
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_smart_watch_normal_advert_no_service_data(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Normal smart watch adverts (no service_data) should not create entities.

    The smart watch normal advertisements carry manufacturer_data and service
    UUIDs but the service_data dict is empty.  Without parseable service_data,
    no entities should be created from the advert alone.  (Entity creation
    requires the GATT connection path — see test_integration_connected.py.)
    """
    fixture = load_fixture("esphome_smart_watch")
    device = list(fixture["devices"].values())[0]

    first_normal = next(a for a in device["advertisements"] if not a.get("_synthetic"))

    states_before = {s.entity_id for s in hass.states.async_all("sensor")}

    service_info = load_service_info(device, first_normal)
    inject_bluetooth_service_info(hass, service_info)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    states_after = {s.entity_id for s in hass.states.async_all("sensor")}
    new_states = states_after - states_before

    assert not new_states, (
        f"Expected no entities from normal advertisement (no service_data), "
        f"but got: {new_states}"
    )


# ---------------------------------------------------------------------------
# 7. Mesh node — write/notify-only characteristics → no entities
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("enable_bluetooth")
async def test_mesh_node_creates_no_entities(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Mesh node with write/notify-only characteristics → no entities created."""
    states_before = {s.entity_id for s in hass.states.async_all("sensor")}

    for service_info in iter_service_infos("esphome_mesh_node"):
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()

    await hass.async_block_till_done()

    states_after = {s.entity_id for s in hass.states.async_all("sensor")}
    new_states = states_after - states_before

    assert not new_states, (
        f"Expected no entities for mesh node (no readable characteristics), "
        f"but got: {new_states}"
    )


@pytest.mark.usefixtures("enable_bluetooth")
async def test_mesh_node_full_replay_no_entities(
    hass: HomeAssistant, integration_entry: MockConfigEntry
) -> None:
    """Full replay of all mesh node advertisements produces zero entities."""
    initial_count = len(hass.states.async_all("sensor"))

    for service_info in iter_service_infos("esphome_mesh_node"):
        inject_bluetooth_service_info(hass, service_info)
        await hass.async_block_till_done()

    final_count = len(hass.states.async_all("sensor"))
    assert final_count == initial_count, (
        f"Expected no new entities for mesh node, "
        f"but count changed from {initial_count} to {final_count}"
    )
