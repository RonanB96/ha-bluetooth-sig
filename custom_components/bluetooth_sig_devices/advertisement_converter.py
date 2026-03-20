"""Stateless advertisement conversion for Bluetooth SIG Devices.

Pure-function module that converts Home Assistant
``BluetoothServiceInfoBleak`` objects into the ``bluetooth-sig-python``
library's ``AdvertisementData``.

No Home Assistant runtime state is required — every function accepts
its inputs explicitly and returns a result.

Functions
---------
convert_advertisement
    Three-tier conversion: raw PDU → manual fallback → platform enrichment.
get_manufacturer_name
    Extract manufacturer name from parsed ``AdvertisementData``.
get_model_name
    Extract model name from parsed ``AdvertisementData``.
"""

from __future__ import annotations

import enum
import logging
from typing import Any

from bluetooth_sig.advertising import PayloadContext, parse_advertising_payloads
from bluetooth_sig.advertising.pdu_parser import AdvertisingPDUParser
from bluetooth_sig.registry.core.appearance_values import appearance_values_registry
from bluetooth_sig.registry.core.class_of_device import class_of_device_registry
from bluetooth_sig.types.advertising import (
    AdvertisementData,
    AdvertisingDataStructures,
    BLEAdvertisingFlags,
)
from bluetooth_sig.types.appearance import AppearanceData
from bluetooth_sig.types.company import ManufacturerData
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_PDU_PARSER = AdvertisingPDUParser()

_LOGGER = logging.getLogger(__name__)


class ConversionTier(enum.Enum):
    """Which conversion strategy produced the ad_structures."""

    RAW_PDU = "raw_pdu"
    MANUAL = "manual"


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def convert_advertisement(
    service_info: BluetoothServiceInfoBleak,
) -> AdvertisementData:
    """Convert HA ``BluetoothServiceInfoBleak`` to library ``AdvertisementData``.

    Uses a three-tier strategy for the richest possible data:

    1. **Raw PDU** — if ``service_info.raw`` contains bytes, parse them
       with ``AdvertisingPDUParser`` for real flags, appearance, etc.
    2. **Manual fallback** — build ``AdvertisingDataStructures`` from the
       pre-parsed ``BluetoothServiceInfoBleak`` fields.
    3. **Platform enrichment** — if BlueZ ``device.details["props"]``
       contains ``Appearance``, ``Class``, or ``AdvertisingFlags``, merge
       them into the result.
    """
    # Tier 1: raw PDU parsing (richest data)
    ad_structures = _try_parse_raw(service_info)
    tier: ConversionTier | None = (
        ConversionTier.RAW_PDU if ad_structures is not None else None
    )

    # Tier 2: manual struct building from pre-parsed fields
    if ad_structures is None:
        ad_structures = _build_ad_structures(service_info)
        tier = ConversionTier.MANUAL

    # Tier 3: enrich from BlueZ Device1 props when available
    _enrich_from_platform_details(
        ad_structures,
        service_info,
        raw_pdu_parsed=tier is ConversionTier.RAW_PDU,
    )

    # Always run interpreters for vendor-specific data
    interpreted_data, interpreter_name = _parse_payloads(service_info)

    return AdvertisementData(
        ad_structures=ad_structures,
        interpreted_data=interpreted_data,
        interpreter_name=interpreter_name,
        rssi=service_info.rssi,
    )


def get_manufacturer_name(advertisement: AdvertisementData) -> str | None:
    """Extract manufacturer name from parsed advertisement data."""
    if advertisement.ad_structures.core.manufacturer_data:
        for mfr_data in advertisement.ad_structures.core.manufacturer_data.values():
            if (
                mfr_data.company
                and mfr_data.company.name
                and not mfr_data.company.name.startswith("Unknown")
            ):
                return mfr_data.company.name
    if advertisement.interpreter_name:
        return advertisement.interpreter_name
    return None


def get_model_name(advertisement: AdvertisementData) -> str | None:
    """Extract model name from parsed advertisement data."""
    local_name = advertisement.ad_structures.core.local_name
    if local_name:
        return local_name
    return None


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _try_parse_raw(
    service_info: BluetoothServiceInfoBleak,
) -> AdvertisingDataStructures | None:
    """Attempt to parse raw advertisement PDU bytes.

    Returns parsed ``AdvertisingDataStructures`` with real BLE flags,
    appearance, tx_power etc., or ``None`` if raw bytes are unavailable
    or parsing fails.
    """
    raw: bytes | None = service_info.raw
    if not raw:
        return None

    try:
        parsed = _PDU_PARSER.parse_advertising_data(raw)
        ad_structures = parsed.ad_structures

        # Address is not in the AD payload — supplement from service_info
        if not ad_structures.directed.le_bluetooth_device_address:
            ad_structures.directed.le_bluetooth_device_address = service_info.address

        return ad_structures
    except (ValueError, TypeError, KeyError, AttributeError):
        _LOGGER.warning(
            "Raw PDU parse failed for %s, falling back",
            service_info.address,
            exc_info=True,
        )
        return None


