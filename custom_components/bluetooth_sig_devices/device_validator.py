"""Device validation for Bluetooth SIG Devices integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.gatt.characteristics.registry import CharacteristicRegistry
from bluetooth_sig.types.uuid import BluetoothUUID

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)


@dataclass
class GATTProbeResult:
    """Result from probing a device's GATT services.

    This is a simple data container for probe results, used to track
    what characteristics a device supports.
    """

    address: str
    name: str | None = None
    parseable_count: int = 0
    supported_char_uuids: list[BluetoothUUID] = field(default_factory=list)

    def has_support(self) -> bool:
        """Check if device has any parseable characteristics."""
        return self.parseable_count > 0


class DeviceValidator:
    """Validates if a BLE device should be tracked by this integration.

    This class determines whether a discovered Bluetooth device has data
    that can be parsed by the bluetooth-sig-python library, either from
    advertisement data or GATT characteristics.
    """

    def __init__(self, translator: BluetoothSIGTranslator) -> None:
        """Initialize the device validator.

        Args:
            translator: BluetoothSIGTranslator instance for parsing

        """
        self.translator = translator
        self._registry = CharacteristicRegistry

    def should_track_device(
        self,
        service_info: BluetoothServiceInfoBleak,
        gatt_probe_result: GATTProbeResult | None = None,
    ) -> tuple[bool, str]:
        """Determine if device should be tracked.

        Checks both advertisement data and GATT capabilities (if available)
        to determine if the device has any data we can parse.

        Args:
            service_info: Bluetooth service info from Home Assistant
            gatt_probe_result: GATT probe result (optional)

        Returns:
            Tuple of (should_track, reason)

        """
        address = service_info.address

        # First check advertisement data
        if self._has_parseable_advert_data(service_info):
            _LOGGER.debug(
                "Device %s has parseable advertisement data",
                address,
            )
            return True, "Parseable advertisement data"

        # Check interpreted manufacturer data
        if self._has_interpreted_manufacturer_data(service_info):
            _LOGGER.debug(
                "Device %s has interpreted manufacturer data",
                address,
            )
            return True, "Interpreted manufacturer data"

        # If we have GATT probe result, check those
        if gatt_probe_result and gatt_probe_result.parseable_count > 0:
            _LOGGER.debug(
                "Device %s has %d parseable GATT characteristics",
                address,
                gatt_probe_result.parseable_count,
            )
            return (
                True,
                f"{gatt_probe_result.parseable_count} parseable GATT characteristics",
            )

        _LOGGER.debug(
            "Device %s has no supported data",
            address,
        )
        return False, "No supported data found"

    def _has_parseable_advert_data(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Check if advertisement contains parseable SIG service data.

        Args:
            service_info: Bluetooth service info

        Returns:
            True if any service data UUID is a known SIG characteristic

        """
        if not service_info.service_data:
            return False

        for uuid_str in service_info.service_data:
            try:
                uuid = BluetoothUUID(uuid_str)
                char_class = self._registry.get_characteristic_class_by_uuid(uuid)
                if char_class is not None:
                    _LOGGER.debug(
                        "Found parseable service data UUID: %s",
                        uuid.short_form,
                    )
                    return True
            except (ValueError, TypeError):
                continue

        return False

    def _has_interpreted_manufacturer_data(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Check if manufacturer data can be interpreted by the library.

        Args:
            service_info: Bluetooth service info

        Returns:
            True if manufacturer data can be parsed

        """
        if not service_info.manufacturer_data:
            return False

        # Import here to avoid circular imports
        from .device_adapter import HomeAssistantBluetoothAdapter

        try:
            advertisement = HomeAssistantBluetoothAdapter.convert_advertisement(
                service_info
            )
            return advertisement.interpreted_data is not None
        except Exception:
            return False

    def get_supported_characteristic_uuids(
        self,
        discovered_uuids: list[BluetoothUUID],
    ) -> list[BluetoothUUID]:
        """Filter discovered UUIDs to only those we can parse.

        Args:
            discovered_uuids: List of discovered characteristic UUIDs

        Returns:
            List of UUIDs that have parsers in the library

        """
        supported = []
        for uuid in discovered_uuids:
            char_class = self._registry.get_characteristic_class_by_uuid(uuid)
            if char_class is not None:
                supported.append(uuid)
        return supported

    def get_characteristic_info(
        self,
        uuid: BluetoothUUID,
    ) -> tuple[str, str | None] | None:
        """Get characteristic name and unit from the library.

        Args:
            uuid: Characteristic UUID

        Returns:
            Tuple of (name, unit) or None if not found

        """
        char_class = self._registry.get_characteristic_class_by_uuid(uuid)
        if char_class is None:
            return None

        char_instance = char_class()
        return char_instance.name, char_instance.unit

    def should_probe_device(
        self,
        service_info: BluetoothServiceInfoBleak,
        already_tracked_addresses: set[str],
        custom_device_addresses: set[str],
        cached_capabilities_addresses: set[str],
    ) -> tuple[bool, str]:
        """Determine if a device should be probed for GATT capabilities.

        Args:
            service_info: Bluetooth service info
            already_tracked_addresses: Set of addresses already being tracked
            custom_device_addresses: Set of user-configured custom device addresses
            cached_capabilities_addresses: Set of addresses with cached capabilities

        Returns:
            Tuple of (should_probe, reason)

        """
        address = service_info.address
        address_upper = address.upper()

        # Always probe custom devices
        if address_upper in custom_device_addresses:
            return True, "Custom device configured by user"

        # Must be connectable
        if not service_info.connectable:
            return False, "Device is not connectable"

        # Don't probe if we already have capabilities
        if address in cached_capabilities_addresses:
            return False, "Capabilities already cached"

        # Don't probe if already tracked via advertisements
        if address in already_tracked_addresses:
            # But check if we should add GATT polling for additional data
            # For now, skip if already tracked
            return False, "Already tracked via advertisements"

        # Probe connectable devices that we don't have info for
        return True, "Connectable device without cached capabilities"


def create_validator(translator: BluetoothSIGTranslator) -> DeviceValidator:
    """Create a DeviceValidator instance.

    Factory function for creating validators.

    Args:
        translator: BluetoothSIGTranslator instance

    Returns:
        DeviceValidator instance

    """
    return DeviceValidator(translator)
