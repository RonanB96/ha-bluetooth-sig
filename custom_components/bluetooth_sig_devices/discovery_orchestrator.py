"""Discovery orchestration for Bluetooth SIG Devices.

Routes BLE device advertisements to the correct handling path:

- **Confirmed devices** → schedule GATT re-probe via backoff.
- **Unconfirmed devices** → evaluate advertisement support, fire
  discovery flow, or schedule a GATT probe and reject on exhaustion.
- **GATT probe callbacks** → handle success (fire discovery) and
  failure (reject if exhausted; never reject confirmed devices).

The ``DiscoveryOrchestrator`` receives a reference to the parent
coordinator and delegates to its sub-managers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.helpers import discovery_flow

from .advertisement_converter import convert_advertisement, get_manufacturer_name
from .const import (
    DOMAIN,
    BLEAddress,
    CharacteristicSource,
    DiscoveredCharacteristic,
    DiscoveryData,
)
from .device_validator import GATTProbeResult

if TYPE_CHECKING:
    from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)


class DiscoveryOrchestrator:
    """Routes BLE devices to the correct discovery / probe path.

    Composed into ``BluetoothSIGCoordinator`` — receives a coordinator
    reference at construction and accesses its sub-managers.
    """

    def __init__(self, coordinator: BluetoothSIGCoordinator) -> None:
        self._coord = coordinator

    # ------------------------------------------------------------------
    # Device routing
    # ------------------------------------------------------------------

    def ensure_device_processor(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Route a discovered BLE device to the correct handling path.

        **Confirmed** — the user has already added the device.
        **Unconfirmed** — the device has not been added.
        """
        address = service_info.address
        coord = self._coord

        if address in coord.processor_coordinators or coord.has_config_entry(address):
            self._schedule_confirmed_gatt_probe(service_info)
            return

        self._handle_unconfirmed_device(service_info)

    # ------------------------------------------------------------------
    # Unconfirmed device path
    # ------------------------------------------------------------------

    def _handle_unconfirmed_device(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Evaluate an unconfirmed device for support and fire discovery.

        Parseable advertisement data fires a discovery flow immediately.
        Connectable devices with no parseable data are probed via GATT
        with a hard failure limit.
        """
        address = service_info.address
        tracker = self._coord.discovery_tracker

        if tracker.is_rejected(address):
            return

        if tracker.is_discovery_triggered(address):
            _LOGGER.debug("Device %s: discovery already triggered — skipping", address)
            return

        has_advert_data = self._coord.support_detector.has_supported_data(service_info)

        if not has_advert_data:
            self._try_gatt_probe_or_reject(service_info)
            return

        tracker.mark_discovery_triggered(address)
        self._fire_advertisement_discovery_flow(service_info)

    def _try_gatt_probe_or_reject(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Attempt a GATT probe for an unconfirmed device, or reject it.

        Called when advertisement data is not interpretable.  Each
        condition is checked explicitly so the rejection reason is
        always accurate.
        """
        address = service_info.address
        tracker = self._coord.discovery_tracker
        gatt = self._coord.gatt_manager

        # Already handled — probe completed or in flight.
        if address in gatt.probe_results or address in gatt.pending_probes:
            return

        if not service_info.connectable:
            reason = "non-connectable with no parseable advertisement data"
            tracker.mark_rejected(address, reason)
            _LOGGER.info("Device %s rejected: %s", address, reason)
            return

        if gatt.is_failures_exhausted(address):
            reason = "all GATT probe attempts exhausted"
            tracker.mark_rejected(address, reason)
            _LOGGER.info("Device %s rejected: %s", address, reason)
            return

        gatt.schedule_probe(service_info)

    def _fire_advertisement_discovery_flow(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Fire a discovery flow for a device with parseable advertisement data."""
        address = service_info.address
        coord = self._coord
        gatt = coord.gatt_manager

        advertisement = None
        manufacturer = ""
        try:
            advertisement = convert_advertisement(service_info)
            manufacturer = get_manufacturer_name(advertisement) or ""
        except (ValueError, TypeError, KeyError, AttributeError):
            _LOGGER.warning("Could not extract manufacturer for %s", address)

        # Fall back to GATT Manufacturer Name String if advert had none
        if not manufacturer:
            probe_result = gatt.probe_results.get(address)
            if probe_result and probe_result.manufacturer_name:
                manufacturer = probe_result.manufacturer_name

        # Collect characteristic names for the discovery card
        supported = coord.support_detector.get_supported_characteristics(service_info)
        manufacturer_interp = (
            coord.support_detector.check_manufacturer_support(
                service_info, advertisement=advertisement
            )
            or ""
        )
        char_names = coord.support_detector.build_characteristics_summary(
            address,
            supported,
            coord.known_characteristics,
            manufacturer_name=manufacturer_interp,
        )

        _LOGGER.info(
            "Firing discovery flow for device %s (%s) — characteristics: %s",
            address,
            service_info.name or "unknown",
            char_names or "none",
        )
        discovery_flow.async_create_flow(
            coord.hass,
            DOMAIN,
            context={"source": "integration_discovery"},
            data=DiscoveryData(
                address=address,
                name=service_info.name or f"Bluetooth Device {address[-8:]}",
                characteristics=char_names,
                manufacturer=manufacturer,
                rssi=service_info.rssi,
            ),
        )

    # ------------------------------------------------------------------
    # GATT probe callbacks (invoked by GATTManager)
    # ------------------------------------------------------------------

    def handle_probe_success(
        self,
        address: BLEAddress,
        result: GATTProbeResult,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Handle a successful GATT probe.

        Triggers an immediate poll for confirmed devices and fires a
        discovery flow for unconfirmed devices with parseable data.
        """
        coord = self._coord

        # Trigger an immediate poll so cached GATT data reaches
        # entities without waiting for a new advertisement.
        coord.notify_probe_complete(address)

        if coord.has_config_entry(address):
            return

        # --- Unconfirmed device: fire discovery flow ---
        coord.discovery_tracker.mark_discovery_triggered(address)

        # Build DiscoveredCharacteristic list from probe result
        from .support_detector import SupportDetector

        supported: list[DiscoveredCharacteristic] = []
        for char_uuid in result.supported_char_uuids:
            instance = SupportDetector._resolve_characteristic_by_uuid(
                char_uuid,
                fallback_name=char_uuid.short_form,
            )
            supported.append(
                DiscoveredCharacteristic(
                    characteristic=instance,
                    source=CharacteristicSource.GATT,
                )
            )

        char_names = coord.support_detector.build_characteristics_summary(
            address,
            supported,
            coord.known_characteristics,
        )

        # Resolve manufacturer: advertisement first, GATT fallback
        manufacturer = ""
        try:
            advertisement = convert_advertisement(service_info)
            manufacturer = get_manufacturer_name(advertisement) or ""
        except (ValueError, TypeError, KeyError, AttributeError):
            _LOGGER.debug(
                "Could not extract advert manufacturer for %s",
                address,
            )
        if not manufacturer and result.manufacturer_name:
            manufacturer = result.manufacturer_name

        _LOGGER.info(
            "Firing discovery flow for device %s (%s) — characteristics: %s",
            address,
            service_info.name or "unknown",
            char_names or "none",
        )
        discovery_flow.async_create_flow(
            coord.hass,
            DOMAIN,
            context={"source": "integration_discovery"},
            data=DiscoveryData(
                address=address,
                name=service_info.name or f"Bluetooth Device {address[-8:]}",
                characteristics=char_names,
                manufacturer=manufacturer,
                rssi=service_info.rssi,
            ),
        )

    def handle_probe_failure(
        self,
        address: BLEAddress,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Handle a failed GATT probe attempt.

        For unconfirmed devices, checks whether probe attempts are
        exhausted and rejects the device if so.  Confirmed devices
        are never rejected.
        """
        coord = self._coord

        if coord.has_config_entry(address):
            _LOGGER.debug(
                "GATT probe failed for confirmed device %s — will retry",
                address,
            )
            return

        gatt = coord.gatt_manager
        if gatt.is_failures_exhausted(address):
            reason = "all GATT probe attempts exhausted"
            coord.discovery_tracker.mark_rejected(address, reason)
            _LOGGER.warning(
                "All %d GATT probe attempts failed for %s — "
                "device cannot be auto-discovered via GATT",
                gatt._max_probe_retries,
                address,
            )

    # ------------------------------------------------------------------
    # Confirmed device GATT probe
    # ------------------------------------------------------------------

    def _schedule_confirmed_gatt_probe(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Schedule GATT probing for a user-confirmed device if applicable.

        Called on every advertisement for confirmed devices.  The
        ``GATTManager.schedule_probe_for_confirmed_device()`` method
        gates on its own backoff timer and dedup checks, so calling
        this frequently is safe (O(1) dict lookups).

        Skips silently if the device is not connectable or GATT is
        disabled via the device's config entry options.
        """
        if not service_info.connectable:
            return
        if not self._coord._is_gatt_enabled(service_info.address):
            return
        self._coord.gatt_manager.schedule_probe_for_confirmed_device(service_info)
