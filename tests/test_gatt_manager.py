"""Tests for gatt_manager.py — GATT probing, polling, and lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.bluetooth_sig_devices.coordinator import (
    BluetoothSIGCoordinator,
)
from custom_components.bluetooth_sig_devices.device_validator import GATTProbeResult
from custom_components.bluetooth_sig_devices.gatt_poller import (
    _MANUFACTURER_NAME_UUID,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service_info(
    address: str = "AA:BB:CC:DD:EE:FF",
    name: str = "Test Device",
    connectable: bool = True,
) -> BluetoothServiceInfoBleak:
    """Build a minimal BluetoothServiceInfoBleak."""
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-65,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=connectable,
        time=0,
        tx_power=None,
    )


def _make_coordinator(mock_hass: MagicMock) -> BluetoothSIGCoordinator:
    """Build a coordinator with mocked hass."""
    entry = MagicMock()
    entry.options = {}
    entry.data = {}
    return BluetoothSIGCoordinator(mock_hass, entry)


# ---------------------------------------------------------------------------
# Module-level resolution
# ---------------------------------------------------------------------------


class TestModuleLevelResolution:
    """Test that _MANUFACTURER_NAME_UUID is resolved from the library."""

    def test_manufacturer_name_uuid_resolved(self) -> None:
        """Test that _MANUFACTURER_NAME_UUID is a valid BluetoothUUID."""
        assert _MANUFACTURER_NAME_UUID is not None
        assert isinstance(_MANUFACTURER_NAME_UUID, BluetoothUUID)
        assert "2a29" in str(_MANUFACTURER_NAME_UUID).lower()


# ---------------------------------------------------------------------------
# is_failures_exhausted boundary tests
# ---------------------------------------------------------------------------


class TestIsFailuresExhausted:
    """Tests for is_failures_exhausted — only checks failure count."""

    def test_not_exhausted_fresh(self) -> None:
        """Fresh device has no failures."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        assert gatt.is_failures_exhausted("AA:BB:CC:DD:EE:FF") is False

    def test_exhausted_at_max_failures(self) -> None:
        """Failure count at max is exhausted."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_failures["AA:BB:CC:DD:EE:FF"] = gatt._max_probe_retries
        assert gatt.is_failures_exhausted("AA:BB:CC:DD:EE:FF") is True

    def test_not_exhausted_below_max(self) -> None:
        """Failure count below max is not exhausted."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_failures["AA:BB:CC:DD:EE:FF"] = gatt._max_probe_retries - 1
        assert gatt.is_failures_exhausted("AA:BB:CC:DD:EE:FF") is False

    def test_probe_result_does_not_affect_exhaustion(self) -> None:
        """A successful probe result does not count as 'failures exhausted'."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = MagicMock()
        assert gatt.is_failures_exhausted("AA:BB:CC:DD:EE:FF") is False


# ---------------------------------------------------------------------------
# remove_device
# ---------------------------------------------------------------------------


class TestRemoveDevice:
    """Tests for remove_device cleanup."""

    def test_remove_device_clears_all_state(self) -> None:
        """Test remove_device clears probe_results, probe_failures, initial_gatt_cache."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        gatt.probe_results[addr] = MagicMock()
        gatt.probe_failures[addr] = 2
        gatt._initial_gatt_cache[addr] = MagicMock()

        gatt.remove_device(addr)

        assert addr not in gatt.probe_results
        assert addr not in gatt.probe_failures
        assert addr not in gatt._initial_gatt_cache

    def test_remove_device_nonexistent_is_noop(self) -> None:
        """Test remove_device with unknown address is safe."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.remove_device("00:00:00:00:00:00")  # Should not raise


# ---------------------------------------------------------------------------
# async_stop
# ---------------------------------------------------------------------------


class TestAsyncStop:
    """Tests for async_stop task cancellation."""

    async def test_async_stop_cancels_tasks(self) -> None:
        """Test async_stop cancels all in-flight probe tasks."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        loop = asyncio.get_running_loop()
        task1 = loop.create_future()
        task1.set_result(None)
        task2 = loop.create_future()
        task2.set_result(None)
        gatt._probe_tasks["AA:BB:CC:DD:EE:01"] = task1
        gatt._probe_tasks["AA:BB:CC:DD:EE:02"] = task2
        gatt.pending_probes.add("AA:BB:CC:DD:EE:01")
        gatt.pending_probes.add("AA:BB:CC:DD:EE:02")

        await gatt.async_stop()

        assert len(gatt._probe_tasks) == 0
        assert len(gatt.pending_probes) == 0


