"""Constants for the Bluetooth SIG Devices integration."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any, NamedTuple, TypedDict

from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic

# ---------------------------------------------------------------------------
# Strict type aliases
# ---------------------------------------------------------------------------
type BLEAddress = str

DOMAIN = "bluetooth_sig_devices"

# Configuration keys
CONF_DEVICE_ADDRESS = "address"
CONF_POLL_INTERVAL = "poll_interval"

# GATT connection defaults
DEFAULT_POLL_INTERVAL = timedelta(minutes=5)
MIN_POLL_INTERVAL_SECONDS = 30
MAX_POLL_INTERVAL_SECONDS = 86400  # 24 hours
DEFAULT_CONNECTION_TIMEOUT = 30.0
DEFAULT_READ_TIMEOUT = 10.0

# Probe configuration
MAX_PROBE_FAILURES = 3
MAX_CONCURRENT_PROBES = 2

# Services that should NOT count as "parseable SIG data"
# These are standard BLE services that any BLE monitor can expose
# The actual UUIDs are retrieved from the bluetooth-sig library at runtime
EXCLUDED_SERVICE_NAMES: frozenset[str] = frozenset(
    {
        "GAP",  # Generic Access Profile - basic device identity
        "GATT",  # Generic Attribute Profile - protocol infrastructure
    }
)

# --- BLE address classification ---


class BLEAddressType(Enum):
    """Classification of BLE address types.

    BLE addresses are classified based on the Bluetooth Core Specification
    (Vol 6, Part B, Section 1.3).  Random addresses are sub-classified by
    the two most-significant bits of the first octet:

    - 11xxxxxx (0xC0-0xFF) → Random Static (stable per power cycle or lifetime)
    - 01xxxxxx (0x40-0x7F) → Resolvable Private (rotates every ~15 minutes)
    - 00xxxxxx (0x00-0x3F) → Non-Resolvable Private (rotates, unresolvable)
    - 10xxxxxx (0x80-0xBF) → Reserved (treated as unknown)
    """

    PUBLIC = "public"
    RANDOM_STATIC = "random_static"
    RESOLVABLE_PRIVATE = "resolvable_private"
    NON_RESOLVABLE_PRIVATE = "non_resolvable_private"
    UNKNOWN = "unknown"


# Address types considered stable enough to track with MAC as identity.
# UNKNOWN is included because when BlueZ metadata is absent we assume stable.
STATIC_ADDRESS_TYPES: frozenset[BLEAddressType] = frozenset(
    {
        BLEAddressType.PUBLIC,
        BLEAddressType.RANDOM_STATIC,
        BLEAddressType.UNKNOWN,
    }
)

# --- Tracking set bounds (prevent unbounded memory growth) ---
MAX_SEEN_DEVICES = 2048
MAX_REJECTED_DEVICES = 4096

# --- Stale device cleanup ---
STALE_DEVICE_CLEANUP_INTERVAL = timedelta(minutes=15)
STALE_DEVICE_TIMEOUT_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Structured data types
# ---------------------------------------------------------------------------


class CharacteristicSource(Enum):
    """How a characteristic was discovered.

    Mirrors ``bluetooth_sig.advertising.DataSource`` for the passive
    advertisement path and adds ``GATT`` for the active connection path.
    """

    ADVERTISEMENT = "advertisement"
    MANUFACTURER = "manufacturer"
    GATT = "gatt"


class DiscoveredCharacteristic(NamedTuple):
    """A discovered characteristic's UUID and human-readable name."""

    characteristic: BaseCharacteristic[Any]
    source: CharacteristicSource = CharacteristicSource.ADVERTISEMENT


class DiscoveryData(TypedDict):
    """Data passed to ``discovery_flow.async_create_flow``."""

    address: BLEAddress
    name: str
    characteristics: str
    manufacturer: str


class GATTProbeSnapshotData(TypedDict):
    """Diagnostics snapshot for a single GATT probe result."""

    parseable_characteristics: int
    has_support: bool
    probe_failures: int


class DeviceStatistics(TypedDict):
    """Diagnostics snapshot of coordinator-level statistics."""

    tracked_devices: int
    active_processor_coordinators: int
    gatt_probed_devices: int
    pending_probes: int
    seen_devices: int
    rejected_devices: int
    discovery_triggered: int
    filtered_ephemeral_count: int


class DiagnosticsSnapshot(TypedDict):
    """Complete diagnostics snapshot returned by the coordinator."""

    device_statistics: DeviceStatistics
    gatt_probe_results: dict[BLEAddress, GATTProbeSnapshotData]
    probe_failures: dict[BLEAddress, int]
    known_characteristics: dict[BLEAddress, list[str]]
