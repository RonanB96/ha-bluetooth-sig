"""Device adapter for Home Assistant Bluetooth.

This module provides the HomeAssistantBluetoothAdapter class which implements
the bluetooth-sig-python ClientManagerProtocol. It bridges Home Assistant's
Bluetooth integration with the bluetooth-sig-python library for both:
- Passive mode: parsing advertisement data
- Active mode: GATT connections for reading characteristics
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    close_stale_connections_by_address,
    establish_connection,
)
from bluetooth_sig.advertising import PayloadContext, parse_advertising_payloads
from bluetooth_sig.device.client import ClientManagerProtocol
from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.gatt.characteristics.unknown import UnknownCharacteristic
from bluetooth_sig.gatt.services.base import BaseGattService
from bluetooth_sig.gatt.services.registry import GattServiceRegistry
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
from bluetooth_sig.types.data_types import CharacteristicInfo, ServiceInfo
from bluetooth_sig.types.device_types import DeviceService, ScannedDevice
from bluetooth_sig.types.gatt_enums import GattProperty
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

# Bleak returns characteristic properties as lowercase hyphenated strings
# (e.g. "write-without-response"), but GattProperty is an IntEnum with
# bitmask values.  Build the mapping once from the enum member names.
_BLEAK_PROP_TO_GATT: dict[str, GattProperty] = {
    member.name.lower().replace("_", "-"): member
    for member in GattProperty
}
from homeassistant.core import HomeAssistant

from .const import DEFAULT_CONNECTION_TIMEOUT, DEFAULT_READ_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class HomeAssistantBluetoothAdapter(ClientManagerProtocol):
    """Adapter for Home Assistant Bluetooth to bluetooth-sig-python.

    This adapter implements the full ClientManagerProtocol, supporting both:
    - Passive mode: Advertisement parsing only (no hass/ble_device needed)
    - Active mode: Full GATT connection support (requires hass and ble_device)

    For passive mode (advertisement parsing only):
        adapter = HomeAssistantBluetoothAdapter(address="AA:BB:CC:DD:EE:FF", name="Device")

    For active mode (GATT connections):
        adapter = HomeAssistantBluetoothAdapter(
            address="AA:BB:CC:DD:EE:FF",
            name="Device",
            hass=hass,
            ble_device=ble_device,
        )
    """

    supports_scanning = False

    def __init__(
        self,
        address: str,
        name: str = "",
        *,
        hass: HomeAssistant | None = None,
        ble_device: BLEDevice | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            address: Bluetooth device address (MAC address)
            name: Device name
            hass: Home Assistant instance (required for GATT connections)
            ble_device: BLE device from Home Assistant (required for GATT connections)

        """
        super().__init__(address)
        self._name = name
        self._hass = hass
        self._ble_device = ble_device

        # Connection state
        self._client: BleakClient | None = None
        self._is_connected = False
        self._mtu_size = 23  # Default BLE MTU

        # Advertisement tracking
        self._latest_advertisement: AdvertisementData | None = None
        self._disconnected_callback: Callable[[], None] | None = None
        self._advertisement_callbacks: list[Callable[[AdvertisementData], None]] = []

        # Notification callbacks: {char_uuid_str: callback}
        self._notification_callbacks: dict[str, Callable[[str, bytes], None]] = {}

        # Service cache (like BleakRetryConnectionManager)
        self._cached_services: list[DeviceService] | None = None

    def update_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the BLE device reference.

        Should be called when Home Assistant provides a new BLEDevice reference.

        Args:
            ble_device: Updated BLE device from Home Assistant

        """
        self._ble_device = ble_device

    def set_hass(self, hass: HomeAssistant) -> None:
        """Set the Home Assistant instance.

        Args:
            hass: Home Assistant instance

        """
        self._hass = hass

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._name

    @property
    def is_connected(self) -> bool:
        """Return whether the device is connected."""
        return (
            self._is_connected
            and self._client is not None
            and self._client.is_connected
        )

    @property
    def mtu_size(self) -> int:
        """Return the MTU size."""
        if self._client and self._client.is_connected:
            return self._client.mtu_size
        return self._mtu_size

    @property
    def has_connection_support(self) -> bool:
        """Check if this adapter is configured for GATT connections."""
        return self._hass is not None

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

        service_info: BluetoothServiceInfoBleak = advertisement
        # Extract manufacturer data - convert to ManufacturerData objects
        manufacturer_data: dict[int, ManufacturerData] = {}
        if service_info.manufacturer_data:
            for company_id, payload in service_info.manufacturer_data.items():
                manufacturer_data[company_id] = ManufacturerData(
                    company=CompanyIdentifier(id=company_id, name="Unknown"),
                    payload=payload,
                )

        # Extract service data - convert to BluetoothUUID keys
        service_data: dict[BluetoothUUID, bytes] = {}
        if service_info.service_data:
            for uuid_str, data in service_info.service_data.items():
                service_data[BluetoothUUID(uuid_str)] = data

        # Extract service UUIDs
        service_uuids = []
        if service_info.service_uuids:
            service_uuids = [BluetoothUUID(uuid) for uuid in service_info.service_uuids]

        # Get local name
        local_name = service_info.name or ""

        # Get RSSI
        rssi = service_info.rssi

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

        # Parse advertising data using bluetooth-sig interpreters
        interpreted_data = None
        interpreter_name = None

        # Prepare data for parsing
        mfr_data_for_parse: dict[int, bytes] = {}
        if service_info.manufacturer_data:
            for company_id, payload in service_info.manufacturer_data.items():
                mfr_data_for_parse[company_id] = payload
                _LOGGER.debug(
                    "Device %s has manufacturer data company ID: 0x%04X with %d bytes",
                    service_info.address,
                    company_id,
                    len(payload),
                )

        svc_data_for_parse: dict[BluetoothUUID, bytes] = {}
        if service_info.service_data:
            for uuid_str, data in service_info.service_data.items():
                svc_data_for_parse[BluetoothUUID(uuid_str)] = data
                _LOGGER.debug(
                    "Device %s has service data UUID: %s with %d bytes",
                    service_info.address,
                    uuid_str,
                    len(data),
                )

        # Try to parse with the library's interpreters
        if mfr_data_for_parse or svc_data_for_parse:
            try:
                context = PayloadContext(
                    mac_address=service_info.address,
                    rssi=rssi or 0,
                )
                parsed_results = parse_advertising_payloads(
                    manufacturer_data=mfr_data_for_parse,
                    service_data=svc_data_for_parse,
                    context=context,
                )
                if parsed_results:
                    # Use the first parsed result
                    interpreted_data = parsed_results[0]
                    interpreter_name = type(interpreted_data).__name__
                    _LOGGER.debug(
                        "Parsed advertising data for %s: %s from %s",
                        service_info.address,
                        interpreted_data,
                        interpreter_name,
                    )
            except Exception as e:
                _LOGGER.debug(
                    "Failed to parse advertising data for %s: %s",
                    service_info.address,
                    e,
                )

        # Create and return AdvertisementData
        return AdvertisementData(
            ad_structures=ad_structures,
            interpreted_data=interpreted_data,
            interpreter_name=interpreter_name,
            rssi=rssi,
        )

    async def get_latest_advertisement(
        self, refresh: bool = False
    ) -> AdvertisementData | None:
        """Return the latest advertisement data.

        Args:
            refresh: If True and we have hass, attempt to get fresh
                     advertisement data from HA's Bluetooth component.
                     If False, return the last cached advertisement.

        Returns:
            Latest AdvertisementData, or None if none received yet

        """
        if refresh and self._hass is not None:
            # Try to get fresh service info from HA
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
                     If False, return the cached RSSI from last advertisement.

        Returns:
            RSSI value in dBm, or None if no advertisement has been received

        """
        if refresh:
            await self.get_latest_advertisement(refresh=True)

        if self._latest_advertisement is not None:
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

    # =========================================================================
    # GATT Connection Methods (ClientManagerProtocol implementation)
    # =========================================================================

    def _ensure_connection_support(self) -> None:
        """Raise if GATT connection support is not configured."""
        if self._hass is None:
            raise RuntimeError(
                "GATT operations require hass parameter. "
                "Create adapter with: HomeAssistantBluetoothAdapter(..., hass=hass)"
            )

    def _get_ble_device(self) -> BLEDevice:
        """Get BLE device, refreshing from HA if needed."""
        self._ensure_connection_support()

        # Try to get a fresh connectable device from HA
        if self._hass is not None:
            fresh_device = bluetooth.async_ble_device_from_address(
                self._hass, self._address, connectable=True
            )
            if fresh_device:
                self._ble_device = fresh_device

        if self._ble_device is None:
            raise RuntimeError(
                f"No BLE device available for {self._address}. "
                "Device may be out of range."
            )
        return self._ble_device

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection event from BleakClient."""
        _LOGGER.debug("Device %s disconnected", self._address)
        self._is_connected = False
        self._client = None
        if self._disconnected_callback:
            self._disconnected_callback()

    async def connect(self, *, timeout: float = DEFAULT_CONNECTION_TIMEOUT) -> None:
        """Connect to the device using bleak-retry-connector.

        Args:
            timeout: Connection timeout in seconds

        Raises:
            RuntimeError: If hass is not configured
            BleakError: If connection fails

        """
        self._ensure_connection_support()

        if self._is_connected and self._client and self._client.is_connected:
            _LOGGER.debug("Already connected to %s", self._address)
            return

        ble_device = self._get_ble_device()

        _LOGGER.debug("Connecting to %s", self._address)

        # Close any stale connections first
        await close_stale_connections_by_address(self._address)

        try:
            self._client = await establish_connection(
                BleakClient,
                ble_device,
                self._address,
                disconnected_callback=self._on_disconnect,
                max_attempts=2,
                ble_device_callback=self._get_ble_device,
            )
            self._is_connected = True
            self._mtu_size = self._client.mtu_size
            self._cached_services = None  # Clear cache on new connection
            _LOGGER.debug(
                "Connected to %s (MTU: %d)",
                self._address,
                self._mtu_size,
            )
        except BleakError as err:
            _LOGGER.debug("Failed to connect to %s: %s", self._address, err)
            self._is_connected = False
            self._client = None
            raise

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._client:
            try:
                if self._client.is_connected:
                    await self._client.disconnect()
                    _LOGGER.debug("Disconnected from %s", self._address)
            except BleakError as err:
                _LOGGER.debug("Error disconnecting from %s: %s", self._address, err)
            finally:
                self._client = None
                self._is_connected = False
                self._notification_callbacks.clear()
                self._cached_services = None  # Clear cache on disconnect

    async def get_services(self) -> list[DeviceService]:
        """Get GATT services from the connected device.

        Returns a list of DeviceService objects with characteristics populated
        as BaseCharacteristic instances from the registry. Results are cached
        after first retrieval.

        Returns:
            List of DeviceService objects

        Raises:
            RuntimeError: If not connected

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        # Return cached services if available
        if self._cached_services is not None:
            return self._cached_services

        result: list[DeviceService] = []

        for bleak_service in self._client.services:
            service_uuid = BluetoothUUID(bleak_service.uuid)

            # Get service class from registry or create a base service
            service_class = GattServiceRegistry.get_service_class_by_uuid(service_uuid)
            if service_class:
                service_instance = service_class()
            else:
                # Create a generic service for unknown UUIDs
                service_info = ServiceInfo(
                    uuid=service_uuid, name=f"Service {service_uuid.short_form}"
                )
                service_instance = BaseGattService(info=service_info)

            # Build characteristics dict
            characteristics: dict[str, BaseCharacteristic[Any]] = {}

            for bleak_char in bleak_service.characteristics:
                char_uuid = BluetoothUUID(bleak_char.uuid)
                char_uuid_str = str(char_uuid)

                # Convert Bleak properties to GattProperty enum
                properties: list[GattProperty] = []
                for prop in bleak_char.properties:
                    gatt_prop = _BLEAK_PROP_TO_GATT.get(prop)
                    if gatt_prop is not None:
                        properties.append(gatt_prop)
                    else:
                        _LOGGER.warning("Unmapped Bleak property: %s", prop)

                # Get characteristic class from registry
                char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
                    char_uuid
                )
                if char_class:
                    # Create characteristic instance with runtime properties from device
                    char_instance = char_class(properties=properties)
                else:
                    # Fallback: Create UnknownCharacteristic for unrecognized UUIDs
                    char_info = CharacteristicInfo(
                        uuid=char_uuid,
                        name=bleak_char.description
                        or f"Unknown Characteristic ({char_uuid.short_form})",
                    )
                    char_instance = UnknownCharacteristic(
                        info=char_info, properties=properties
                    )

                characteristics[char_uuid_str] = char_instance

            device_service = DeviceService(
                service=service_instance,
                characteristics=characteristics,
            )
            result.append(device_service)

        _LOGGER.debug(
            "Discovered %d services with %d characteristics from %s",
            len(result),
            sum(len(s.characteristics) for s in result),
            self._address,
        )

        # Cache the result
        self._cached_services = result
        return result

    async def read_gatt_char(self, char_uuid: BluetoothUUID) -> bytes:
        """Read a GATT characteristic.

        Args:
            char_uuid: UUID of the characteristic to read

        Returns:
            Raw bytes from the characteristic

        Raises:
            RuntimeError: If not connected
            BleakError: If read fails

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        try:
            data = await asyncio.wait_for(
                self._client.read_gatt_char(str(char_uuid)),
                timeout=DEFAULT_READ_TIMEOUT,
            )
            _LOGGER.debug(
                "Read characteristic %s from %s: %s",
                char_uuid.short_form,
                self._address,
                data.hex() if data else "empty",
            )
            return bytes(data)
        except TimeoutError as err:
            raise BleakError(f"Timeout reading {char_uuid}") from err

    async def write_gatt_char(
        self, char_uuid: BluetoothUUID, data: bytes, response: bool = True
    ) -> None:
        """Write a GATT characteristic.

        Args:
            char_uuid: UUID of the characteristic to write
            data: Data to write
            response: Whether to wait for response

        Raises:
            RuntimeError: If not connected
            BleakError: If write fails

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        await self._client.write_gatt_char(str(char_uuid), data, response=response)
        _LOGGER.debug(
            "Wrote %d bytes to characteristic %s on %s",
            len(data),
            char_uuid.short_form,
            self._address,
        )

    async def read_gatt_descriptor(self, desc_uuid: BluetoothUUID) -> bytes:
        """Read a GATT descriptor.

        Args:
            desc_uuid: UUID of the descriptor to read

        Returns:
            Raw bytes from the descriptor

        Raises:
            RuntimeError: If not connected
            ValueError: If descriptor not found

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        # Find descriptor by UUID
        desc_uuid_str = str(desc_uuid).lower()
        for service in self._client.services:
            for char in service.characteristics:
                for desc in char.descriptors:
                    if desc.uuid.lower() == desc_uuid_str:
                        data = await self._client.read_gatt_descriptor(desc.handle)
                        return bytes(data)

        raise ValueError(f"Descriptor {desc_uuid} not found")

    async def write_gatt_descriptor(
        self, desc_uuid: BluetoothUUID, data: bytes
    ) -> None:
        """Write a GATT descriptor.

        Args:
            desc_uuid: UUID of the descriptor to write
            data: Data to write

        Raises:
            RuntimeError: If not connected
            ValueError: If descriptor not found

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        # Find descriptor by UUID
        desc_uuid_str = str(desc_uuid).lower()
        for service in self._client.services:
            for char in service.characteristics:
                for desc in char.descriptors:
                    if desc.uuid.lower() == desc_uuid_str:
                        await self._client.write_gatt_descriptor(desc.handle, data)
                        return

        raise ValueError(f"Descriptor {desc_uuid} not found")

    async def start_notify(
        self, char_uuid: BluetoothUUID, callback: Callable[[str, bytes], None]
    ) -> None:
        """Start notifications on a characteristic.

        Args:
            char_uuid: UUID of the characteristic
            callback: Callback function(uuid_str, data) for notifications

        Raises:
            RuntimeError: If not connected

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        char_uuid_str = str(char_uuid)
        self._notification_callbacks[char_uuid_str] = callback

        def _notification_handler(
            _sender: BleakGATTCharacteristic, data: bytearray
        ) -> None:
            callback(char_uuid_str, bytes(data))

        await self._client.start_notify(char_uuid_str, _notification_handler)
        _LOGGER.debug(
            "Started notifications for %s on %s", char_uuid.short_form, self._address
        )

    async def stop_notify(self, char_uuid: BluetoothUUID) -> None:
        """Stop notifications on a characteristic.

        Args:
            char_uuid: UUID of the characteristic

        Raises:
            RuntimeError: If not connected

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        char_uuid_str = str(char_uuid)
        self._notification_callbacks.pop(char_uuid_str, None)
        await self._client.stop_notify(char_uuid_str)
        _LOGGER.debug(
            "Stopped notifications for %s on %s", char_uuid.short_form, self._address
        )

    async def pair(self) -> None:
        """Pair with the device.

        Note: Pairing is typically handled automatically by the OS on most platforms.

        Raises:
            RuntimeError: If not connected
            NotImplementedError: Explicit pairing not supported via Bleak

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        try:
            await self._client.pair()
            _LOGGER.debug("Paired with %s", self._address)
        except NotImplementedError:
            _LOGGER.debug(
                "Explicit pairing not supported on this platform for %s",
                self._address,
            )
            raise

    async def unpair(self) -> None:
        """Unpair from the device.

        Raises:
            RuntimeError: If not connected
            NotImplementedError: Explicit unpairing not supported via Bleak

        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to device")

        try:
            await self._client.unpair()
            _LOGGER.debug("Unpaired from %s", self._address)
        except NotImplementedError:
            _LOGGER.debug(
                "Explicit unpairing not supported on this platform for %s",
                self._address,
            )
            raise

    async def read_rssi(self) -> int:
        """Read RSSI from the most recent advertisement.

        Bleak does not support reading RSSI from an active connection,
        so this returns the cached RSSI from the last advertisement.

        Returns:
            RSSI value in dBm

        Raises:
            ValueError: If no advertisement with RSSI has been received yet

        """
        if self._latest_advertisement and self._latest_advertisement.rssi is not None:
            return self._latest_advertisement.rssi

        raise ValueError(
            f"No RSSI available for {self._address}. "
            "Call get_latest_advertisement(refresh=True) first."
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
