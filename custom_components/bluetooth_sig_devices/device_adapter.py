"""Device adapter for Home Assistant Bluetooth."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from bluetooth_sig.device.connection import ConnectionManagerProtocol
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
from bluetooth_sig.types.device_types import DeviceService, ScannedDevice
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)


class HomeAssistantBluetoothAdapter(ConnectionManagerProtocol):
    """Adapter for Home Assistant Bluetooth to bluetooth-sig-python."""

    # TODO GATT operations

    supports_scanning = False

    def __init__(self, address: str, name: str) -> None:
        """Initialize the adapter."""
        self._address = address
        self._name = name
        self._is_connected = False
        self._latest_advertisement: AdvertisementData | None = None
        self._disconnected_callback: Callable[[], None] | None = None
        self._advertisement_callbacks: list[Callable[[AdvertisementData], None]] = []

    @property
    def address(self) -> str:
        """Return the device address."""
        return self._address

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._name

    @property
    def is_connected(self) -> bool:
        """Return whether the device is connected."""
        return self._is_connected

    @property
    def mtu_size(self) -> int:
        """Return the MTU size."""
        return 23  # Default BLE MTU

    @classmethod
    def convert_advertisement(cls, advertisement: object) -> AdvertisementData:
        """Convert HA BluetoothServiceInfoBleak to bluetooth-sig AdvertisementData.

        Args:
            advertisement: Home Assistant's Bluetooth service info

        Returns:
            AdvertisementData compatible with bluetooth-sig-python library
        """
        # Type narrowing for Home Assistant's BluetoothServiceInfoBleak
        if not isinstance(advertisement, BluetoothServiceInfoBleak):
            msg = f"Expected BluetoothServiceInfoBleak, got {type(advertisement)}"
            raise TypeError(msg)

        # Extract manufacturer data - convert to ManufacturerData objects
        manufacturer_data: dict[int, ManufacturerData] = {}
        if advertisement.manufacturer_data:
            for company_id, payload in advertisement.manufacturer_data.items():
                manufacturer_data[company_id] = ManufacturerData(
                    company=CompanyIdentifier(id=company_id, name="Unknown"),
                    payload=payload,
                )

        # Extract service data - convert to BluetoothUUID keys
        service_data: dict[BluetoothUUID, bytes] = {}
        if advertisement.service_data:
            for uuid_str, data in advertisement.service_data.items():
                service_data[BluetoothUUID(uuid_str)] = data

        # Extract service UUIDs
        service_uuids = []
        if advertisement.service_uuids:
            service_uuids = [
                BluetoothUUID(uuid) for uuid in advertisement.service_uuids
            ]

        # Get local name
        local_name = advertisement.name or ""

        # Get RSSI
        rssi = advertisement.rssi

        # Create CoreAdvertisingData with the extracted information
        core_data = CoreAdvertisingData(
            manufacturer_data=manufacturer_data,
            service_data=service_data,
            service_uuids=service_uuids,
            solicited_service_uuids=[],
            local_name=local_name,
            uri_data=None,
        )

        # Create other advertising data structures with defaults
        properties = DeviceProperties(
            flags=BLEAdvertisingFlags(0),
            appearance=None,
            tx_power=0,
            le_role=None,
            le_supported_features=None,
            class_of_device=None,
        )

        # Create AdvertisingDataStructures
        ad_structures = AdvertisingDataStructures(
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
                indoor_positioning=b"",
                three_d_information=b"",
                transport_discovery_data=b"",
                channel_map_update_indication=b"",
            ),
            mesh=MeshAndBroadcastData(
                mesh_message=b"",
                mesh_beacon=b"",
                pb_adv=b"",
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

        # Create and return AdvertisementData
        return AdvertisementData(
            ad_structures=ad_structures,
            interpreted_data=None,
            interpreter_name=None,
            rssi=rssi,
        )

    async def get_latest_advertisement(
        self, refresh: bool = False
    ) -> AdvertisementData | None:
        """Return the latest advertisement data."""
        return self._latest_advertisement

    async def get_advertisement_rssi(self, refresh: bool = False) -> int | None:
        """Return the RSSI from the latest advertisement."""
        if self._latest_advertisement:
            return self._latest_advertisement.rssi
        return None

    def set_disconnected_callback(self, callback: Callable[[], None] | None) -> None:
        """Set the callback for disconnection events."""
        self._disconnected_callback = callback

    def on_advertisement_received(self, advertisement: AdvertisementData) -> None:
        """Handle receiving an advertisement."""
        self._latest_advertisement = advertisement
        for callback in self._advertisement_callbacks:
            callback(advertisement)

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

    # Stub connection methods (not used for advertising-only mode)
    async def connect(self, *, timeout: float = 10.0) -> None:
        """Connect to the device (stub)."""
        raise NotImplementedError("Connection not supported in advertising-only mode")

    async def disconnect(self) -> None:
        """Disconnect from the device (stub)."""
        raise NotImplementedError("Connection not supported in advertising-only mode")

    async def get_services(self) -> list[DeviceService]:
        """Get GATT services (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    async def pair(self) -> None:
        """Pair with the device (stub)."""
        raise NotImplementedError("Pairing not supported in advertising-only mode")

    async def unpair(self) -> None:
        """Unpair from the device (stub)."""
        raise NotImplementedError("Pairing not supported in advertising-only mode")

    async def read_rssi(self) -> int:
        """Read RSSI from the device (stub)."""
        raise NotImplementedError("RSSI reading not supported in advertising-only mode")

    async def read_gatt_char(self, char_uuid: BluetoothUUID) -> bytes:
        """Read a GATT characteristic (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    async def write_gatt_char(
        self, char_uuid: BluetoothUUID, data: bytes, response: bool = True
    ) -> None:
        """Write a GATT characteristic (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    async def read_gatt_descriptor(self, desc_uuid: BluetoothUUID) -> bytes:
        """Read a GATT descriptor (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    async def write_gatt_descriptor(
        self, desc_uuid: BluetoothUUID, data: bytes
    ) -> None:
        """Write a GATT descriptor (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    async def start_notify(
        self, char_uuid: BluetoothUUID, callback: Callable[[str, bytes], None]
    ) -> None:
        """Start notifications on a characteristic (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    async def stop_notify(self, char_uuid: BluetoothUUID) -> None:
        """Stop notifications on a characteristic (stub)."""
        raise NotImplementedError(
            "GATT operations not supported in advertising-only mode"
        )

    # Scanning methods are handled by Home Assistant's Bluetooth integration, not this adapter
    @classmethod
    async def scan(
        cls,
        timeout: float = 5.0,
        *,
        filters: object | None = None,
        scanning_mode: object = "active",
        adapter: str | None = None,
        callback: object | None = None,
    ) -> list[ScannedDevice]:
        """Scan for devices (stub)."""
        raise NotImplementedError("Scanning handled by Home Assistant Bluetooth")

    @classmethod
    def scan_stream(
        cls,
        timeout: float | None = 5.0,
        *,
        filters: object | None = None,
        scanning_mode: object = "active",
        adapter: str | None = None,
    ) -> AsyncIterator[ScannedDevice]:
        """Stream scan results (stub)."""
        raise NotImplementedError("Scanning handled by Home Assistant Bluetooth")

    @classmethod
    async def find_device(
        cls,
        filters: object,
        timeout: float = 10.0,
        *,
        scanning_mode: object = "active",
        adapter: str | None = None,
    ) -> None:
        """Find a device (stub)."""
        raise NotImplementedError(
            "Device discovery handled by Home Assistant Bluetooth"
        )
