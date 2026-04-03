"""Per-device advertisement tracking for Bluetooth SIG Devices.

Provides ``AdvertisementManager`` — the instance-based per-device tracker
that stores the latest advertisement, RSSI, and registered callbacks.

Stateless conversion logic lives in ``advertisement_converter``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from bluetooth_sig.types.advertising import (
    AdvertisementData,
    BLEAdvertisingFlags,
)
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .advertisement_converter import convert_advertisement
from .const import BLEAddress

_LOGGER = logging.getLogger(__name__)


class AdvertisementManager:
    """Per-device advertisement tracking, RSSI, and callbacks.

    Tracks per-device advertisement state, RSSI, and registered
    callbacks.  For stateless conversion use
    ``advertisement_converter.convert_advertisement()`` directly.
    """

    def __init__(
        self,
        address: BLEAddress,
        *,
        hass: HomeAssistant | None = None,
    ) -> None:
        """Initialise the advertisement manager.

        Args:
            address: Bluetooth device address (MAC address).
            hass: Home Assistant instance (needed for refreshing adverts).

        """
        self._address = address
        self._hass = hass

        # Per-device tracking state
        self._latest_advertisement: AdvertisementData | None = None
        self._disconnected_callback: Callable[[], None] | None = None
        self._advertisement_callbacks: list[Callable[[AdvertisementData], None]] = []

    @property
    def connectable(self) -> bool:
        """Return whether the device last advertised as connectable.

        Derived from the ``LE_GENERAL_DISCOVERABLE_MODE`` flag in the
        latest advertisement — no separate state to keep in sync.
        """
        if self._latest_advertisement is None:
            return False
        flags = self._latest_advertisement.ad_structures.properties.flags
        return bool(flags & BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE)

    # ------------------------------------------------------------------
    # Per-device advertisement tracking (instance methods)
    # ------------------------------------------------------------------

    def set_hass(self, hass: HomeAssistant) -> None:
        """Set the Home Assistant instance for refresh support."""
        self._hass = hass

    def set_disconnected_callback(self, callback: Callable[[], None] | None) -> None:
        """Set the callback for disconnection events."""
        self._disconnected_callback = callback

    def fire_disconnected(self) -> None:
        """Fire the disconnected callback if registered."""
        if self._disconnected_callback:
            self._disconnected_callback()

    def on_advertisement_received(self, advertisement: AdvertisementData) -> None:
        """Handle receiving an advertisement."""
        self._latest_advertisement = advertisement
        for cb in list(self._advertisement_callbacks):
            cb(advertisement)

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

    async def get_latest_advertisement(
        self, refresh: bool = False
    ) -> AdvertisementData | None:
        """Return the latest advertisement data.

        Args:
            refresh: If True and hass is available, fetch fresh data from
                     HA's Bluetooth component.

        Returns:
            Latest ``AdvertisementData``, or ``None`` if none received yet.

        """
        if refresh and self._hass is not None:
            service_info = bluetooth.async_last_service_info(
                self._hass, self._address, connectable=False
            )
            if service_info:
                self._latest_advertisement = convert_advertisement(service_info)

        return self._latest_advertisement

    async def get_advertisement_rssi(self, refresh: bool = False) -> int | None:
        """Get the RSSI from advertisement data.

        Args:
            refresh: If True, attempt to get fresh advertisement data.

        Returns:
            RSSI value in dBm, or ``None`` if no advertisement received yet.

        """
        if refresh:
            await self.get_latest_advertisement(refresh=True)

        return self._get_cached_rssi()

    def _get_cached_rssi(self) -> int | None:
        """Return the cached RSSI, or ``None`` if unavailable."""
        if self._latest_advertisement is not None:
            return self._latest_advertisement.rssi
        return None

    def read_rssi_sync(self) -> int:
        """Return the cached RSSI from the latest advertisement.

        Raises:
            ValueError: If no advertisement with RSSI has been received yet.

        """
        rssi = self._get_cached_rssi()
        if rssi is not None:
            return rssi

        raise ValueError(
            f"No RSSI available for {self._address}. "
            "Call get_latest_advertisement(refresh=True) first."
        )
