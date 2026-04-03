"""Bluetooth test helpers for fixture loading and advertisement injection.

Provides utilities for:
- Loading JSON fixture files captured from real BLE hardware
- Reconstructing real ``BluetoothServiceInfoBleak`` objects from fixture data
- Injecting advertisements through the real HomeAssistant Bluetooth pipeline
- Building mock ``BleakClient`` instances from fixture GATT data for
  connected-device (GATT probe + poll) test scenarios

JSON fixture format (produced by ``scripts/capture_ble_fixtures.py``):

.. code-block:: json

    {
      "captured_at": "2026-03-01T10:00:00+00:00",
      "duration": 30,
      "scanner_source": "hci0",
      "devices": {
        "AA:BB:CC:DD:EE:FF": {
          "address": "AA:BB:CC:DD:EE:FF",
          "name": "dummy-env-sensor",
          "gatt_services": [
            {
              "uuid": "0000180f-0000-1000-8000-00805f9b34fb",
              "handle": 52,
              "description": "Battery Service",
              "characteristics": [
                {
                  "uuid": "00002a19-0000-1000-8000-00805f9b34fb",
                  "handle": 53,
                  "description": "Battery Level",
                  "properties": ["read", "notify"],
                  "raw_value": "52"
                }
              ]
            }
          ],
          "advertisements": [
            {
              "timestamp": 0.123,
              "connectable": true,
              "rssi": -65,
              "local_name": "dummy-env-sensor",
              "manufacturer_data": {},
              "service_data": {
                "00002a19-0000-1000-8000-00805f9b34fb": "4b"
              },
              "service_uuids": ["00002a19-0000-1000-8000-00805f9b34fb"],
              "tx_power": null
            }
          ]
        }
      }
    }
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_get_advertisement_callback,
)
from homeassistant.core import HomeAssistant

# Fixtures live next to this file under tests/fixtures/
_FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# State query helpers
# ---------------------------------------------------------------------------


def find_sensor_states(
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
# Deserialisation helpers
# ---------------------------------------------------------------------------


def _hex_to_bytes(hex_str: str) -> bytes:
    """Decode a hex string back to bytes."""
    return bytes.fromhex(hex_str)


def _deserialise_manufacturer_data(md: dict[str, str]) -> dict[int, bytes]:
    """Restore manufacturer data: str keys → int, hex values → bytes."""
    return {int(k): _hex_to_bytes(v) for k, v in md.items()}


def _deserialise_service_data(sd: dict[str, str]) -> dict[str, bytes]:
    """Restore service data: hex values → bytes (keys remain str UUIDs)."""
    return {k: _hex_to_bytes(v) for k, v in sd.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file from ``tests/fixtures/``.

    Args:
        name: Filename with or without the ``.json`` extension.

    Returns:
        Parsed fixture dict.

    Raises:
        FileNotFoundError: When the fixture file does not exist.
    """
    if not name.endswith(".json"):
        name = f"{name}.json"
    path = _FIXTURE_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_service_info(
    device_data: dict[str, Any],
    adv_entry: dict[str, Any],
) -> BluetoothServiceInfoBleak:
    """Reconstruct a ``BluetoothServiceInfoBleak`` from fixture data.

    Builds a real ``BLEDevice`` and ``AdvertisementData`` (not MagicMocks)
    so that the object exercises the same code paths as production
    advertisements.

    Args:
        device_data: The device-level dict from the fixture (``address``, ``name``).
        adv_entry: One entry from ``device_data["advertisements"]``.

    Returns:
        A fully-populated ``BluetoothServiceInfoBleak`` ready for injection.
    """
    address: str = device_data["address"]
    name: str | None = device_data.get("name")
    rssi: int = adv_entry["rssi"]
    local_name: str | None = adv_entry.get("local_name")
    manufacturer_data = _deserialise_manufacturer_data(
        adv_entry.get("manufacturer_data", {})
    )
    service_data = _deserialise_service_data(adv_entry.get("service_data", {}))
    service_uuids: list[str] = adv_entry.get("service_uuids", [])
    tx_power: int | None = adv_entry.get("tx_power")

    ble_device = BLEDevice(
        address=address,
        name=name,
        details={},
    )

    advertisement_data = AdvertisementData(
        local_name=local_name,
        manufacturer_data=manufacturer_data,
        service_data=service_data,
        service_uuids=service_uuids,
        rssi=rssi,
        tx_power=tx_power,
        platform_data=(),
    )

    return BluetoothServiceInfoBleak(
        name=local_name or name or address,
        address=address,
        rssi=rssi,
        manufacturer_data=manufacturer_data,
        service_data=service_data,
        service_uuids=service_uuids,
        source="local",
        device=ble_device,
        advertisement=advertisement_data,
        connectable=adv_entry.get("connectable", True),
        time=adv_entry.get("timestamp", 0.0),
        tx_power=tx_power,
    )


