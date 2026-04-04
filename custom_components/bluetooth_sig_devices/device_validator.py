"""Device validation for Bluetooth SIG Devices integration.

Provides BLE address classification (public / random-static / RPA / NRPA)
and the ``GATTProbeResult`` data container used by the GATT manager.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from bluetooth_sig.types.gatt_enums import GattProperty
from bluetooth_sig.types.uuid import BluetoothUUID

from .const import STATIC_ADDRESS_TYPES, BLEAddress, BLEAddressType

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)

# Address types that indicate ephemeral (rotating) addresses.
# Used as a fallback heuristic when no BlueZ/ESPHome metadata is available.
_EPHEMERAL_ADDRESS_TYPES: frozenset[BLEAddressType] = frozenset(
    {
        BLEAddressType.RESOLVABLE_PRIVATE,
        BLEAddressType.NON_RESOLVABLE_PRIVATE,
    }
)


def _empty_characteristic_properties() -> dict[str, GattProperty]:
    """Return an empty characteristic-property mapping."""
    return {}


# ---------------------------------------------------------------------------
# BLE address classification
# ---------------------------------------------------------------------------


def _classify_random_address(address: BLEAddress) -> BLEAddressType:
    """Classify a random BLE address sub-type from the first octet.

    Per the Bluetooth Core Spec (Vol 6, Part B, §1.3) the two
    most-significant bits of the first MAC octet determine the sub-type:

    - ``11`` (0xC0–0xFF) → Random Static
    - ``01`` (0x40–0x7F) → Resolvable Private (RPA)
    - ``00`` (0x00–0x3F) → Non-Resolvable Private (NRPA)
    - ``10`` (0x80–0xBF) → Reserved
    """
    try:
        first_byte = int(address.split(":")[0], 16)
    except (ValueError, IndexError):
        return BLEAddressType.UNKNOWN

    top_bits = (first_byte >> 6) & 0x03
    if top_bits == 0b11:  # 0xC0-0xFF
        return BLEAddressType.RANDOM_STATIC
    if top_bits == 0b01:  # 0x40-0x7F
        return BLEAddressType.RESOLVABLE_PRIVATE
    if top_bits == 0b00:  # 0x00-0x3F
        return BLEAddressType.NON_RESOLVABLE_PRIVATE
    # 0b10 is reserved in the BLE spec
    return BLEAddressType.UNKNOWN


# ESPHome proxy ``address_type`` integer values
# (from aioesphomeapi / bleak-esphome).
_ESPHOME_ADDRESS_TYPE_RANDOM = 1


def classify_ble_address(
    service_info: BluetoothServiceInfoBleak,
) -> BLEAddressType:
    """Classify a BLE address as public, random-static, RPA, NRPA, or unknown.

    Checks two metadata formats:

    1. **BlueZ** (native Linux adapter):
       ``device.details["props"]["AddressType"]`` → ``"public"`` / ``"random"``
    2. **ESPHome Bluetooth proxy** (via bleak-esphome):
       ``device.details["address_type"]`` → ``0`` (public) / ``1`` (random)

    If the address is reported as random, the two most-significant bits of
    the first MAC octet determine the sub-type per the Bluetooth Core Spec
    (Vol 6, Part B, §1.3).

    When neither metadata format is present, a **MAC heuristic** is applied:
    the first octet is checked against the Bluetooth Core Spec random-address
    ranges.  Addresses whose first byte falls in the RPA (0x40–0x7F) or NRPA
    (0x00–0x3F) range are classified as ephemeral — preventing wasted GATT
    probes and spurious discovery flows on rotating addresses.  Addresses in
    the Random Static (0xC0–0xFF) or reserved (0x80–0xBF) range return
    ``UNKNOWN`` (treated as stable).
    """
    device = service_info.device

    is_random = False

    if hasattr(device, "details") and isinstance(device.details, dict):
        details: dict[str, Any] = device.details

        # --- BlueZ format: {"props": {"AddressType": "random"|"public"}} ---
        props = details.get("props", {})
        if isinstance(props, dict):
            addr_type_str = props.get("AddressType", "")
            if addr_type_str == "random":
                is_random = True
            elif addr_type_str == "public":
                return BLEAddressType.PUBLIC

        # --- ESPHome proxy format: {"address_type": 0|1} ---
        if not is_random and "address_type" in details:
            esphome_addr_type = details["address_type"]
            if esphome_addr_type == _ESPHOME_ADDRESS_TYPE_RANDOM:
                is_random = True
            else:
                # ESPHome reports public (0)
                return BLEAddressType.PUBLIC

    if not is_random:
        # No metadata available — apply MAC-based heuristic as a fallback.
        # Per BT Core Spec §1.3, addresses in the RPA (0x40–0x7F) and NRPA
        # (0x00–0x3F) ranges are overwhelmingly ephemeral in practice.  Treat
        # them as such to avoid wasted GATT probes and spurious discovery
        # flows. Random Static and reserved ranges stay UNKNOWN (stable).
        heuristic = _classify_random_address(service_info.address)
        if heuristic in _EPHEMERAL_ADDRESS_TYPES:
            _LOGGER.debug(
                "No BLE address metadata for %s — MAC heuristic classifies "
                "as %s (ephemeral, will be filtered)",
                service_info.address,
                heuristic.value,
            )
            return heuristic
        return BLEAddressType.UNKNOWN

    # Random address — classify sub-type from the first octet.
    return _classify_random_address(service_info.address)


def is_static_address(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the device has a static (trackable) BLE address.

    Static addresses include Public, Random Static, and Unknown (when
    BlueZ metadata is not available and the MAC heuristic does not
    indicate an ephemeral range).  Resolvable Private and
    Non-Resolvable Private addresses — whether confirmed by metadata
    or inferred by MAC heuristic — are rejected.
    """
    return classify_ble_address(service_info) in STATIC_ADDRESS_TYPES


@dataclass
class GATTProbeResult:
    """Result from probing a device's GATT services.

    This is a simple data container for probe results, used to track
    what characteristics a device supports.
    """

    address: BLEAddress
    name: str | None = None
    parseable_count: int = 0
    supported_char_uuids: tuple[BluetoothUUID, ...] = ()
    manufacturer_name: str | None = None
    characteristic_properties: dict[str, GattProperty] = field(
        default_factory=_empty_characteristic_properties
    )

    def has_support(self) -> bool:
        """Check if device has any parseable characteristics."""
        return self.parseable_count > 0
