"""Advertisement conversion and tracking for Bluetooth SIG Devices.

Encapsulates:

- HA ``BluetoothServiceInfoBleak`` → library ``AdvertisementData`` conversion
  (structural mapping **and** interpreter parsing, split into two internal steps)
- Per-device advertisement state: latest advertisement, RSSI, callbacks
- Static helpers for extracting manufacturer/model names from parsed data

The class is composed into ``HomeAssistantBluetoothAdapter`` (which delegates
protocol-mandated advertisement methods here) and used directly by
``BluetoothSIGCoordinator`` for data-pipeline helpers.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
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
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant

from .const import BLEAddress

_PDU_PARSER = AdvertisingPDUParser()

_LOGGER = logging.getLogger(__name__)


class ConversionTier(enum.Enum):
    """Which conversion strategy produced the ad_structures."""

    RAW_PDU = "raw_pdu"
    MANUAL = "manual"


class AdvertisementManager:
    """Manages advertisement conversion, tracking, and callbacks for a device.

    **Static usage** (conversion only — no instance needed)::

        ad = AdvertisementManager.convert_advertisement(service_info)

    **Instance usage** (per-device tracking)::

        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF", hass=hass)
        mgr.on_advertisement_received(ad)
        latest = await mgr.get_latest_advertisement(refresh=True)
    """

    def __init__(
        self,
        address: BLEAddress,
        *,
        hass: HomeAssistant | None = None,
    ) -> None:
        """Initialise the advertisement manager.

        Args:
            address: Bluetooth device address (MAC address).
            hass: Home Assistant instance (needed for refreshing adverts).

        """
        self._address = address
        self._hass = hass

        # Per-device tracking state
        self._latest_advertisement: AdvertisementData | None = None
        self._disconnected_callback: Callable[[], None] | None = None
        self._advertisement_callbacks: list[Callable[[AdvertisementData], None]] = []

    @property
    def connectable(self) -> bool:
        """Return whether the device last advertised as connectable.

        Derived from the ``LE_GENERAL_DISCOVERABLE_MODE`` flag in the
        latest advertisement — no separate state to keep in sync.
        """
        if self._latest_advertisement is None:
            return False
        flags = self._latest_advertisement.ad_structures.properties.flags
        return bool(flags & BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE)

    # ------------------------------------------------------------------
    # Conversion — classmethod API (no instance required)
    # ------------------------------------------------------------------

    @classmethod
    def convert_advertisement(
        cls, advertisement: BluetoothServiceInfoBleak
    ) -> AdvertisementData:
        """Convert HA ``BluetoothServiceInfoBleak`` to library ``AdvertisementData``.

        Uses a three-tier strategy for the richest possible data:

        1. **Raw PDU** — if ``service_info.raw`` contains bytes (BlueZ side
           channel or ESPHome raw path), parse them with
           ``AdvertisingPDUParser`` for real flags, appearance, tx_power, etc.
        2. **Manual fallback** — build ``AdvertisingDataStructures`` from the
           pre-parsed ``BluetoothServiceInfoBleak`` fields.
        3. **Platform enrichment** — if BlueZ ``device.details["props"]``
           contains ``Appearance``, ``Class``, or ``AdvertisingFlags``, merge
           them into the result.

        Args:
            advertisement: Home Assistant's Bluetooth service info.

        Returns:
            ``AdvertisementData`` compatible with bluetooth-sig-python.

        """
        service_info = advertisement

        # Tier 1: raw PDU parsing (richest data)
        ad_structures = cls._try_parse_raw(service_info)
        tier: ConversionTier | None = (
            ConversionTier.RAW_PDU if ad_structures is not None else None
        )

        # Tier 2: manual struct building from pre-parsed fields
        if ad_structures is None:
            ad_structures = cls._build_ad_structures(service_info)
            tier = ConversionTier.MANUAL

        # Tier 3: enrich from BlueZ Device1 props when available
        cls._enrich_from_platform_details(
            ad_structures,
            service_info,
            raw_pdu_parsed=tier is ConversionTier.RAW_PDU,
        )

        # Always run interpreters for vendor-specific data
        interpreted_data, interpreter_name = cls._parse_payloads(service_info)

        return AdvertisementData(
            ad_structures=ad_structures,
            interpreted_data=interpreted_data,
            interpreter_name=interpreter_name,
            rssi=service_info.rssi,
        )

    # ------------------------------------------------------------------
    # Internal conversion helpers
    # ------------------------------------------------------------------

    @classmethod
    def _try_parse_raw(
        cls, service_info: BluetoothServiceInfoBleak
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
                ad_structures.directed.le_bluetooth_device_address = (
                    service_info.address
                )

            return ad_structures
        except Exception:
            _LOGGER.debug(
                "Raw PDU parse failed for %s, falling back",
                service_info.address,
                exc_info=True,
            )
            return None

    @classmethod
    def _enrich_from_platform_details(
        cls,
        ad_structures: AdvertisingDataStructures,
        service_info: BluetoothServiceInfoBleak,
        *,
        raw_pdu_parsed: bool,
    ) -> None:
        """Enrich ad_structures from BlueZ Device1 D-Bus properties.

        BlueZ exposes ``Appearance`` (uint16), ``Class`` (uint32), and
        ``AdvertisingFlags`` (bytes) via ``device.details["props"]``.
        ESPHome devices only have ``{"address_type": int}`` — this method
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
                    info = appearance_values_registry.get_appearance_info(
                        appearance_val
                    )
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

        except Exception:
            _LOGGER.warning(
                "Platform detail enrichment failed for %s",
                service_info.address,
                exc_info=True,
            )

    @classmethod
    def _build_ad_structures(
        cls, service_info: BluetoothServiceInfoBleak
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

    @classmethod
    def _parse_payloads(
        cls, service_info: BluetoothServiceInfoBleak
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
        except Exception as exc:
            _LOGGER.warning(
                "Failed to parse advertising data for %s: %s",
                service_info.address,
                exc,
            )

        return None, None

    # ------------------------------------------------------------------
    # Per-device advertisement tracking (instance methods)
    # ------------------------------------------------------------------

    def set_hass(self, hass: HomeAssistant) -> None:
        """Set the Home Assistant instance for refresh support."""
        self._hass = hass

    def set_disconnected_callback(self, callback: Callable[[], None] | None) -> None:
        """Set the callback for disconnection events."""
        self._disconnected_callback = callback

    def fire_disconnected(self) -> None:
        """Fire the disconnected callback if registered."""
        if self._disconnected_callback:
            self._disconnected_callback()

    def on_advertisement_received(self, advertisement: AdvertisementData) -> None:
        """Handle receiving an advertisement."""
        self._latest_advertisement = advertisement
        for cb in list(self._advertisement_callbacks):
            cb(advertisement)

    def register_advertisement_callback(
        self, callback: Callable[[AdvertisementData], None]
    ) -> None:
        """Register a callback for advertisement events."""
        self._advertisement_callbacks.append(callback)

    def unregister_advertisement_callback(
        self, callback: Callable[[AdvertisementData], None]
    ) -> None:
        """Unregister a callback for advertisement events."""
        if callback in self._advertisement_callbacks:
            self._advertisement_callbacks.remove(callback)

    async def get_latest_advertisement(
        self, refresh: bool = False
    ) -> AdvertisementData | None:
        """Return the latest advertisement data.

        Args:
            refresh: If True and hass is available, fetch fresh data from
                     HA's Bluetooth component.

        Returns:
            Latest ``AdvertisementData``, or ``None`` if none received yet.

        """
        if refresh and self._hass is not None:
            service_info = bluetooth.async_last_service_info(
                self._hass, self._address, connectable=False
            )
            if service_info:
                self._latest_advertisement = self.convert_advertisement(service_info)

        return self._latest_advertisement

    async def get_advertisement_rssi(self, refresh: bool = False) -> int | None:
        """Get the RSSI from advertisement data.

        Args:
            refresh: If True, attempt to get fresh advertisement data.

        Returns:
            RSSI value in dBm, or ``None`` if no advertisement received yet.

        """
        if refresh:
            await self.get_latest_advertisement(refresh=True)

        return self._get_cached_rssi()

    def _get_cached_rssi(self) -> int | None:
        """Return the cached RSSI, or ``None`` if unavailable."""
        if self._latest_advertisement is not None:
            return self._latest_advertisement.rssi
        return None

    def read_rssi_sync(self) -> int:
        """Return the cached RSSI from the latest advertisement.

        Raises:
            ValueError: If no advertisement with RSSI has been received yet.

        """
        rssi = self._get_cached_rssi()
        if rssi is not None:
            return rssi

        raise ValueError(
            f"No RSSI available for {self._address}. "
            "Call get_latest_advertisement(refresh=True) first."
        )

    # ------------------------------------------------------------------
    # Static helpers for extracting device metadata
    # ------------------------------------------------------------------

    @staticmethod
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

    @staticmethod
    def get_model_name(advertisement: AdvertisementData) -> str | None:
        """Extract model name from parsed advertisement data."""
        local_name = advertisement.ad_structures.core.local_name
        if local_name:
            return local_name
        return None
