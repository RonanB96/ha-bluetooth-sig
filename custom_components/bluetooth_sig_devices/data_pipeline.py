"""Passive advertisement data pipeline for Bluetooth SIG Devices.

Converts a ``BluetoothServiceInfoBleak`` into a
``PassiveBluetoothDataUpdate`` that the
``ActiveBluetoothProcessorCoordinator`` can merge into its entity
state.

Functions in this module are stateless — they receive device state
and the translator as explicit parameters.
"""

from __future__ import annotations

import logging

from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.device.device import Device
from bluetooth_sig.types.advertising import AdvertisementData
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription

from .advertisement_converter import (
    convert_advertisement,
    get_manufacturer_name,
    get_model_name,
)
from .const import BLEAddress
from .device_adapter import HomeAssistantBluetoothAdapter
from .entity_builder import add_interpreted_entities, add_service_data_entities

_LOGGER = logging.getLogger(__name__)


def update_device(
    service_info: BluetoothServiceInfoBleak,
    *,
    hass: HomeAssistant,
    devices: dict[BLEAddress, Device],
    translator: BluetoothSIGTranslator,
) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
    """Build a ``PassiveBluetoothDataUpdate`` from a BLE advertisement.

    Creates the library ``Device`` on first sighting, converts the
    advertisement, and delegates entity construction to
    ``build_passive_bluetooth_update``.
    """
    address = service_info.address
    is_first_update = address not in devices

    _LOGGER.debug(
        "Processing device %s (name=%s, rssi=%s, mfr_data=%d, svc_data=%d)",
        address,
        service_info.name or "unknown",
        service_info.rssi,
        len(service_info.manufacturer_data) if service_info.manufacturer_data else 0,
        len(service_info.service_data) if service_info.service_data else 0,
    )

    if is_first_update:
        _LOGGER.info(
            "Device %s: first advertisement update received (name=%s)",
            address,
            service_info.name or "unknown",
        )

    # Get or create device instance
    if address not in devices:
        ble_device = bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        )
        adapter = HomeAssistantBluetoothAdapter(
            address,
            service_info.name or "",
            hass=hass,
            ble_device=ble_device,
        )
        devices[address] = Device(
            connection_manager=adapter,
            translator=translator,
        )
        _LOGGER.debug("Created new device for address %s", address)

    # Convert advertisement
    advertisement = convert_advertisement(service_info)

    return build_passive_bluetooth_update(
        address, service_info, advertisement, translator=translator
    )


def build_passive_bluetooth_update(
    address: BLEAddress,
    service_info: BluetoothServiceInfoBleak,
    advertisement: AdvertisementData,
    *,
    translator: BluetoothSIGTranslator,
) -> PassiveBluetoothDataUpdate[float | int | str | bool]:
    """Build ``PassiveBluetoothDataUpdate`` from advertisement data."""
    devices: dict[str | None, DeviceInfo] = {}
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
    entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

    device_name = service_info.name or f"Bluetooth Device {address[-8:]}"
    devices[None] = DeviceInfo(
        name=device_name,
        manufacturer=get_manufacturer_name(advertisement),
        model=get_model_name(advertisement),
    )

    # Process interpreted data if available
    seen_uuids: set[str] = set()
    if advertisement.interpreted_data:
        _LOGGER.debug(
            "Device %s has interpreted data from %s: %s",
            address,
            advertisement.interpreter_name,
            advertisement.interpreted_data,
        )
        add_interpreted_entities(
            None,
            advertisement.interpreter_name,
            advertisement.interpreted_data,
            entity_descriptions,
            entity_names,
            entity_data,
            seen_uuids=seen_uuids,
        )

    # Process service data for standard GATT characteristics
    if advertisement.ad_structures.core.service_data:
        add_service_data_entities(
            None,
            advertisement.ad_structures.core.service_data,
            translator,
            entity_descriptions,
            entity_names,
            entity_data,
            skip_uuids=seen_uuids if advertisement.interpreted_data else set(),
        )

    _LOGGER.debug(
        "Device %s: built update with %d entities (descriptions=%d, names=%d)",
        address,
        len(entity_data),
        len(entity_descriptions),
        len(entity_names),
    )

    return PassiveBluetoothDataUpdate(
        devices=devices,
        entity_descriptions=entity_descriptions,
        entity_names=entity_names,
        entity_data=entity_data,
    )
