"""BLE advertisement capture script.

Scans real Bluetooth LE advertisements and serialises them as JSON fixture
files for use in pytest replay tests.  The serialisation format mirrors
habluetooth.storage so that the replay helpers can reconstruct real
``BLEDevice`` / ``AdvertisementData`` objects from disk.

Usage examples::

    # Capture all devices for 30 s
    python scripts/capture_ble_fixtures.py --duration 30 --output tests/fixtures/capture.json

    # Capture only ESPHome dummy devices
    python scripts/capture_ble_fixtures.py --duration 30 --filter-name dummy- --output tests/fixtures/esphome_devices.json

    # Capture + enrich with real GATT characteristic reads (for connectable GATT servers)
    python scripts/capture_ble_fixtures.py --duration 30 --filter-name dummy- --gatt-read --output tests/fixtures/esphome_devices.json

    # Capture a specific device by address
    python scripts/capture_ble_fixtures.py --duration 15 --filter-address AA:BB:CC:DD:EE:FF --output tests/fixtures/single.json

GATT enrichment (--gatt-read):
    For connectable GATT server devices (like ESP32 running esp32_ble_server),
    the advertisement packet contains only service UUIDs — no service data.
    With --gatt-read, after scanning the script connects to each captured
    device and reads all GATT characteristics registered in the
    bluetooth-sig-python library.  The read values are embedded back into
    the fixture as synthetic ``service_data`` entries (keyed by characteristic
    UUID) so that replay tests exercise the passive advertisement code path
    with real, measured values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Serialisation helpers (mirrors habluetooth.storage conventions)
# ---------------------------------------------------------------------------


def _bytes_to_hex(data: bytes) -> str:
    """Encode bytes as a lowercase hex string."""
    return data.hex()


def _serialise_manufacturer_data(md: dict[int, bytes]) -> dict[str, str]:
    """Serialise manufacturer data: int keys → str, bytes values → hex."""
    return {str(k): _bytes_to_hex(v) for k, v in md.items()}


def _serialise_service_data(sd: dict[str, bytes]) -> dict[str, str]:
    """Serialise service data: bytes values → hex (keys are already str UUIDs)."""
    return {k: _bytes_to_hex(v) for k, v in sd.items()}


def _serialise_advertisement(
    device: BLEDevice,
    advertisement: AdvertisementData,
    timestamp: float,
    connectable: bool,
) -> dict:  # type: ignore[type-arg]
    """Serialise a single advertisement to a JSON-safe dict."""
    return {
        "timestamp": round(timestamp, 6),
        "connectable": connectable,
        "rssi": advertisement.rssi,
        "local_name": advertisement.local_name,
        "manufacturer_data": _serialise_manufacturer_data(
            advertisement.manufacturer_data
        ),
        "service_data": _serialise_service_data(advertisement.service_data),
        "service_uuids": list(advertisement.service_uuids),
        "tx_power": advertisement.tx_power,
    }


# ---------------------------------------------------------------------------
# Capture logic
# ---------------------------------------------------------------------------


class AdvertisementCapture:
    """Collects BLE advertisements from a BleakScanner for a fixed duration."""

    def __init__(
        self,
        *,
        filter_name: str | None = None,
        filter_address: str | None = None,
    ) -> None:
        self._filter_name = filter_name
        self._filter_address = filter_address.upper() if filter_address else None
        # {address: {"device": {...}, "advertisements": [...]}}
        self._devices: dict[str, dict] = {}  # type: ignore[type-arg]
        self._start_time: float = 0.0

    def _matches_filter(self, device: BLEDevice) -> bool:
        """Return True if the device passes the configured filters."""
        if self._filter_address and device.address.upper() != self._filter_address:
            return False
        if self._filter_name:
            name = device.name or ""
            if self._filter_name.lower() not in name.lower():
                return False
        return True

    def detection_callback(
        self, device: BLEDevice, advertisement: AdvertisementData
    ) -> None:
        """bleak detection callback — called for every received advertisement."""
        if not self._matches_filter(device):
            return

        address = device.address.upper()
        relative_ts = time.monotonic() - self._start_time

        if address not in self._devices:
            self._devices[address] = {
                "address": address,
                "name": device.name,
                "advertisements": [],
            }
            _LOGGER.info("New device: %s (%s)", address, device.name)

        adv_entry = _serialise_advertisement(
            device, advertisement, relative_ts, connectable=True
        )
        self._devices[address]["advertisements"].append(adv_entry)

    async def run(self, duration: float, scanner_source: str) -> dict:  # type: ignore[type-arg]
        """Scan for *duration* seconds and return the serialised fixture dict."""
        self._start_time = time.monotonic()
        captured_at = datetime.now(UTC).isoformat()

        scanner = BleakScanner(detection_callback=self.detection_callback)
        _LOGGER.info("Starting BLE scan for %.0f seconds…", duration)

        async with scanner:
            await asyncio.sleep(duration)

        _LOGGER.info(
            "Scan complete — captured %d device(s), %d total advertisement(s)",
            len(self._devices),
            sum(len(d["advertisements"]) for d in self._devices.values()),
        )

        return {
            "captured_at": captured_at,
            "duration": duration,
            "scanner_source": scanner_source,
            "devices": self._devices,
        }


# ---------------------------------------------------------------------------
# GATT enrichment: connect and read real characteristic values
# ---------------------------------------------------------------------------

# These are the Bluetooth SIG characteristic UUIDs we know the library can
# parse.  We attempt to read each one and embed the raw bytes as service_data
# in the fixture so that replay tests exercise the passive-advertisement code
# path with real, measured values.
_KNOWN_CHAR_UUIDS: list[str] = [
    "00002a19-0000-1000-8000-00805f9b34fb",  # Battery Level
    "00002a6e-0000-1000-8000-00805f9b34fb",  # Temperature
    "00002a6f-0000-1000-8000-00805f9b34fb",  # Humidity
    "00002a37-0000-1000-8000-00805f9b34fb",  # Heart Rate Measurement
    "00002a38-0000-1000-8000-00805f9b34fb",  # Body Sensor Location
    "00002a2b-0000-1000-8000-00805f9b34fb",  # Current Time
    "00002a49-0000-1000-8000-00805f9b34fb",  # Blood Pressure Feature
    "00002a1c-0000-1000-8000-00805f9b34fb",  # Temperature Measurement
    "00002a56-0000-1000-8000-00805f9b34fb",  # Digital
    "00002a58-0000-1000-8000-00805f9b34fb",  # Analog
]


async def _gatt_read_device(address: str, name: str | None) -> dict[str, str]:
    """Connect to *address* and read all known SIG characteristic UUIDs.

    Returns a dict mapping characteristic UUID → hex-encoded raw value for
    each characteristic that was successfully read.
    """
    service_data: dict[str, str] = {}
    _LOGGER.info("GATT connect → %s (%s)…", address, name)

    try:
        async with BleakClient(address, timeout=10.0) as client:
            _LOGGER.debug("Connected to %s", address)

            # Discover which services/characteristics the device actually has
            services_map: dict[str, Any] = {}
            for service in client.services:
                for char in service.characteristics:
                    services_map[char.uuid.lower()] = char

            for uuid in _KNOWN_CHAR_UUIDS:
                if uuid not in services_map:
                    continue
                char = services_map[uuid]
                if "read" not in char.properties:
                    _LOGGER.debug("  %s — not readable, skipping", uuid)
                    continue
                try:
                    raw = await client.read_gatt_char(char)
                    service_data[uuid] = raw.hex()
                    _LOGGER.info("  %s → %s (raw: %s)", uuid, name, raw.hex())
                except Exception as err:
                    _LOGGER.debug("  %s read failed: %s", uuid, err)

    except Exception as err:
        _LOGGER.warning("GATT read failed for %s: %s", address, err)

    return service_data


async def enrich_fixture_with_gatt(fixture: dict[str, Any]) -> None:  # type: ignore[type-arg]
    """Connect to each captured device and embed GATT reads as service_data.

    Mutates *fixture* in-place: for each device, appends a synthetic
    advertisement whose ``service_data`` contains the real characteristic
    values read via GATT connection.  The timestamp for this synthetic entry
    is set to the duration+1 so it sorts last.
    """
    duration: float = fixture.get("duration", 0.0)

    for address, device_data in fixture["devices"].items():
        name: str | None = device_data.get("name")
        service_data = await _gatt_read_device(address, name)

        if not service_data:
            _LOGGER.info("No GATT data read from %s, skipping enrichment", address)
            continue

        # Collect service_uuids already seen in other advertisements
        existing_uuids: set[str] = set()
        for adv in device_data["advertisements"]:
            existing_uuids.update(adv.get("service_uuids", []))

        gatt_advertisement = {
            "timestamp": round(duration + 1.0, 3),
            "connectable": True,
            "rssi": device_data["advertisements"][-1]["rssi"]
            if device_data["advertisements"]
            else -70,
            "local_name": name,
            "manufacturer_data": {},
            "service_data": service_data,
            "service_uuids": sorted(existing_uuids),
            "tx_power": None,
            "_synthetic": True,
            "_source": "gatt_read",
        }

        device_data["advertisements"].append(gatt_advertisement)
        _LOGGER.info(
            "Enriched %s with %d GATT characteristic(s): %s",
            address,
            len(service_data),
            list(service_data.keys()),
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture BLE advertisements and save as JSON test fixtures.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="How long to scan (default: 30 s)",
    )
    parser.add_argument(
        "--filter-name",
        metavar="SUBSTRING",
        help="Only capture devices whose name contains this substring (case-insensitive)",
    )
    parser.add_argument(
        "--filter-address",
        metavar="MAC",
        help="Only capture a specific device by MAC address",
    )
    parser.add_argument(
        "--output",
        default="tests/fixtures/capture.json",
        metavar="PATH",
        help="Output JSON file path (default: tests/fixtures/capture.json)",
    )
    parser.add_argument(
        "--scanner-source",
        default="hci0",
        metavar="SOURCE",
        help="Scanner source label to embed in the fixture (default: hci0)",
    )
    parser.add_argument(
        "--gatt-read",
        action="store_true",
        help=(
            "After scanning, connect to each captured device via GATT and read "
            "all known SIG characteristic UUIDs.  The read values are embedded "
            "as a synthetic service_data advertisement so that replay tests "
            "exercise the passive-advertisement code path with real values."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    return parser


async def _main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    capture = AdvertisementCapture(
        filter_name=args.filter_name,
        filter_address=args.filter_address,
    )

    fixture = await capture.run(
        duration=args.duration,
        scanner_source=args.scanner_source,
    )

    if args.gatt_read:
        _LOGGER.info("GATT enrichment mode — connecting to captured devices…")
        await enrich_fixture_with_gatt(fixture)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(fixture, fh, indent=2)

    print(f"Fixture written to {output_path}")
    print(f"  {len(fixture['devices'])} device(s) captured")
    for addr, dev in fixture["devices"].items():
        n_adv = len(dev["advertisements"])
        n_gatt = sum(1 for a in dev["advertisements"] if a.get("_synthetic"))
        print(
            f"  {addr}: {dev['name']} — {n_adv} advertisement(s) ({n_gatt} synthetic GATT)"
        )


if __name__ == "__main__":
    asyncio.run(_main())