# ---------------------------------------------------------------------------
# schedule_probe deduplication
# ---------------------------------------------------------------------------


class TestScheduleProbe:
    """Tests for schedule_probe deduplication."""

    def test_schedule_probe_creates_task(self) -> None:
        """Test schedule_probe creates a task for a fresh device."""
        mock_hass = MagicMock()
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        service_info = _make_service_info()
        gatt.schedule_probe(service_info)

        assert "AA:BB:CC:DD:EE:FF" in gatt.pending_probes
        assert "AA:BB:CC:DD:EE:FF" in gatt._probe_tasks

    def test_schedule_probe_dedup_same_address_twice(self) -> None:
        """Test schedule_probe ignores duplicate address."""
        mock_hass = MagicMock()
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        service_info = _make_service_info()
        gatt.schedule_probe(service_info)
        gatt.schedule_probe(service_info)

        assert mock_hass.async_create_task.call_count == 1

    def test_schedule_probe_skips_already_probed(self) -> None:
        """Test schedule_probe skips when probe_results already has address."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = MagicMock()
        gatt.schedule_probe(_make_service_info())

        mock_hass.async_create_task.assert_not_called()

    def test_schedule_probe_ignores_failure_count(self) -> None:
        """schedule_probe does not check failure count — coordinator decides."""
        mock_hass = MagicMock()
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_failures["AA:BB:CC:DD:EE:FF"] = gatt._max_probe_retries
        gatt.schedule_probe(_make_service_info())

        mock_hass.async_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# async_poll_gatt_characteristics
# ---------------------------------------------------------------------------


class TestAsyncPollGattCharacteristics:
    """Tests for poll path: no support, no device, connect error, disconnect error."""

    async def test_poll_no_probe_result_returns_none(self) -> None:
        """Test poll returns None when no probe result exists."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        result = await gatt.async_poll_gatt_characteristics("AA:BB:CC:DD:EE:FF")
        assert result is None

    async def test_poll_no_support_returns_none(self) -> None:
        """Test poll returns None when probe found no support."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=0,
            supported_char_uuids=(),
        )

        result = await gatt.async_poll_gatt_characteristics("AA:BB:CC:DD:EE:FF")
        assert result is None

    async def test_poll_no_device_returns_none(self) -> None:
        """Test poll returns None when device instance is missing."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )
        # No device in coord.devices

        result = await gatt.async_poll_gatt_characteristics("AA:BB:CC:DD:EE:FF")
        assert result is None

    async def test_poll_connect_raises_returns_none(self) -> None:
        """Test poll returns None when connect raises."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        mock_device = MagicMock()
        mock_device.connect = AsyncMock(side_effect=Exception("connect failed"))
        mock_device.disconnect = AsyncMock()
        coord.devices["AA:BB:CC:DD:EE:FF"] = mock_device

        result = await gatt.async_poll_gatt_characteristics("AA:BB:CC:DD:EE:FF")
        assert result is None
        mock_device.disconnect.assert_called_once()

    async def test_poll_disconnect_error_logged(self) -> None:
        """Test poll logs warning when disconnect fails after poll."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.disconnect = AsyncMock(side_effect=Exception("disc fail"))
        # _build_gatt_entities will fail since device.read() doesn't exist properly
        # but disconnect error path is still exercised
        mock_device.read = AsyncMock(return_value=75)
        coord.devices["AA:BB:CC:DD:EE:FF"] = mock_device

        # Should not raise — disconnect error is caught and logged
        await gatt.async_poll_gatt_characteristics("AA:BB:CC:DD:EE:FF")
        # Result may be None or a PassiveBluetoothDataUpdate depending on
        # whether _build_gatt_entities succeeds; the key assertion is no exception
        mock_device.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# async_poll_gatt_with_semaphore — cached initial data
# ---------------------------------------------------------------------------


class TestAsyncPollWithSemaphore:
    """Tests for async_poll_gatt_with_semaphore cached path."""

    async def test_returns_cached_initial_data(self) -> None:
        """Test first call returns cached data without connecting."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        mock_update = MagicMock()
        gatt._initial_gatt_cache["AA:BB:CC:DD:EE:FF"] = mock_update

        result = await gatt.async_poll_gatt_with_semaphore("AA:BB:CC:DD:EE:FF")
        assert result is mock_update
        # Cache should be consumed
        assert "AA:BB:CC:DD:EE:FF" not in gatt._initial_gatt_cache

    async def test_falls_through_to_live_poll(self) -> None:
        """Test subsequent call delegates to live poll."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        # No cached data → should call async_poll_gatt_characteristics
        gatt.async_poll_gatt_characteristics = AsyncMock(return_value=None)
        result = await gatt.async_poll_gatt_with_semaphore("AA:BB:CC:DD:EE:FF")

        assert result is None
        gatt.async_poll_gatt_characteristics.assert_called_once_with(
            "AA:BB:CC:DD:EE:FF"
        )


