"""Discovery state tracking for Bluetooth SIG Devices integration.

Encapsulates the sets and timers used to track which BLE devices have
been seen, rejected, or had discovery flows fired. Also handles
stale-device cleanup and LRU eviction of the seen-devices set.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DEFAULT_STALE_DEVICE_TIMEOUT,
    MAX_REJECTED_DEVICES,
    MAX_SEEN_DEVICES,
    STALE_DEVICE_CLEANUP_INTERVAL,
    BLEAddress,
)

if TYPE_CHECKING:
    from .coordinator import BluetoothSIGCoordinator

_LOGGER = logging.getLogger(__name__)


class DiscoveryTracker:
    """Track BLE device discovery state and manage stale-device cleanup.

    Owns:
    - ``seen_devices`` — addresses we have seen at least once
    - ``rejected_devices`` — addresses fully evaluated with no support
    - ``discovery_triggered`` — addresses for which a discovery flow was fired
    - ``last_seen_time`` — monotonic timestamp of last advertisement
    - ``filtered_ephemeral_count`` — counter for filtered RPA/NRPA addresses
    - Periodic stale-device cleanup timer
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: BluetoothSIGCoordinator,
        *,
        stale_device_timeout: int = DEFAULT_STALE_DEVICE_TIMEOUT,
    ) -> None:
        """Initialise the discovery tracker."""
        self._hass = hass
        self._coordinator = coordinator
        self._stale_device_timeout = stale_device_timeout

        self.seen_devices: set[BLEAddress] = set()
        self.rejected_devices: set[BLEAddress] = set()
        self.rejection_reasons: dict[BLEAddress, str] = {}
        self.discovery_triggered: set[BLEAddress] = set()
        self.last_seen_time: dict[BLEAddress, float] = {}
        self.filtered_ephemeral_count: int = 0

        self._cancel_stale_cleanup: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_rejected(self, address: BLEAddress) -> bool:
        """Return True if the address has been rejected."""
        return address in self.rejected_devices

    def is_discovery_triggered(self, address: BLEAddress) -> bool:
        """Return True if a discovery flow was already fired for this address."""
        return address in self.discovery_triggered

    def mark_discovery_triggered(self, address: BLEAddress) -> None:
        """Record that a discovery flow has been fired for *address*."""
        self.discovery_triggered.add(address)

    def mark_rejected(self, address: BLEAddress, reason: str = "") -> None:
        """Mark *address* as fully evaluated with no support."""
        if len(self.rejected_devices) < MAX_REJECTED_DEVICES:
            self.rejected_devices.add(address)
            if reason:
                self.rejection_reasons[address] = reason

    def record_sighting(self, address: BLEAddress) -> bool:
        """Record that *address* was seen in an advertisement.

        Returns True if this is the first sighting for this address.
        """
        self.last_seen_time[address] = time.monotonic()

        if address in self.seen_devices:
            return False

        # Enforce cap to prevent unbounded growth
        if len(self.seen_devices) >= MAX_SEEN_DEVICES:
            self._evict_oldest_seen()

        self.seen_devices.add(address)
        return True

    def increment_filtered_ephemeral(self) -> int:
        """Increment and return the ephemeral-address filter counter."""
        self.filtered_ephemeral_count += 1
        return self.filtered_ephemeral_count

    # ------------------------------------------------------------------
    # LRU eviction
    # ------------------------------------------------------------------

    def _evict_oldest_seen(self) -> None:
        """Remove the oldest entries from ``seen_devices`` when over capacity.

        Uses ``last_seen_time`` to identify the least-recently-seen addresses
        and removes them from all discovery tracking sets.
        """
        evict_count = max(1, len(self.seen_devices) // 4)
        sorted_addrs = sorted(
            self.seen_devices,
            key=lambda a: self.last_seen_time.get(a, 0.0),
        )
        for addr in sorted_addrs[:evict_count]:
            self.seen_devices.discard(addr)
            self.discovery_triggered.discard(addr)
            self.rejected_devices.discard(addr)
            self.rejection_reasons.pop(addr, None)
            self.last_seen_time.pop(addr, None)
            # Also clean probe failure counts from the GATT manager
            self._coordinator.gatt_manager.probe_failures.pop(addr, None)
        _LOGGER.debug(
            "Evicted %d oldest addresses from tracking sets (seen=%d)",
            evict_count,
            len(self.seen_devices),
        )

    # ------------------------------------------------------------------
    # Stale cleanup
    # ------------------------------------------------------------------

    @callback
    def async_cleanup_stale_devices(self, _now: object = None) -> None:
        """Periodically remove stale entries from unbounded tracking sets.

        Addresses that have not been seen for ``DEFAULT_STALE_DEVICE_TIMEOUT``
        are removed from all tracking sets and the coordinator's device cache.
        Addresses with active processor coordinators or config entries are
        never evicted.
        """
        now = time.monotonic()
        cutoff = now - self._stale_device_timeout

        coord = self._coordinator
        stale_addresses: list[BLEAddress] = [
            addr
            for addr, last_seen in self.last_seen_time.items()
            if last_seen < cutoff
            and addr not in coord.processor_coordinators
            and not coord.has_config_entry(addr)
        ]

        if not stale_addresses:
            return

        gatt = coord.gatt_manager
        for addr in stale_addresses:
            self.seen_devices.discard(addr)
            self.discovery_triggered.discard(addr)
            self.rejected_devices.discard(addr)
            self.rejection_reasons.pop(addr, None)
            self.last_seen_time.pop(addr, None)
            gatt.probe_failures.pop(addr, None)
            gatt.probe_results.pop(addr, None)
            coord.devices.pop(addr, None)

        # Cap rejected_devices if it grew beyond the limit
        if len(self.rejected_devices) > MAX_REJECTED_DEVICES:
            excess = len(self.rejected_devices) - MAX_REJECTED_DEVICES
            for addr in list(self.rejected_devices)[:excess]:
                self.rejected_devices.discard(addr)
                self.rejection_reasons.pop(addr, None)
                self.last_seen_time.pop(addr, None)

        _LOGGER.debug(
            "Stale cleanup: removed %d addresses (seen=%d, rejected=%d, "
            "discovery_triggered=%d)",
            len(stale_addresses),
            len(self.seen_devices),
            len(self.rejected_devices),
            len(self.discovery_triggered),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def async_start(self) -> None:
        """Start the periodic stale-device cleanup timer."""
        self._cancel_stale_cleanup = async_track_time_interval(
            self._hass,
            self.async_cleanup_stale_devices,
            STALE_DEVICE_CLEANUP_INTERVAL,
            cancel_on_shutdown=True,
        )

    def async_stop(self) -> None:
        """Cancel the stale-device cleanup timer and clear all tracked state."""
        if self._cancel_stale_cleanup is not None:
            self._cancel_stale_cleanup()
            self._cancel_stale_cleanup = None

        self.seen_devices.clear()
        self.rejected_devices.clear()
        self.rejection_reasons.clear()
        self.discovery_triggered.clear()
        self.last_seen_time.clear()

    def remove_device(self, address: BLEAddress) -> None:
        """Allow re-discovery if a device's config entry is removed."""
        self.discovery_triggered.discard(address)
