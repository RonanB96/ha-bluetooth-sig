"""Device validation for Bluetooth SIG Devices integration.

Provides BLE address classification (public / random-static / RPA / NRPA)
and the ``GATTProbeResult`` data container used by the GATT manager.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bluetooth_sig.types.uuid import BluetoothUUID

from .const import STATIC_ADDRESS_TYPES, BLEAddressType

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BLE address classification
# ---------------------------------------------------------------------------


def _classify_random_address(address: str) -> BLEAddressType:
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

    When neither metadata format is present (e.g. test mocks) the function
    returns ``UNKNOWN`` which is treated as stable by callers.
    """
    device = service_info.device

    is_random = False

    if hasattr(device, "details") and isinstance(device.details, dict):
        details: dict = device.details

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
        # No metadata (mock, unknown backend) — conservatively assume stable.
        return BLEAddressType.UNKNOWN

    # Random address — classify sub-type from the first octet.
    return _classify_random_address(service_info.address)


def is_static_address(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the device has a static (trackable) BLE address.

    Static addresses include Public, Random Static, and Unknown (when
    BlueZ metadata is not available we assume the address is stable).
    Resolvable Private and Non-Resolvable Private addresses are rejected.
    """
    return classify_ble_address(service_info) in STATIC_ADDRESS_TYPES


@dataclass
class GATTProbeResult:
    """Result from probing a device's GATT services.

    This is a simple data container for probe results, used to track
    what characteristics a device supports.
    """

    address: str
    name: str | None = None
    parseable_count: int = 0
    supported_char_uuids: list[BluetoothUUID] = field(default_factory=list)

    def has_support(self) -> bool:
        """Check if device has any parseable characteristics."""
        return self.parseable_count > 0
