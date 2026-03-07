"""Entity metadata resolution for Bluetooth SIG Devices integration.

Pure-function utilities for resolving Home Assistant entity metadata
(device class, unit of measurement, state class) from bluetooth-sig
library data.  These functions have no side effects and no dependency
on coordinator or Home Assistant state.
"""

from __future__ import annotations

from bluetooth_sig.registry.uuids.units import UnitsRegistry
from bluetooth_sig.types.registry.common import CharacteristicSpec
from homeassistant.components.sensor import SensorDeviceClass

# ---------------------------------------------------------------------------
# Unit → SensorDeviceClass fallback mapping.
#
# Used when no UUID mapping is available (e.g. struct field sub-entities
# which do not have their own UUID, or unknown characteristics with
# recognisable units).  Only truly 1:1 unambiguous mappings are included;
# every entry here must be valid per HA's DEVICE_CLASS_UNITS.
#
# Deliberately EXCLUDED (ambiguous, multi-class, or unit string mismatch):
#   "%"               — BATTERY / HUMIDITY / MOISTURE / POWER_FACTOR
#                       (disambiguated by name; see resolve_device_class)
#   "Pa"              — both PRESSURE and ATMOSPHERIC_PRESSURE accept it
#   "mmHg"            — not in HA's UnitOfPressure enum
#   "ppm"             — CO2, CO, CH4, or VOC_PARTS; cannot differentiate
#   "ppb"             — NO2, O3, SO2, or VOC_PARTS; cannot differentiate
#   "m"               — DISTANCE or UnitOfTime.MONTHS collision
#   "mm"              — DISTANCE or PRECIPITATION
#   "m/s"             — SPEED or WIND_SPEED
#   "°"               — WIND_DIRECTION but also magnetic declination/bearing
#   "dB SPL"          — not a recognised HA unit constant (HA uses "dB")
#   "beats per minute" — no matching HA SensorDeviceClass
#   "kilowatt hour"   — library long-form; HA expects "kWh"
#   "kilometre per hour" — library long-form; HA expects "km/h"
#   "watt per square metre" — library long-form; HA expects "W/m²"
#   "kg/m³"           — not in HA's ABSOLUTE_HUMIDITY units (g/m³ or mg/m³)
#   "T"               — no HA SensorDeviceClass for magnetic flux density
#   "N"               — no HA SensorDeviceClass for force
# ---------------------------------------------------------------------------
UNIT_TO_DEVICE_CLASS: dict[str, SensorDeviceClass] = {
    # Temperature
    "°C": SensorDeviceClass.TEMPERATURE,
    "K": SensorDeviceClass.TEMPERATURE,
    # Electrical
    "V": SensorDeviceClass.VOLTAGE,
    "mV": SensorDeviceClass.VOLTAGE,
    "A": SensorDeviceClass.CURRENT,
    "mA": SensorDeviceClass.CURRENT,
    "W": SensorDeviceClass.POWER,
    "mW": SensorDeviceClass.POWER,
    "kW": SensorDeviceClass.POWER,
    "VA": SensorDeviceClass.APPARENT_POWER,
    "kVA": SensorDeviceClass.APPARENT_POWER,
    # Energy
    "J": SensorDeviceClass.ENERGY,
    "kJ": SensorDeviceClass.ENERGY,
    "Wh": SensorDeviceClass.ENERGY,
    "kWh": SensorDeviceClass.ENERGY,
    # Frequency
    "Hz": SensorDeviceClass.FREQUENCY,
    "kHz": SensorDeviceClass.FREQUENCY,
    # Mass
    "kg": SensorDeviceClass.WEIGHT,
    "g": SensorDeviceClass.WEIGHT,
    # Illuminance
    "lx": SensorDeviceClass.ILLUMINANCE,
    # Duration — HA UnitOfTime.SECONDS = "s"; unambiguous in BLE context
    "s": SensorDeviceClass.DURATION,
    "ms": SensorDeviceClass.DURATION,
    "min": SensorDeviceClass.DURATION,
    # Signal strength
    "dBm": SensorDeviceClass.SIGNAL_STRENGTH,
    "dB": SensorDeviceClass.SIGNAL_STRENGTH,
    # Pressure — Pa is excluded (PRESSURE vs ATMOSPHERIC_PRESSURE ambiguity),
    # but hPa is used exclusively for atmospheric pressure in practice
    "hPa": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    "mbar": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
}


# Struct field names that indicate a cumulative total.
CUMULATIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "cumulative_wheel_revolutions",
        "cumulative_crank_revolutions",
        "accumulated_energy",
        "energy_expended",
        "total_distance",
        "accumulated_torque",
    }
)


def resolve_field_unit(
    field_name: str,
    spec: CharacteristicSpec | None,
) -> str | None:
    """Resolve per-field unit from the GSS specification.

    Looks up the ``FieldSpec`` matching *field_name* in the characteristic's
    GSS ``structure`` list and converts its ``unit_id`` to a human-readable
    symbol via the SIG units registry.

    Returns ``None`` when no per-field unit is available.
    """
    if spec is None or not spec.structure:
        return None

    for field_spec in spec.structure:
        if field_spec.python_name == field_name:
            uid = field_spec.unit_id
            if uid is None:
                return None
            full_id = f"org.bluetooth.unit.{uid}"
            units_reg = UnitsRegistry.get_instance()
            info = units_reg.get_info(full_id)
            if info and info.symbol:
                return info.symbol
            return None

    return None


def normalize_uuid_short(uuid_str: str) -> str | None:
    """Return the 4-character uppercase hex short UUID, or ``None``.

    Handles three input formats:
    - Full UUID:        ``"00002A6E-0000-1000-8000-00805F9B34FB"``
    - GATT-prefixed:   ``"gatt_2a6e"``
    - Already short:   ``"2A6E"``
    """
    s = uuid_str.strip().upper()
    if s.startswith("GATT_"):
        s = s[5:]
    if "-" in s:
        # Full-form: first segment is "00002A6E"; strip leading zeros.
        s = s.split("-")[0].lstrip("0") or "0"
    # Bluetooth SIG short UUIDs are exactly 4 hex characters.
    if 1 <= len(s) <= 4 and all(c in "0123456789ABCDEF" for c in s):
        return s.zfill(4)
    return None


def resolve_device_class(
    unit: str | None,
    name: str,
) -> SensorDeviceClass | None:
    """Derive ``SensorDeviceClass`` from unit and entity name.

    Resolution order:
    1. Name-based disambiguation for "%" (battery vs humidity).
    2. Unit-only fallback for clearly 1:1 cases.

    No per-UUID or per-characteristic maps — resolution is entirely
    driven by the unit string and the entity name provided by the
    library.
    """
    if not unit or not unit.strip():
        return None

    # 1. Disambiguate "%" by entity name (SIG naming convention)
    if unit == "%":
        lower_name = name.lower()
        if "battery" in lower_name:
            return SensorDeviceClass.BATTERY
        if "humidity" in lower_name:
            return SensorDeviceClass.HUMIDITY
        return None  # generic percentage — no device class

    # 2. Unit-only fallback
    return UNIT_TO_DEVICE_CLASS.get(unit)