# ---------------------------------------------------------------------------
# async_probe_device edge cases
# ---------------------------------------------------------------------------


class TestAsyncProbeDevice:
    """Tests for async_probe_device already-probed and failure-limit paths."""

    async def test_already_probed_returns_cached(self) -> None:
        """Test async_probe_device returns cached result when already probed."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        cached_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=2,
            supported_char_uuids=(BluetoothUUID("2A19"), BluetoothUUID("2A6E")),
        )
        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = cached_result

        service_info = _make_service_info()
        result = await gatt.async_probe_device(service_info)
        assert result is cached_result

    async def test_probe_attempts_despite_high_failure_count(self) -> None:
        """async_probe_device does not guard on failure count — coordinator decides."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_failures["AA:BB:CC:DD:EE:FF"] = gatt._max_probe_retries

        service_info = _make_service_info()
        # Without a BLE device available, the probe will fail for I/O reasons
        # but the key assertion is that it doesn't short-circuit on failure count.
        result = await gatt.async_probe_device(service_info)
        # Returns None because no real BLE device, not because of failure count.
        assert result is None
        # Failure count was incremented by the probe attempt itself.
        assert gatt.probe_failures["AA:BB:CC:DD:EE:FF"] == gatt._max_probe_retries + 1

    async def test_probe_disconnect_failure_logged(self) -> None:
        """Test disconnect failure after probe is logged as warning."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        # Create a mock device that connects, discovers, but disconnect fails
        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.connected.discover_services = AsyncMock(return_value=[])
        mock_device.disconnect = AsyncMock(side_effect=Exception("disc error"))
        coord.devices["AA:BB:CC:DD:EE:FF"] = mock_device

        service_info = _make_service_info()

        with patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ):
            result = await gatt.async_probe_device(service_info)

        # Should still return a result (0 parseable chars)
        assert result is not None
        assert result.parseable_count == 0
        # disconnect should have been called despite error
        mock_device.disconnect.assert_called_once()

    async def test_probe_excluded_service_skipped(self) -> None:
        """Test async_probe_device skips excluded services."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        # Set up a mock service whose UUID maps to an excluded short form
        mock_service = MagicMock()
        # Use a uuid whose short_form.upper() is in excluded_service_uuids
        mock_service.uuid = "00001800-0000-1000-8000-00805f9b34fb"  # GAP
        mock_service.characteristics = {}

        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.connected.discover_services = AsyncMock(return_value=[mock_service])
        mock_device.disconnect = AsyncMock()
        coord.devices["AA:BB:CC:DD:EE:FF"] = mock_device

        service_info = _make_service_info()

        with patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ):
            result = await gatt.async_probe_device(service_info)

        assert result is not None
        assert result.parseable_count == 0

    async def test_probe_excluded_characteristic_skipped(self) -> None:
        """Test async_probe_device skips excluded characteristics."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        # Manually set excluded_char_uuids to include 2A00
        coord._excluded_char_uuids = frozenset({"2A00"})

        mock_service = MagicMock()
        mock_service.uuid = "0000180a-0000-1000-8000-00805f9b34fb"
        mock_service.characteristics = {
            "00002a00-0000-1000-8000-00805f9b34fb": MagicMock(),
        }

        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.connected.discover_services = AsyncMock(return_value=[mock_service])
        mock_device.disconnect = AsyncMock()
        coord.devices["AA:BB:CC:DD:EE:FF"] = mock_device

        service_info = _make_service_info()

        with patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ):
            result = await gatt.async_probe_device(service_info)

        assert result is not None
        # The excluded char should not count
        assert result.parseable_count == 0


# ---------------------------------------------------------------------------
# _read_chars_connected and _build_gatt_entities
# ---------------------------------------------------------------------------


class TestReadCharsConnected:
    """Tests for _read_chars_connected and _build_gatt_entities."""

    async def test_read_chars_no_entities_returns_none(self) -> None:
        """Test _read_chars_connected returns None when all reads fail."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        mock_device = MagicMock()
        mock_device.read = AsyncMock(side_effect=Exception("read failed"))

        probe_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        result = await gatt._read_chars_connected(
            "AA:BB:CC:DD:EE:FF", mock_device, probe_result
        )
        assert result is None

    async def test_read_chars_success_returns_update(self) -> None:
        """Test _read_chars_connected returns update when read succeeds."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        # Battery Level returns an integer
        mock_device = MagicMock()
        mock_device.read = AsyncMock(return_value=75)

        probe_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        result = await gatt._read_chars_connected(
            "AA:BB:CC:DD:EE:FF", mock_device, probe_result
        )
        assert result is not None
        assert len(result.entity_data) >= 1

    async def test_read_chars_none_value_skipped(self) -> None:
        """Test _build_gatt_entities skips None parsed values."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        mock_device = MagicMock()
        mock_device.read = AsyncMock(return_value=None)

        probe_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        result = await gatt._read_chars_connected(
            "AA:BB:CC:DD:EE:FF", mock_device, probe_result
        )
        assert result is None


