"""Entity building utilities for Bluetooth SIG Devices integration.

Stateless functions that construct ``SensorEntityDescription`` entries,
entity names, and entity data from parsed bluetooth-sig library objects.
These functions have no dependency on coordinator instance state.
"""

from __future__ import annotations

import enum
import logging
from typing import Any

from bluetooth_sig.advertising import SIGCharacteristicData
from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.gatt.exceptions import SpecialValueDetectedError
from bluetooth_sig.types.gatt_enums import CharacteristicRole
from bluetooth_sig.types.registry.common import CharacteristicSpec
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothEntityKey,
)
from homeassistant.components.sensor import (
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import EntityDescription

from .entity_metadata import (
    CUMULATIVE_FIELD_NAMES,
    resolve_device_class,
    resolve_field_unit,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role sets used to gate entity creation across all paths
# ---------------------------------------------------------------------------
SKIP_ROLES: frozenset[CharacteristicRole] = frozenset(
    {
        CharacteristicRole.CONTROL,
        CharacteristicRole.FEATURE,
    }
)
DIAGNOSTIC_ROLES: frozenset[CharacteristicRole] = frozenset(
    {
        CharacteristicRole.STATUS,
        CharacteristicRole.INFO,
    }
)


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------


def to_ha_state(value: object) -> int | float | str | bool:
    """Coerce any parsed characteristic value to an HA-compatible type.

    Inspects the **actual value** at runtime using ``isinstance``, not
    the declared ``python_type`` metadata.  This is forward-compatible:
    when the library adds new types the ``str()`` fallback handles them.

    Order matters:
    - ``bool`` is checked before ``int`` (bool subclasses int)
    - ``IntFlag`` is checked before the ``.name`` branch — bit-field
      values have a ``.name`` attribute but should be stored as plain int
    - ``IntEnum`` (and any enum with ``.name``) returns the member name
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, enum.IntFlag):  # must be before .name check
        return int(value)
    if (name := getattr(value, "name", None)) is not None:  # IntEnum, Enum, etc.
        return str(name)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    # Everything else (datetime, timedelta, date, etc.)
    return str(value)


# ---------------------------------------------------------------------------
# Entity construction functions
# ---------------------------------------------------------------------------


def add_simple_entity(
    device_id: str | None,
    uuid: str,
    name: str,
    value: int | float | str | bool,
    unit: str | None,
    is_diagnostic: bool,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
) -> None:
    """Add a simple single-value entity."""
    has_unit = bool(unit and unit.strip())
    dc = resolve_device_class(unit, name)
    entity_key = PassiveBluetoothEntityKey(uuid, device_id)
    entity_descriptions[entity_key] = SensorEntityDescription(
        key=uuid,
        name=name,
        device_class=dc,
        native_unit_of_measurement=unit if has_unit else None,
        state_class=SensorStateClass.MEASUREMENT
        if has_unit and not is_diagnostic
        else None,
        entity_category=EntityCategory.DIAGNOSTIC if is_diagnostic else None,
        entity_registry_enabled_default=not is_diagnostic,
    )
    entity_names[entity_key] = name
    entity_data[entity_key] = value
    _LOGGER.debug(
        "Added entity %s = %s %s (diag=%s) for device %s",
        name,
        value,
        unit or "",
        is_diagnostic,
        device_id,
    )


def _add_leaf_entity(
    *,
    device_id: str | None,
    uuid: str,
    char_name: str,
    qualified_name: str,
    field_name: str,
    field_value: object,
    parent_unit: str | None,
    is_diagnostic: bool,
    has_multiple_units: bool,
    spec: CharacteristicSpec | None,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
) -> None:
    """Create a single leaf entity from a struct field value.

    Handles unit resolution, device class mapping, state class
    assignment, and value coercion for one scalar field.
    """
    entity_key = PassiveBluetoothEntityKey(f"{uuid}_{qualified_name}", device_id)
    field_display_name = f"{char_name} {qualified_name.replace('_', ' ').title()}"

    # Non-numeric struct fields (bool, enum, flag) should not
    # inherit the parent characteristic's unit.
    field_ha_value = to_ha_state(field_value)
    is_numeric = (
        isinstance(field_ha_value, (int, float))
        and not isinstance(field_value, (bool, enum.IntFlag))
        and getattr(field_value, "name", None) is None
    )

    if is_numeric:
        # Try per-field unit from GSS spec first
        per_field = resolve_field_unit(field_name, spec)
        if per_field is not None:
            field_unit = per_field
        elif has_multiple_units:
            # Spec has mixed units but no per-field match —
            # safer to drop than inherit the wrong unit.
            field_unit = None
        else:
            # Single-unit characteristic: inherit parent unit.
            field_unit = parent_unit
    else:
        field_unit = None

    has_unit = bool(field_unit and field_unit.strip())
    dc = resolve_device_class(field_unit, field_display_name)

    # Cumulative fields should use TOTAL_INCREASING, not MEASUREMENT
    if has_unit and not is_diagnostic and qualified_name in CUMULATIVE_FIELD_NAMES:
        state_class = SensorStateClass.TOTAL_INCREASING
    elif has_unit and not is_diagnostic:
        state_class = SensorStateClass.MEASUREMENT
    else:
        state_class = None

    entity_descriptions[entity_key] = SensorEntityDescription(
        key=f"{uuid}_{qualified_name}",
        name=field_display_name,
        device_class=dc,
        native_unit_of_measurement=field_unit if has_unit else None,
        state_class=state_class,
        entity_category=EntityCategory.DIAGNOSTIC if is_diagnostic else None,
        entity_registry_enabled_default=not is_diagnostic,
    )
    entity_names[entity_key] = field_display_name
    entity_data[entity_key] = field_ha_value
    _LOGGER.debug(
        "Added struct field entity %s = %s (unit=%s, diag=%s) for device %s",
        field_display_name,
        field_value,
        field_unit or "none",
        is_diagnostic,
        device_id,
    )


def add_struct_entities(
    device_id: str | None,
    uuid: str,
    char_name: str,
    struct_value: object,
    unit: str | None,
    is_diagnostic: bool,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    *,
    spec: CharacteristicSpec | None = None,
    _prefix: str = "",
) -> None:
    """Add entities from a msgspec Struct, recursing into nested structs.

    Each leaf (non-struct) field becomes a single HA entity.  Nested
    structs are recursed into so their leaf fields are also exposed,
    with the key and display name prefixed to avoid collisions.

    Per-field units are resolved from the GSS specification when the
    characteristic has multiple units (e.g. Heart Rate Measurement
    where heart_rate is bpm but energy_expended is kJ).  When no
    per-field unit is available AND the spec has multiple units, the
    parent unit is dropped to avoid incorrect labelling.
    """
    if not hasattr(struct_value, "__struct_fields__"):
        _LOGGER.debug("Value for %s is not a struct, cannot extract fields", char_name)
        return

    # Determine if the spec has mixed units across fields
    if spec is not None:
        _field_units = {f.unit_id for f in spec.structure if f.unit_id}
        has_multiple_units = len(_field_units) > 1
    else:
        has_multiple_units = False

    for field_name in struct_value.__struct_fields__:
        field_value = getattr(struct_value, field_name)
        qualified_name = f"{_prefix}{field_name}" if _prefix else field_name

        # Recurse into nested structs
        if hasattr(field_value, "__struct_fields__"):
            add_struct_entities(
                device_id,
                uuid,
                char_name,
                field_value,
                unit,
                is_diagnostic,
                entity_descriptions,
                entity_names,
                entity_data,
                spec=spec,
                _prefix=f"{qualified_name}_",
            )
            continue

        # Expand sequence fields (tuple/list) into per-element entities.
        # Single-element sequences produce one entity (no index suffix);
        # multi-element sequences get _0, _1, … suffixed entities.
        if isinstance(field_value, (tuple, list)) and not isinstance(
            field_value, (str, bytes)
        ):
            elements = list(field_value)
            if not elements:
                _LOGGER.debug(
                    "Skipping empty sequence field %s for device %s",
                    qualified_name,
                    device_id,
                )
                continue
            for idx, elem in enumerate(elements):
                _add_leaf_entity(
                    device_id=device_id,
                    uuid=uuid,
                    char_name=char_name,
                    qualified_name=(
                        qualified_name
                        if len(elements) == 1
                        else f"{qualified_name}_{idx}"
                    ),
                    field_name=field_name,
                    field_value=elem,
                    parent_unit=unit,
                    is_diagnostic=is_diagnostic,
                    has_multiple_units=has_multiple_units,
                    spec=spec,
                    entity_descriptions=entity_descriptions,
                    entity_names=entity_names,
                    entity_data=entity_data,
                )
            continue

        _add_leaf_entity(
            device_id=device_id,
            uuid=uuid,
            char_name=char_name,
            qualified_name=qualified_name,
            field_name=field_name,
            field_value=field_value,
            parent_unit=unit,
            is_diagnostic=is_diagnostic,
            has_multiple_units=has_multiple_units,
            spec=spec,
            entity_descriptions=entity_descriptions,
            entity_names=entity_names,
            entity_data=entity_data,
        )


def add_sig_characteristic_entity(
    device_id: str | None,
    data: SIGCharacteristicData,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    *,
    seen_uuids: set[str] | None = None,
) -> None:
    """Add entity from SIGCharacteristicData using library metadata.

    Uses the characteristic's ``role`` property to decide whether and
    how to create entities:

    - CONTROL / FEATURE → skipped (not useful as HA sensor entities)
    - MEASUREMENT       → sensor entities (state_class=MEASUREMENT)
    - STATUS / INFO     → diagnostic entities
    - UNKNOWN           → fall back to value-type heuristic
    """
    # Get characteristic class and metadata from registry
    char_class: type[BaseCharacteristic[Any]] | None = (
        CharacteristicRegistry.get_characteristic_class_by_uuid(data.uuid)
    )
    if char_class is None:
        _LOGGER.debug(
            "No characteristic class found for UUID %s on device %s",
            data.uuid,
            device_id,
        )
        return

    char_instance: BaseCharacteristic[Any] = char_class()
    char_name: str = char_instance.name
    unit: str = char_instance.unit
    role: CharacteristicRole = char_instance.role
    parsed_value = data.parsed_value

    uuid_obj = (
        data.uuid if isinstance(data.uuid, BluetoothUUID) else BluetoothUUID(data.uuid)
    )

    _LOGGER.debug(
        "Processing %s (uuid=%s, role=%s, python_type=%s, unit=%s) for device %s",
        char_name,
        uuid_obj.short_form,
        role.value,
        type(parsed_value).__name__,
        unit,
        device_id,
    )

    # Gate: skip characteristics that are not useful as sensor entities
    if role in SKIP_ROLES:
        _LOGGER.debug(
            "Skipping %s (role=%s) for device %s",
            char_name,
            role.value,
            device_id,
        )
        return

    # Determine entity category from role
    is_diagnostic = role in DIAGNOSTIC_ROLES

    # Track this UUID so the service_data path can skip it
    if seen_uuids is not None:
        seen_uuids.add(str(data.uuid).lower())

    # Route on the actual value, not declared python_type
    if hasattr(parsed_value, "__struct_fields__"):
        add_struct_entities(
            device_id,
            str(data.uuid),
            char_name,
            parsed_value,
            unit,
            is_diagnostic,
            entity_descriptions,
            entity_names,
            entity_data,
            spec=char_instance.spec,
        )
    else:
        add_simple_entity(
            device_id,
            str(data.uuid),
            char_name,
            to_ha_state(parsed_value),
            unit,
            is_diagnostic,
            entity_descriptions,
            entity_names,
            entity_data,
        )


def add_interpreted_entities(
    device_id: str | None,
    interpreter_name: str | None,
    interpreted_data: object,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    *,
    seen_uuids: set[str] | None = None,
) -> None:
    """Add entities from interpreted advertising data."""
    # Handle SIGCharacteristicData from the library
    if isinstance(interpreted_data, SIGCharacteristicData):
        add_sig_characteristic_entity(
            device_id,
            interpreted_data,
            entity_descriptions,
            entity_names,
            entity_data,
            seen_uuids=seen_uuids,
        )
        return

    _LOGGER.debug(
        "Unknown interpreted data type %s for device %s",
        type(interpreted_data).__name__,
        device_id,
    )


def add_service_data_entities(
    device_id: str | None,
    service_data: dict[BluetoothUUID, bytes],
    translator: BluetoothSIGTranslator,
    entity_descriptions: dict[PassiveBluetoothEntityKey, EntityDescription],
    entity_names: dict[PassiveBluetoothEntityKey, str | None],
    entity_data: dict[PassiveBluetoothEntityKey, float | int | str | bool],
    *,
    skip_uuids: set[str] | None = None,
) -> None:
    """Add entities from service data using GATT characteristic metadata.

    Args:
        device_id: Device identifier (None for default device).
        service_data: Map of service UUID to raw payload bytes.
        translator: BluetoothSIGTranslator for characteristic lookup/parsing.
        entity_descriptions: Accumulator for entity descriptions.
        entity_names: Accumulator for entity names.
        entity_data: Accumulator for entity data values.
        skip_uuids: UUIDs already handled by interpreted data (optional).

    """
    for service_uuid, data in service_data.items():
        if skip_uuids and str(service_uuid).lower() in skip_uuids:
            _LOGGER.debug(
                "Skipping service data %s — already created from interpreted data",
                service_uuid,
            )
            continue
        try:
            char_info = translator.get_characteristic_info_by_uuid(str(service_uuid))
            if not char_info:
                continue

            # Use role to gate service data entities
            char_class: type[BaseCharacteristic[Any]] | None = (
                CharacteristicRegistry.get_characteristic_class_by_uuid(service_uuid)
            )
            if char_class is not None:
                role: CharacteristicRole = char_class().role
                if role in SKIP_ROLES:
                    _LOGGER.debug(
                        "Skipping service data %s (role=%s)",
                        char_info.name,
                        role.value,
                    )
                    continue
                is_diagnostic = role in DIAGNOSTIC_ROLES
            else:
                # Fallback: characteristics with a unit are likely measurements
                has_unit = bool(char_info.unit and char_info.unit.strip())
                is_diagnostic = not has_unit

            parsed_value = translator.parse_characteristic(
                str(service_uuid), data, None
            )

            entity_key = PassiveBluetoothEntityKey(
                f"svc_{str(service_uuid).replace('-', '_')}", device_id
            )

            svc_unit = char_info.unit
            has_unit = bool(svc_unit and svc_unit.strip())
            svc_name = char_info.name or f"Service {service_uuid}"
            dc = resolve_device_class(svc_unit, svc_name)

            entity_descriptions[entity_key] = SensorEntityDescription(
                key=f"svc_{service_uuid}",
                name=svc_name,
                device_class=dc,
                native_unit_of_measurement=svc_unit if has_unit else None,
                state_class=SensorStateClass.MEASUREMENT
                if has_unit and not is_diagnostic
                else None,
                entity_category=EntityCategory.DIAGNOSTIC if is_diagnostic else None,
                entity_registry_enabled_default=not is_diagnostic,
            )

            entity_names[entity_key] = svc_name
            entity_data[entity_key] = to_ha_state(parsed_value)
        except SpecialValueDetectedError:
            _LOGGER.debug(
                "Service data %s contains special sentinel value, skipping",
                service_uuid,
            )
        except Exception:
            _LOGGER.warning(
                "Could not parse service data for %s",
                service_uuid,
                exc_info=True,
            )