def iter_service_infos(fixture_name: str) -> Iterator[BluetoothServiceInfoBleak]:
    """Yield all advertisements from a fixture sorted by timestamp.

    Suitable for sequential injection into the HA Bluetooth pipeline.

    Args:
        fixture_name: Name of the fixture file (with or without ``.json``).

    Yields:
        ``BluetoothServiceInfoBleak`` objects in ascending timestamp order.
    """
    fixture = load_fixture(fixture_name)
    entries: list[tuple[float, dict[str, Any], dict[str, Any]]] = []

    for device_data in fixture["devices"].values():
        for adv_entry in device_data["advertisements"]:
            entries.append((adv_entry.get("timestamp", 0.0), device_data, adv_entry))

    entries.sort(key=lambda x: x[0])

    for _ts, device_data, adv_entry in entries:
        yield load_service_info(device_data, adv_entry)


def inject_bluetooth_service_info(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
) -> None:
    """Inject a ``BluetoothServiceInfoBleak`` through the real HA Bluetooth pipeline.

    Routes through ``HomeAssistantBluetoothManager.scanner_adv_received`` so
    that ``BluetoothCallbackMatcher`` dispatch, ``BluetoothScanningMode.PASSIVE``
    handling, and all registered integration callbacks fire exactly as they
    would for a live advertisement.

    Requires the ``enable_bluetooth`` fixture to be active — the manager must
    be initialised before calling this function.

    Args:
        hass: Running HomeAssistant instance.
        service_info: Advertisement to inject.
    """
    callback = async_get_advertisement_callback(hass)
    callback(service_info)


# ---------------------------------------------------------------------------
# GATT mock helpers — build mock BleakClient from fixture gatt_services data
# ---------------------------------------------------------------------------


def _build_mock_bleak_service(svc_data: dict[str, Any]) -> MagicMock:
    """Build a mock ``BleakGATTService`` from fixture JSON.

    Returns a MagicMock that quacks like a ``BleakGATTService`` — with
    ``.uuid``, ``.handle``, ``.description``, and iterable
    ``.characteristics``.
    """
    mock_service = MagicMock()
    mock_service.uuid = svc_data["uuid"]
    mock_service.handle = svc_data["handle"]
    mock_service.description = svc_data.get("description", "")

    chars = []
    for char_data in svc_data.get("characteristics", []):
        mock_char = MagicMock()
        mock_char.uuid = char_data["uuid"]
        mock_char.handle = char_data["handle"]
        mock_char.description = char_data.get("description", "")
        mock_char.properties = char_data.get("properties", [])

        # Build descriptors if present
        descs = []
        for desc_data in char_data.get("descriptors", []):
            mock_desc = MagicMock()
            mock_desc.uuid = desc_data["uuid"]
            mock_desc.handle = desc_data["handle"]
            descs.append(mock_desc)
        mock_char.descriptors = descs

        chars.append(mock_char)

    mock_service.characteristics = chars
    return mock_service


