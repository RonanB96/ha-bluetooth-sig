"""GATT characteristic polling for Bluetooth SIG Devices.

Stateless async functions that read GATT characteristics from a
connected BLE device and build ``PassiveBluetoothDataUpdate`` objects.

Used by ``GATTManager`` for both:

- Initial read during probe (``read_chars_connected``)
- Periodic polling (``poll_gatt_characteristics``)

All functions receive their dependencies explicitly — no shared
mutable state lives in this module.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bluetooth_sig import is_struct_value, to_primitive
from bluetooth_sig.device.device import Device
from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.gatt.exceptions import SpecialValueDetectedError
from bluetooth_sig.types.gatt_enums import CharacteristicName, CharacteristicRole
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
)
from homeassistant.helpers.entity import EntityDescription

from .const import DEFAULT_READ_TIMEOUT, BLEAddress
from .device_validator import GATTProbeResult
from .entity_builder import (
    DIAGNOSTIC_ROLES,
    add_simple_entity,
    add_struct_entities,
)

_LOGGER = logging.getLogger(__name__)

# Resolve the Manufacturer Name String UUID from the library registry
# so we can identify it during GATT reads without hardcoding.
_manufacturer_cls = CharacteristicRegistry.get_characteristic_class(
    CharacteristicName.MANUFACTURER_NAME_STRING
)
_MANUFACTURER_NAME_UUID: BluetoothUUID | None = (
    _manufacturer_cls().uuid if _manufacturer_cls else None
)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


async def build_gatt_entities(
    address: BLEAddress,
    device: Device,
    probe_result: GATTProbeResult,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    *,
    capture_manufacturer: bool = False,
) -> None:
    """Read characteristics and populate entity dicts.

    Shared by ``read_chars_connected`` (probe-time) and
    ``poll_gatt_characteristics`` (poll-time).

    When *capture_manufacturer* is True (probe-time only), the
    Manufacturer Name String value is stored on *probe_result*
    for use in discovery flow metadata.
    """
    for char_uuid in probe_result.supported_char_uuids:
        special_value_meaning: str | None = None
        try:
            parsed_value = await asyncio.wait_for(
                device.read(str(char_uuid)),
                timeout=DEFAULT_READ_TIMEOUT,
            )
        except SpecialValueDetectedError as err:
            # Well-formed read returning a SIG sentinel (e.g. "value is
            # not known", "NaN"). Per the SIG spec this is a valid
            # reading meaning the sensor has no current sample — not
            # a parse failure. Still build the entity so the device
            # and entity registry rows get created; the state will be
            # ``unknown`` until a real value is read.
            #
            # Logged at WARNING because special values are an
            # exceptional condition the operator should be aware of
            # (the SIG spec defines them precisely so they are
            # surfaced rather than hidden).
            parsed_value = None
            special_value_meaning = err.special_value.meaning
            _LOGGER.debug(
                "Characteristic %s (%s) on %s returned SIG special value "
                "(%s); entity will report 'unknown' until a real reading "
                "is available",
                err.name,
                char_uuid.short_form,
                address,
                special_value_meaning,
            )
        except Exception as err:
            _LOGGER.debug(
                "Failed to read characteristic %s from %s: %s",
                char_uuid.short_form,
                address,
                err,
            )
            continue

        try:
            if parsed_value is None and special_value_meaning is None:
                # device.read() returned None with no exception — nothing
                # to publish for this characteristic.
                continue

            # Capture manufacturer name from GATT — only during
            # initial probe, not on every poll cycle.
            if (
                parsed_value is not None
                and capture_manufacturer
                and _MANUFACTURER_NAME_UUID is not None
                and char_uuid == _MANUFACTURER_NAME_UUID
                and isinstance(parsed_value, str)
            ):
                probe_result.manufacturer_name = parsed_value

            char_class: type[BaseCharacteristic[Any]] | None = (
                CharacteristicRegistry.get_characteristic_class_by_uuid(char_uuid)
            )
            if not char_class:
                _LOGGER.debug(
                    "No registered class for UUID %s, skipping",
                    char_uuid.short_form,
                )
                continue

            char_instance: BaseCharacteristic[Any] = char_class()
            char_name: str = char_instance.name
            char_unit: str = char_instance.unit

            role: CharacteristicRole = char_instance.role
            is_diagnostic = role in DIAGNOSTIC_ROLES

            if parsed_value is None:
                # SIG special value — emit a simple entity with no
                # current value so HA shows ``unknown`` rather than
                # hiding the sensor entirely.
                add_simple_entity(
                    None,
                    f"gatt_{char_uuid.short_form}",
                    char_name,
                    None,  # type: ignore[arg-type]
                    char_unit,
                    is_diagnostic,
                    entity_descriptions,
                    entity_names,
                    entity_data,
                )
            elif is_struct_value(parsed_value):
                add_struct_entities(
                    None,
                    f"gatt_{char_uuid.short_form}",
                    char_name,
                    parsed_value,
                    char_unit,
                    is_diagnostic,
                    entity_descriptions,
                    entity_names,
                    entity_data,
                    spec=char_instance.spec,
                )
            else:
                add_simple_entity(
                    None,
                    f"gatt_{char_uuid.short_form}",
                    char_name,
                    to_primitive(parsed_value),
                    char_unit,
                    is_diagnostic,
                    entity_descriptions,
                    entity_names,
                    entity_data,
                )

        except Exception as err:
            _LOGGER.debug(
                "Failed to build entity for characteristic %s from %s: %s",
                char_uuid.short_form,
                address,
                err,
            )


async def read_chars_connected(
    address: BLEAddress,
    device: Device,
    probe_result: GATTProbeResult,
) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
    """Read characteristic values using an already-open BLE connection.

    Called inside ``async_probe_device`` while the connection is still
    live. Returns ``None`` if no entities could be built (e.g. all reads
    failed).
    """
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
    entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

    await build_gatt_entities(
        address,
        device,
        probe_result,
        entity_descriptions,
        entity_names,
        entity_data,
        capture_manufacturer=True,
    )

    if not entity_data:
        return None

    return PassiveBluetoothDataUpdate(
        devices={},
        entity_descriptions=entity_descriptions,
        entity_names=entity_names,
        entity_data=entity_data,
    )


async def poll_gatt_characteristics(
    address: BLEAddress,
    probe_result: GATTProbeResult,
    device: Device,
) -> PassiveBluetoothDataUpdate[float | int | str | bool] | None:
    """Poll GATT characteristics from a connectable device.

    Connects, reads all known parseable characteristics, and returns
    a ``PassiveBluetoothDataUpdate`` with the data.
    """
    try:
        await device.connect()

        entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription] = {}
        entity_names: dict[PassiveBluetoothEntityKey, str | None] = {}
        entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool] = {}

        await build_gatt_entities(
            address,
            device,
            probe_result,
            entity_descriptions,
            entity_names,
            entity_data,
        )

        if not entity_data:
            return None

        return PassiveBluetoothDataUpdate(
            devices={},
            entity_descriptions=entity_descriptions,
            entity_names=entity_names,
            entity_data=entity_data,
        )

    except Exception as err:
        _LOGGER.debug("Failed to poll GATT from %s: %s", address, err)
        return None

    finally:
        try:
            await device.disconnect()
        except Exception as disc_err:
            _LOGGER.debug(
                "Disconnect failed after polling %s: %s",
                address,
                disc_err,
            )