def _enrich_from_platform_details(
    ad_structures: AdvertisingDataStructures,
    service_info: BluetoothServiceInfoBleak,
    *,
    raw_pdu_parsed: bool,
) -> None:
    """Enrich ad_structures from BlueZ Device1 D-Bus properties.

    BlueZ exposes ``Appearance`` (uint16), ``Class`` (uint32), and
    ``AdvertisingFlags`` (bytes) via ``device.details["props"]``.
    ESPHome devices only have ``{"address_type": int}`` — this function
    is a no-op for them.
    """
    try:
        details: Any = service_info.device.details
        if not isinstance(details, dict):
            return

        props: dict[str, Any] | None = details.get("props")
        if not isinstance(props, dict):
            return

        # Appearance → AppearanceData with full category/subcategory resolution
        if ad_structures.properties.appearance is None:
            appearance_val = props.get("Appearance")
            if isinstance(appearance_val, int):
                info = appearance_values_registry.get_appearance_info(appearance_val)
                ad_structures.properties.appearance = AppearanceData(
                    raw_value=appearance_val, info=info
                )

        # Class of Device → full major/minor/service class decode
        if ad_structures.properties.class_of_device is None:
            class_val = props.get("Class")
            if isinstance(class_val, int) and class_val != 0:
                ad_structures.properties.class_of_device = (
                    class_of_device_registry.decode_class_of_device(class_val)
                )

        # Real advertising flags from BlueZ — skip when raw PDU
        # already provided authentic flags; otherwise merge into
        # existing flags (add bits, never strip)
        if not raw_pdu_parsed:
            adv_flags_raw = props.get("AdvertisingFlags")
            if isinstance(adv_flags_raw, (bytes, bytearray)) and adv_flags_raw:
                bluez_flags = BLEAdvertisingFlags(adv_flags_raw[0])
                ad_structures.properties.flags |= bluez_flags

    except (AttributeError, KeyError, TypeError):
        _LOGGER.warning(
            "Platform detail enrichment failed for %s",
            service_info.address,
            exc_info=True,
        )


def _build_ad_structures(
    service_info: BluetoothServiceInfoBleak,
) -> AdvertisingDataStructures:
    """Build ``AdvertisingDataStructures`` from HA service info.

    Pure structural mapping — no library interpreter invocation.
    """
    # Manufacturer data → ManufacturerData objects with resolved company names
    manufacturer_data: dict[int, ManufacturerData] = {}
    if service_info.manufacturer_data:
        for company_id, payload in service_info.manufacturer_data.items():
            manufacturer_data[company_id] = ManufacturerData.from_id_and_payload(
                company_id, payload
            )

    # Service data → BluetoothUUID-keyed dict
    service_data: dict[BluetoothUUID, bytes] = {}
    if service_info.service_data:
        for uuid_str, data in service_info.service_data.items():
            service_data[BluetoothUUID(uuid_str)] = data

    # Service UUIDs
    service_uuids: list[BluetoothUUID] = []
    if service_info.service_uuids:
        service_uuids = [BluetoothUUID(u) for u in service_info.service_uuids]

    return AdvertisingDataStructures.from_common_fields(
        manufacturer_data=manufacturer_data,
        service_data=service_data,
        service_uuids=service_uuids,
        local_name=service_info.name or "",
        tx_power=service_info.tx_power or 0,
        address=service_info.address,
        connectable=service_info.connectable,
    )


def _parse_payloads(
    service_info: BluetoothServiceInfoBleak,
) -> tuple[Any, str | None]:
    """Invoke library interpreters on advertisement payloads.

    Returns:
        ``(interpreted_data, interpreter_name)`` or ``(None, None)``.
    """
    mfr_data_for_parse: dict[int, bytes] = {}
    if service_info.manufacturer_data:
        for company_id, payload in service_info.manufacturer_data.items():
            mfr_data_for_parse[company_id] = payload

    svc_data_for_parse: dict[BluetoothUUID, bytes] = {}
    if service_info.service_data:
        for uuid_str, data in service_info.service_data.items():
            svc_data_for_parse[BluetoothUUID(uuid_str)] = data

    if not mfr_data_for_parse and not svc_data_for_parse:
        return None, None

    try:
        context = PayloadContext(
            mac_address=service_info.address,
            rssi=service_info.rssi or 0,
            timestamp=service_info.time,
        )
        parsed_results = parse_advertising_payloads(
            manufacturer_data=mfr_data_for_parse,
            service_data=svc_data_for_parse,
            context=context,
        )
        if parsed_results:
            interpreted_data = parsed_results[0]
            interpreter_name = type(interpreted_data).__name__
            return interpreted_data, interpreter_name
    except (ValueError, TypeError, KeyError) as exc:
        _LOGGER.warning(
            "Failed to parse advertising data for %s: %s",
            service_info.address,
            exc,
        )

    return None, None
