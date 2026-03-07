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

import logging
from collections.abc import Callable

from bluetooth_sig.advertising import PayloadContext, parse_advertising_payloads
from bluetooth_sig.types.advertising import (
    AdvertisementData,
    AdvertisingDataStructures,
    BLEAdvertisingFlags,
    CoreAdvertisingData,
    DeviceProperties,
    DirectedAdvertisingData,
    LocationAndSensingData,
    MeshAndBroadcastData,
    OOBSecurityData,
    SecurityData,
)
from bluetooth_sig.types.company import CompanyIdentifier, ManufacturerData
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
        address: str,
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

    # ------------------------------------------------------------------
    # Conversion — classmethod API (no instance required)
    # ------------------------------------------------------------------

    @classmethod
    def convert_advertisement(cls, advertisement: object) -> AdvertisementData:
        """Convert HA ``BluetoothServiceInfoBleak`` to library ``AdvertisementData``.

        Performs structural HA→library mapping **and** interpreter parsing in
        two internal steps.  This is the single public entry point; callers
        that previously used ``HomeAssistantBluetoothAdapter.convert_advertisement``
        are redirected here.

        Args:
            advertisement: Home Assistant's Bluetooth service info.

        Returns:
            ``AdvertisementData`` compatible with bluetooth-sig-python.

        Raises:
            TypeError: If *advertisement* is not a ``BluetoothServiceInfoBleak``.

        """
        if not isinstance(advertisement, BluetoothServiceInfoBleak):
            msg = f"Expected BluetoothServiceInfoBleak, got {type(advertisement)}"
            raise TypeError(msg)

        service_info: BluetoothServiceInfoBleak = advertisement

        ad_structures = cls._build_ad_structures(service_info)
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
    def _build_ad_structures(
        cls, service_info: BluetoothServiceInfoBleak
    ) -> AdvertisingDataStructures:
        """Build ``AdvertisingDataStructures`` from HA service info.

        Pure structural mapping — no library interpreter invocation.
        """
        # Manufacturer data → ManufacturerData objects
        manufacturer_data: dict[int, ManufacturerData] = {}
        if service_info.manufacturer_data:
            for company_id, payload in service_info.manufacturer_data.items():
                manufacturer_data[company_id] = ManufacturerData(
                    company=CompanyIdentifier(id=company_id, name="Unknown"),
                    payload=payload,
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

        core_data = CoreAdvertisingData(
            manufacturer_data=manufacturer_data,
            service_data=service_data,
            service_uuids=service_uuids,
            solicited_service_uuids=[],
            local_name=service_info.name or "",
            uri_data=None,
        )

        properties = DeviceProperties(
            flags=BLEAdvertisingFlags(0),
            appearance=None,
            tx_power=0,
            le_role=None,
            le_supported_features=None,
            class_of_device=None,
        )

        return AdvertisingDataStructures(
            core=core_data,
            properties=properties,
            directed=DirectedAdvertisingData(
                public_target_address=[],
                random_target_address=[],
                le_bluetooth_device_address="",
                advertising_interval=None,
                advertising_interval_long=None,
                peripheral_connection_interval_range=None,
            ),
            oob_security=OOBSecurityData(
                simple_pairing_hash_c=b"",
                simple_pairing_randomizer_r=b"",
                secure_connections_confirmation=b"",
                secure_connections_random=b"",
                security_manager_tk_value=b"",
                security_manager_oob_flags=b"",
            ),
            location=LocationAndSensingData(
                indoor_positioning=None,
                three_d_information=None,
                transport_discovery_data=None,
                channel_map_update_indication=None,
            ),
            mesh=MeshAndBroadcastData(
                mesh_message=None,
                secure_network_beacon=None,
                unprovisioned_device_beacon=None,
                provisioning_bearer=None,
                broadcast_name="",
                broadcast_code=b"",
                biginfo=b"",
                periodic_advertising_response_timing=b"",
                electronic_shelf_label=b"",
            ),
            security=SecurityData(
                encrypted_advertising_data=b"",
                resolvable_set_identifier=b"",
            ),
        )

    @classmethod
    def _parse_payloads(
        cls, service_info: BluetoothServiceInfoBleak
    ) -> tuple[object | None, str | None]:
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
            )
            parsed_results = parse_advertising_payloads(
                manufacturer_data=mfr_data_for_parse,
                service_data=svc_data_for_parse,
                context=context,
            )
            if parsed_results:
                interpreted_data = parsed_results[0]
                interpreter_name = type(interpreted_data).__name__
                _LOGGER.debug(
                    "Parsed advertising data for %s: %s from %s",
                    service_info.address,
                    interpreted_data,
                    interpreter_name,
                )
                return interpreted_data, interpreter_name
        except Exception as exc:
            _LOGGER.debug(
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
        for cb in self._advertisement_callbacks:
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

        if self._latest_advertisement is not None:
            return self._latest_advertisement.rssi
        return None

    def read_rssi_sync(self) -> int:
        """Return the cached RSSI from the latest advertisement.

        Raises:
            ValueError: If no advertisement with RSSI has been received yet.

        """
        if self._latest_advertisement and self._latest_advertisement.rssi is not None:
            return self._latest_advertisement.rssi

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
                if mfr_data.company and mfr_data.company.name:
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