def build_mock_bleak_client(
    device_data: dict[str, Any],
    *,
    mtu_size: int = 23,
    connect_side_effect: BaseException | None = None,
    disconnect_side_effect: BaseException | None = None,
) -> MagicMock:
    """Build a fully-populated mock ``BleakClient`` from fixture GATT data.

    The mock supports:
    - ``connect()`` / ``disconnect()`` (async no-ops unless side_effect given)
    - ``is_connected`` → True after connect
    - ``mtu_size`` → configurable (default 23)
    - ``services`` → iterable mock GATT services from fixture
    - ``read_gatt_char(uuid)`` → returns raw bytes from fixture
    - ``write_gatt_char(uuid, data)`` → async no-op
    - ``start_notify(uuid, callback)`` / ``stop_notify(uuid)`` → async no-ops
    - ``read_gatt_descriptor(handle)`` / ``write_gatt_descriptor(handle, data)``
    - ``pair()`` / ``unpair()`` → async no-ops

    Args:
        device_data: The device-level dict from the fixture, which must
            contain a ``gatt_services`` list.
        mtu_size: Simulated MTU size.
        connect_side_effect: Exception to raise on connect (simulates failure).
        disconnect_side_effect: Exception to raise on disconnect.

    Returns:
        A ``MagicMock`` suitable for patching ``BleakClient``.
    """
    gatt_services_data = device_data.get("gatt_services", [])

    # Build the raw-value lookup: UUID → bytes
    char_raw_values: dict[str, bytes] = {}
    for svc in gatt_services_data:
        for char in svc.get("characteristics", []):
            if char.get("raw_value") is not None:
                char_raw_values[char["uuid"]] = bytes.fromhex(char["raw_value"])

    # Build mock Bleak services
    mock_services = [_build_mock_bleak_service(s) for s in gatt_services_data]

    # Build the client mock
    client = MagicMock()
    client.is_connected = True
    client.mtu_size = mtu_size
    client.services = mock_services
    client.connect = AsyncMock(side_effect=connect_side_effect)
    client.disconnect = AsyncMock(side_effect=disconnect_side_effect)

    async def _mock_read_gatt_char(uuid_or_handle: str | int, **kwargs: Any) -> bytes:
        uuid_str = str(uuid_or_handle).lower()
        if uuid_str in char_raw_values:
            return char_raw_values[uuid_str]
        raise Exception(f"Characteristic {uuid_str} not readable in fixture")

    client.read_gatt_char = AsyncMock(side_effect=_mock_read_gatt_char)
    client.write_gatt_char = AsyncMock()
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.read_gatt_descriptor = AsyncMock(return_value=bytearray(b"\x00\x00"))
    client.write_gatt_descriptor = AsyncMock()
    client.pair = AsyncMock()
    client.unpair = AsyncMock()

    return client


@contextmanager
def mock_gatt_connection(
    device_data: dict[str, Any],
    address: str | None = None,
) -> Iterator[MagicMock]:
    """Context manager that patches the BLE stack with fixture GATT data.

    Patches ``establish_connection``, ``close_stale_connections_by_address``,
    and ``bluetooth.async_ble_device_from_address`` so the coordinator's GATT
    probe can connect, discover services, and read characteristics using the
    real raw bytes captured from the ESP32 — without any real hardware.

    Usage::

        with mock_gatt_connection(device_data) as mock_client:
            # trigger the GATT probe...
            assert mock_client.read_gatt_char.called

    Args:
        device_data: Device dict from fixture (must have ``gatt_services``).
        address: Override BLE address (defaults to fixture's address).

    Yields:
        The mock ``BleakClient`` instance.
    """
    addr = address or device_data["address"]
    mock_client = build_mock_bleak_client(device_data)

    mock_ble_device = BLEDevice(
        address=addr,
        name=device_data.get("name"),
        details={},
    )

    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=mock_ble_device,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.device_adapter.establish_connection",
            return_value=mock_client,
        ),
        patch(
            "custom_components.bluetooth_sig_devices.device_adapter.close_stale_connections_by_address",
            new_callable=AsyncMock,
        ),
    ):
        yield mock_client
