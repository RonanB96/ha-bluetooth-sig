"""Support detection for Bluetooth SIG Devices integration.

Consolidates all logic for determining whether a BLE device's
advertisement (or GATT probe result) contains data parseable by the
``bluetooth-sig-python`` library.  Previously this logic was split
between ``coordinator.py`` and ``device_validator.py``.

The ``SupportDetector`` class is the **single source of truth** for
support detection — ``BluetoothSIGCoordinator`` delegates here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.gatt.characteristics.base import BaseCharacteristic
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.gatt.characteristics.unknown import UnknownCharacteristic
from bluetooth_sig.types.advertising import AdvertisementData
from bluetooth_sig.types.data_types import CharacteristicInfo
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from .advertisement_manager import AdvertisementManager
from .const import BLEAddress, CharacteristicSource, DiscoveredCharacteristic

if TYPE_CHECKING:
    from .gatt_manager import GATTManager

_LOGGER = logging.getLogger(__name__)


class SupportDetector:
    """Determines whether a BLE device has parseable SIG data.

    Checks advertisement service data, manufacturer data (via library
    interpreters), and cached GATT probe results.
    """

    def __init__(
        self,
        translator: BluetoothSIGTranslator,
        gatt_manager: GATTManager,
    ) -> None:
        """Initialise the support detector.

        Args:
            translator: Library translator for UUID lookups.
            gatt_manager: GATT manager for accessing probe results.

        """
        self._translator = translator
        self._gatt_manager = gatt_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_supported_characteristics(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> list[DiscoveredCharacteristic]:
        """Return parseable characteristics from advertisement data.

        Returns a list of ``DiscoveredCharacteristic`` named tuples for each
        supported characteristic detected in the advertisement or cached
        GATT probe.  An empty list means no supported data was found.

        Manufacturer data (interpreted via library interpreters) is **not**
        included here because it does not map to real GATT characteristics.
        Use ``check_manufacturer_support`` for that.
        """
        address = service_info.address
        found: list[DiscoveredCharacteristic] = []

        if service_info.service_data:
            found.extend(self._check_service_data(address, service_info))

        found.extend(self._check_gatt_probes(address))

        return found

    def check_manufacturer_support(
        self,
        service_info: BluetoothServiceInfoBleak,
        advertisement: AdvertisementData | None = None,
    ) -> str | None:
        """Return interpreter name if manufacturer data is parseable, else None.

        If *advertisement* is supplied it is reused; otherwise a fresh
        conversion is performed.  Callers that also need the
        ``AdvertisementData`` for other purposes should convert once and
        pass the result here to avoid duplicate work.
        """
        if not service_info.manufacturer_data:
            return None
        try:
            if advertisement is None:
                advertisement = AdvertisementManager.convert_advertisement(service_info)
            if advertisement.interpreted_data is not None:
                _LOGGER.debug(
                    "Device %s has interpreted manufacturer data: %s",
                    service_info.address,
                    type(advertisement.interpreted_data).__name__,
                )
                return advertisement.interpreter_name or "Manufacturer Data"
        except Exception as exc:
            _LOGGER.debug(
                "Device %s failed to parse manufacturer data: %s",
                service_info.address,
                exc,
            )
        return None

    def has_supported_data(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Check if the device advertisement contains data we can parse."""
        if self.get_supported_characteristics(service_info):
            return True
        return self.check_manufacturer_support(service_info) is not None

    def build_characteristics_summary(
        self,
        address: BLEAddress,
        supported: list[DiscoveredCharacteristic],
        known_characteristics: dict[BLEAddress, dict[str, str]],
        manufacturer_name: str = "",
    ) -> str:
        """Build a formatted characteristics string grouped by source.

        Accumulates discovered characteristic names in
        *known_characteristics* and returns a multi-line summary
        grouped by data source (advertisement, manufacturer, GATT).
        """
        device_chars = known_characteristics.setdefault(address, {})
        for info in supported:
            device_chars[str(info.characteristic.uuid)] = info.characteristic.name

        # Group by source, preserving insertion order and deduplicating names
        adv_names: list[str] = []
        gatt_names: list[str] = []
        seen: set[str] = set()

        for info in supported:
            name = info.characteristic.name
            if name in seen:
                continue
            seen.add(name)
            if info.source is CharacteristicSource.GATT:
                gatt_names.append(name)
            else:
                adv_names.append(name)

        sections: list[str] = []

        if adv_names:
            lines = "\n".join(f"  \u2022 {n}" for n in adv_names)
            sections.append(f"**Advertising data:**\n{lines}")

        if manufacturer_name:
            sections.append(f"**Manufacturer data:**\n  \u2022 {manufacturer_name}")

        if gatt_names:
            lines = "\n".join(f"  \u2022 {n}" for n in gatt_names)
            sections.append(f"**Connected (GATT) data:**\n{lines}")

        return "\n\n".join(sections) if sections else ""

    def get_known_characteristics(
        self,
        address: BLEAddress,
        known_characteristics: dict[BLEAddress, dict[str, str]],
    ) -> dict[str, str]:
        """Return ``{uuid_str: human_name}`` for all known characteristics."""
        result = dict(known_characteristics.get(address, {}))

        # Merge GATT probe results
        probe_result = self._gatt_manager.probe_results.get(address)
        if probe_result:
            for char_uuid in probe_result.supported_char_uuids:
                uuid_str = str(char_uuid)
                if uuid_str not in result:
                    char_class: type[BaseCharacteristic[Any]] | None = (
                        CharacteristicRegistry.get_characteristic_class_by_uuid(
                            char_uuid
                        )
                    )
                    result[uuid_str] = (
                        char_class().name if char_class else char_uuid.short_form
                    )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_service_data(
        self,
        address: BLEAddress,
        service_info: BluetoothServiceInfoBleak,
    ) -> list[DiscoveredCharacteristic]:
        """Check service data UUIDs against the library registries."""
        found: list[DiscoveredCharacteristic] = []

        for uuid_str in service_info.service_data:
            svc_info = self._translator.get_service_info_by_uuid(uuid_str)
            if svc_info is not None:
                svc_chars = self._translator.get_service_characteristics(uuid_str)
                if svc_chars:
                    _LOGGER.debug(
                        "Device %s advertises service %s with %d parseable"
                        " characteristics",
                        address,
                        svc_info.name,
                        len(svc_chars),
                    )
                    for char_instance in svc_chars:
                        found.append(
                            DiscoveredCharacteristic(
                                characteristic=char_instance,
                                source=CharacteristicSource.ADVERTISEMENT,
                            )
                        )
                    continue
                _LOGGER.debug(
                    "Device %s advertises known service %s but no registered"
                    " characteristics",
                    address,
                    svc_info.name,
                )

            char_info = self._translator.get_characteristic_info_by_uuid(uuid_str)
            if char_info is not None:
                _LOGGER.debug(
                    "Device %s has supported characteristic UUID %s (%s)",
                    address,
                    uuid_str,
                    char_info.name,
                )
                instance = self._resolve_characteristic_by_uuid(
                    BluetoothUUID(uuid_str),
                    fallback_name=char_info.name or uuid_str,
                )
                found.append(
                    DiscoveredCharacteristic(
                        characteristic=instance,
                        source=CharacteristicSource.ADVERTISEMENT,
                    )
                )
                continue

            _LOGGER.debug(
                "Device %s has unknown service data UUID %s",
                address,
                uuid_str,
            )

        return found

    def _check_gatt_probes(self, address: BLEAddress) -> list[DiscoveredCharacteristic]:
        """Check cached GATT probe results for parseable characteristics."""
        found: list[DiscoveredCharacteristic] = []
        gatt = self._gatt_manager

        if address not in gatt.probe_results:
            return found

        probe_result = gatt.probe_results[address]
        if not probe_result.has_support():
            return found

        _LOGGER.debug(
            "Device %s has %d parseable GATT characteristics",
            address,
            probe_result.parseable_count,
        )
        for char_uuid in probe_result.supported_char_uuids:
            instance = self._resolve_characteristic_by_uuid(
                char_uuid, fallback_name=char_uuid.short_form
            )
            found.append(
                DiscoveredCharacteristic(
                    characteristic=instance,
                    source=CharacteristicSource.GATT,
                )
            )

        return found

    # ------------------------------------------------------------------
    # Characteristic resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_characteristic_by_uuid(
        char_uuid: BluetoothUUID,
        fallback_name: str,
    ) -> BaseCharacteristic[Any]:
        """Resolve a UUID to a ``BaseCharacteristic`` instance."""
        char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(char_uuid)
        if char_class is not None:
            return char_class()
        return UnknownCharacteristic(
            info=CharacteristicInfo(uuid=char_uuid, name=fallback_name)
        )