# ---------------------------------------------------------------------------
# async_poll_gatt_characteristics — poll returns data / empty data
# ---------------------------------------------------------------------------


class TestPollGattReturnsData:
    """Tests for async_poll_gatt_characteristics with successful data."""

    async def test_poll_success_returns_update(self) -> None:
        """Test poll returns PassiveBluetoothDataUpdate when read succeeds."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        gatt.probe_results[addr] = GATTProbeResult(
            address=addr,
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.disconnect = AsyncMock()
        mock_device.read = AsyncMock(return_value=75)
        coord.devices[addr] = mock_device

        result = await gatt.async_poll_gatt_characteristics(addr)
        assert result is not None
        assert len(result.entity_data) >= 1

    async def test_poll_empty_data_returns_none(self) -> None:
        """Test poll returns None when reads succeed but no entities are built."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        gatt.probe_results[addr] = GATTProbeResult(
            address=addr,
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.disconnect = AsyncMock()
        # Return None for all reads → no entities built
        mock_device.read = AsyncMock(return_value=None)
        coord.devices[addr] = mock_device

        result = await gatt.async_poll_gatt_characteristics(addr)
        assert result is None

    async def test_poll_disconnect_failure_logged_not_raised(self) -> None:
        """Test poll logs warning on disconnect failure but does not raise."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        gatt.probe_results[addr] = GATTProbeResult(
            address=addr,
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        mock_device = MagicMock()
        mock_device.connect = AsyncMock()
        mock_device.disconnect = AsyncMock(side_effect=Exception("disc fail"))
        mock_device.read = AsyncMock(return_value=75)
        coord.devices[addr] = mock_device

        # Must not raise
        await gatt.async_poll_gatt_characteristics(addr)
        mock_device.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# async_probe_and_setup — timeout and manufacturer fallback
# ---------------------------------------------------------------------------


class TestAsyncProbeAndSetup:
    """Tests for async_probe_and_setup timeout and manufacturer name paths."""

    async def test_timeout_increments_failure(self) -> None:
        """Test probe_and_setup handles TimeoutError."""
        mock_hass = MagicMock()
        mock_hass.async_create_task = MagicMock(
            side_effect=lambda coro, *a, **kw: (coro.close(), MagicMock())[1]
        )
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        service_info = _make_service_info(address=addr)

        async def _timeout_wait_for(coro, *, timeout=None):
            """Close the coroutine to avoid 'never awaited' warning, then raise."""
            coro.close()
            raise TimeoutError("timed out")

        with patch(
            "custom_components.bluetooth_sig_devices.gatt_manager.asyncio.wait_for",
            side_effect=_timeout_wait_for,
        ):
            await gatt.async_probe_and_setup(service_info)

        assert gatt.probe_failures.get(addr, 0) >= 1

    async def test_probe_and_setup_invokes_success_callback(self) -> None:
        """async_probe_and_setup invokes on_probe_success with correct args."""
        mock_hass = MagicMock()
        mock_hass.async_create_task = MagicMock(
            side_effect=lambda coro, *a, **kw: (coro.close(), MagicMock())[1]
        )
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        service_info = _make_service_info(address=addr)

        probe_result = GATTProbeResult(
            address=addr,
            name="Test",
            parseable_count=1,
            supported_char_uuids=(BluetoothUUID("2A19"),),
        )

        callback_calls: list[
            tuple[str, GATTProbeResult, BluetoothServiceInfoBleak]
        ] = []
        gatt._on_probe_success = lambda a, r, si: callback_calls.append((a, r, si))

        with patch.object(
            gatt,
            "async_probe_device",
            new_callable=AsyncMock,
            return_value=probe_result,
        ):
            await gatt.async_probe_and_setup(service_info)

        assert len(callback_calls) == 1
        assert callback_calls[0][0] == addr
        assert callback_calls[0][1] is probe_result
        assert callback_calls[0][2] is service_info


# ---------------------------------------------------------------------------
# schedule_probe_for_confirmed_device
# ---------------------------------------------------------------------------


class TestScheduleProbeForConfirmedDevice:
    """Tests for schedule_probe_for_confirmed_device bypass logic."""

    def test_schedules_probe_first_time(self) -> None:
        """Test probe is scheduled when no previous result or failures."""
        mock_hass = MagicMock()
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.schedule_probe_for_confirmed_device(_make_service_info())

        assert "AA:BB:CC:DD:EE:FF" in gatt.pending_probes
        mock_hass.async_create_task.assert_called_once()

    def test_skips_when_result_already_cached(self) -> None:
        """Test no new probe when probe_results already has an entry."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.probe_results["AA:BB:CC:DD:EE:FF"] = MagicMock()
        gatt.schedule_probe_for_confirmed_device(_make_service_info())

        mock_hass.async_create_task.assert_not_called()

    def test_skips_when_probe_pending(self) -> None:
        """Test no new probe when one is already in flight."""
        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        gatt.pending_probes.add("AA:BB:CC:DD:EE:FF")
        gatt.schedule_probe_for_confirmed_device(_make_service_info())

        mock_hass.async_create_task.assert_not_called()

    def test_reschedules_after_backoff_expires(self) -> None:
        """Test re-probe fires after the backoff window has elapsed."""
        import time

        from custom_components.bluetooth_sig_devices.const import (
            CONFIRMED_DEVICE_PROBE_BACKOFF,
        )

        mock_hass = MagicMock()
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"

        # Simulate exhausted failures with a stale last-attempt timestamp
        gatt.probe_failures[addr] = gatt._max_probe_retries
        gatt._confirmed_probe_last_attempt[addr] = (
            time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 1
        )

        gatt.schedule_probe_for_confirmed_device(_make_service_info())

        # Probe scheduled despite exhausted failures (failures not cleared).
        assert addr in gatt.pending_probes
        mock_hass.async_create_task.assert_called_once()

    def test_does_not_reschedule_within_backoff(self) -> None:
        """Test re-probe is suppressed while within the backoff window."""
        import time

        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        gatt.probe_failures[addr] = gatt._max_probe_retries
        # Last attempt was very recent
        gatt._confirmed_probe_last_attempt[addr] = time.monotonic()

        gatt.schedule_probe_for_confirmed_device(_make_service_info())

        mock_hass.async_create_task.assert_not_called()

    def test_backoff_gate_applies_unlike_schedule_probe(self) -> None:
        """schedule_probe_for_confirmed_device applies backoff; schedule_probe does not.

        schedule_probe() is a simple dedup gate (no failure/backoff awareness).
        schedule_probe_for_confirmed_device() adds a time-based backoff when
        prior failures exist — this is the API distinction between the two.
        """
        import time

        from custom_components.bluetooth_sig_devices.const import (
            CONFIRMED_DEVICE_PROBE_BACKOFF,
        )

        mock_hass = MagicMock()
        mock_task = MagicMock()

        def _capture_and_close(coro, *args, **kwargs):
            coro.close()
            return mock_task

        mock_hass.async_create_task.side_effect = _capture_and_close
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        service_info = _make_service_info(addr)

        # Exhaust failures with a recent attempt — within backoff window.
        gatt.probe_failures[addr] = gatt._max_probe_retries
        gatt._confirmed_probe_last_attempt[addr] = time.monotonic()

        # schedule_probe_for_confirmed_device is suppressed by backoff.
        gatt.schedule_probe_for_confirmed_device(service_info)
        mock_hass.async_create_task.assert_not_called()

        # After backoff expires, the probe is scheduled.
        gatt._confirmed_probe_last_attempt[addr] = (
            time.monotonic() - CONFIRMED_DEVICE_PROBE_BACKOFF - 1
        )
        gatt.schedule_probe_for_confirmed_device(service_info)
        mock_hass.async_create_task.assert_called_once()

    def test_remove_device_clears_confirmed_probe_state(self) -> None:
        """Test remove_device clears _confirmed_probe_last_attempt."""
        import time

        mock_hass = MagicMock()
        coord = _make_coordinator(mock_hass)
        gatt = coord.gatt_manager

        addr = "AA:BB:CC:DD:EE:FF"
        gatt._confirmed_probe_last_attempt[addr] = time.monotonic()
        gatt.probe_failures[addr] = 2

        gatt.remove_device(addr)

        assert addr not in gatt._confirmed_probe_last_attempt
        assert addr not in gatt.probe_failures
