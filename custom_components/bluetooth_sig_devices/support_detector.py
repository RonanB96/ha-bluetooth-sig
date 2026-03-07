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
from typing import TYPE_CHECKING

from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from .advertisement_manager import AdvertisementManager
from .const import CharacteristicInfo

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
    ) -> list[CharacteristicInfo]:
        """Return parseable characteristics from advertisement data.

        Returns a list of ``CharacteristicInfo`` named tuples for each
        supported characteristic detected in the advertisement or cached
        GATT probe.  An empty list means no supported data was found.
        """
        address = service_info.address
        found: list[CharacteristicInfo] = []

        if service_info.service_data:
            found.extend(self._check_service_data(address, service_info))

        if service_info.manufacturer_data:
            found.extend(self._check_manufacturer_data(address, service_info))

        found.extend(self._check_gatt_probes(address))

        return found

    def has_supported_data(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Check if the device advertisement contains data we can parse."""
        return len(self.get_supported_characteristics(service_info)) > 0

    def build_characteristics_summary(
        self,
        address: str,
        supported: list[CharacteristicInfo],
        known_characteristics: dict[str, dict[str, str]],
    ) -> str:
        """Build a formatted characteristics string and update tracking.

        Accumulates discovered characteristic names in
        *known_characteristics* and returns a comma-separated summary.
        """
        device_chars = known_characteristics.setdefault(address, {})
        for info in supported:
            device_chars[info.uuid] = info.name

        unique_names = list(dict.fromkeys(device_chars.values()))
        return ", ".join(unique_names)

    def get_known_characteristics(
        self,
        address: str,
        known_characteristics: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        """Return ``{uuid_str: human_name}`` for all known characteristics."""
        result = dict(known_characteristics.get(address, {}))

        # Merge GATT probe results
        probe_result = self._gatt_manager.probe_results.get(address)
        if probe_result:
            for char_uuid in probe_result.supported_char_uuids:
                uuid_str = str(char_uuid)
                if uuid_str not in result:
                    char_class = (
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
        address: str,
        service_info: BluetoothServiceInfoBleak,
    ) -> list[CharacteristicInfo]:
        """Check service data UUIDs against the library registries."""
        found: list[CharacteristicInfo] = []

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
                    for char_spec in svc_chars:
                        char_uuid = getattr(char_spec, "uuid", None)
                        if char_uuid is not None:
                            char_uuid_str = str(char_uuid)
                        else:
                            char_uuid_str = getattr(char_spec, "uuid_str", uuid_str)
                        found.append(
                            CharacteristicInfo(
                                uuid=char_uuid_str,
                                name=getattr(char_spec, "name", None) or char_uuid_str,
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
                found.append(
                    CharacteristicInfo(uuid=uuid_str, name=char_info.name or uuid_str)
                )
                continue

            _LOGGER.debug(
                "Device %s has unknown service data UUID %s",
                address,
                uuid_str,
            )

        return found

    def _check_manufacturer_data(
        self,
        address: str,
        service_info: BluetoothServiceInfoBleak,
    ) -> list[CharacteristicInfo]:
        """Check manufacturer data via library interpreter parsing."""
        found: list[CharacteristicInfo] = []

        try:
            advertisement = AdvertisementManager.convert_advertisement(service_info)
            if advertisement.interpreted_data is not None:
                _LOGGER.debug(
                    "Device %s has interpreted manufacturer data: %s",
                    address,
                    type(advertisement.interpreted_data).__name__,
                )
                interp_name = advertisement.interpreter_name or "Manufacturer Data"
                found.append(CharacteristicInfo(uuid="manufacturer", name=interp_name))
        except Exception as exc:
            _LOGGER.debug(
                "Device %s failed to parse manufacturer data: %s",
                address,
                exc,
            )

        return found

    def _check_gatt_probes(self, address: str) -> list[CharacteristicInfo]:
        """Check cached GATT probe results for parseable characteristics."""
        found: list[CharacteristicInfo] = []
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
            char_class = CharacteristicRegistry.get_characteristic_class_by_uuid(
                char_uuid
            )
            name = char_class().name if char_class else char_uuid.short_form
            found.append(CharacteristicInfo(uuid=str(char_uuid), name=name))

        return found
