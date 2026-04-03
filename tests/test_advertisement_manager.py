"""Tests for advertisement_manager.py — instance methods, static helpers, RSSI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bluetooth_sig.types.advertising import (
    AdvertisementData,
    AdvertisingDataStructures,
    BLEAdvertisingFlags,
    CoreAdvertisingData,
    DeviceProperties,
    DirectedAdvertisingData,
    LocationAndSensingData,
    MeshAndBroadcastData,
    OOBSecurityData,
    SecurityData,
)
from bluetooth_sig.types.company import ManufacturerData

from custom_components.bluetooth_sig_devices.advertisement_converter import (
    get_manufacturer_name,
    get_model_name,
)
from custom_components.bluetooth_sig_devices.advertisement_manager import (
    AdvertisementManager,
)

# ---------------------------------------------------------------------------
# Helpers — build minimal AdvertisementData for testing
# ---------------------------------------------------------------------------


def _make_ad_structures(
    *,
    local_name: str = "",
    manufacturer_data: dict[int, ManufacturerData] | None = None,
    flags: BLEAdvertisingFlags | None = None,
) -> AdvertisingDataStructures:
    """Build a minimal AdvertisingDataStructures for testing."""
    if flags is None:
        flags = BLEAdvertisingFlags(0)
    return AdvertisingDataStructures(
        core=CoreAdvertisingData(
            manufacturer_data=manufacturer_data or {},
            service_data={},
            service_uuids=[],
            solicited_service_uuids=[],
            local_name=local_name,
            uri_data=None,
        ),
        properties=DeviceProperties(
            flags=flags,
            appearance=None,
            tx_power=0,
            le_role=None,
            le_supported_features=None,
            class_of_device=None,
        ),
        directed=DirectedAdvertisingData(
            public_target_address=[],
            random_target_address=[],
            le_bluetooth_device_address="AA:BB:CC:DD:EE:FF",
            advertising_interval=None,
            advertising_interval_long=None,
            peripheral_connection_interval_range=None,
        ),
        oob_security=OOBSecurityData(
            simple_pairing_hash_c=b"",
            simple_pairing_randomizer_r=b"",
            secure_connections_confirmation=b"",
            secure_connections_random=b"",
            security_manager_tk_value=b"",
            security_manager_oob_flags=b"",
        ),
        location=LocationAndSensingData(
            indoor_positioning=None,
            three_d_information=None,
            transport_discovery_data=None,
            channel_map_update_indication=None,
        ),
        mesh=MeshAndBroadcastData(
            mesh_message=None,
            secure_network_beacon=None,
            unprovisioned_device_beacon=None,
            provisioning_bearer=None,
            broadcast_name="",
            broadcast_code=b"",
            biginfo=b"",
            periodic_advertising_response_timing=b"",
            electronic_shelf_label=b"",
        ),
        security=SecurityData(
            encrypted_advertising_data=b"",
            resolvable_set_identifier=b"",
        ),
    )


def _make_advertisement(
    *,
    rssi: int = -60,
    local_name: str = "",
    manufacturer_data: dict[int, ManufacturerData] | None = None,
    interpreted_data: object | None = None,
    interpreter_name: str | None = None,
    flags: BLEAdvertisingFlags | None = None,
) -> AdvertisementData:
    """Build a minimal AdvertisementData for testing."""
    return AdvertisementData(
        ad_structures=_make_ad_structures(
            local_name=local_name,
            manufacturer_data=manufacturer_data,
            flags=flags,
        ),
        interpreted_data=interpreted_data,
        interpreter_name=interpreter_name,
        rssi=rssi,
    )


# ---------------------------------------------------------------------------
# Instance lifecycle tests
# ---------------------------------------------------------------------------


class TestAdvertisementManagerInstance:
    """Tests for AdvertisementManager instance methods."""

    def test_init_defaults(self) -> None:
        """Test default state after construction."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        assert mgr._address == "AA:BB:CC:DD:EE:FF"
        assert mgr._hass is None
        assert mgr._latest_advertisement is None
        assert mgr._advertisement_callbacks == []

    def test_connectable_no_advertisement(self) -> None:
        """Connectable returns False when no advertisement received."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        assert mgr.connectable is False

    def test_connectable_with_discoverable_flag(self) -> None:
        """Connectable returns True when LE_GENERAL_DISCOVERABLE_MODE is set."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        ad = _make_advertisement(
            flags=BLEAdvertisingFlags.LE_GENERAL_DISCOVERABLE_MODE,
        )
        mgr.on_advertisement_received(ad)
        assert mgr.connectable is True

    def test_connectable_without_discoverable_flag(self) -> None:
        """Connectable returns False when only BR_EDR_NOT_SUPPORTED is set."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        ad = _make_advertisement(
            flags=BLEAdvertisingFlags.BR_EDR_NOT_SUPPORTED,
        )
        mgr.on_advertisement_received(ad)
        assert mgr.connectable is False

    def test_set_hass(self) -> None:
        """set_hass stores the HA instance."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mock_hass = MagicMock()
        mgr.set_hass(mock_hass)
        assert mgr._hass is mock_hass

    def test_set_disconnected_callback(self) -> None:
        """set_disconnected_callback stores the callback."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        cb = MagicMock()
        mgr.set_disconnected_callback(cb)
        assert mgr._disconnected_callback is cb

    def test_fire_disconnected_with_callback(self) -> None:
        """fire_disconnected invokes the registered callback."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        cb = MagicMock()
        mgr.set_disconnected_callback(cb)
        mgr.fire_disconnected()
        cb.assert_called_once()

    def test_fire_disconnected_without_callback(self) -> None:
        """fire_disconnected is a no-op when no callback is registered."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mgr.fire_disconnected()  # Should not raise

    def test_on_advertisement_received_stores_ad(self) -> None:
        """on_advertisement_received stores the advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        ad = _make_advertisement(rssi=-70)
        mgr.on_advertisement_received(ad)
        assert mgr._latest_advertisement is ad

    def test_on_advertisement_received_fires_callbacks(self) -> None:
        """on_advertisement_received fires all registered callbacks."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        cb1 = MagicMock()
        cb2 = MagicMock()
        mgr.register_advertisement_callback(cb1)
        mgr.register_advertisement_callback(cb2)
        ad = _make_advertisement(rssi=-65)
        mgr.on_advertisement_received(ad)
        cb1.assert_called_once_with(ad)
        cb2.assert_called_once_with(ad)

    def test_register_and_unregister_callback(self) -> None:
        """register/unregister maintains the callback list."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        cb = MagicMock()
        mgr.register_advertisement_callback(cb)
        assert cb in mgr._advertisement_callbacks
        mgr.unregister_advertisement_callback(cb)
        assert cb not in mgr._advertisement_callbacks

    def test_unregister_nonexistent_callback(self) -> None:
        """Unregistering a callback not in the list is a no-op."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mgr.unregister_advertisement_callback(MagicMock())  # Should not raise


# ---------------------------------------------------------------------------
# RSSI tests
# ---------------------------------------------------------------------------


class TestRSSIMethods:
    """Tests for RSSI-related methods."""

    def test_get_cached_rssi_none_when_no_ad(self) -> None:
        """_get_cached_rssi returns None when no advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        assert mgr._get_cached_rssi() is None

    def test_get_cached_rssi_returns_value(self) -> None:
        """_get_cached_rssi returns the RSSI from the latest advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mgr.on_advertisement_received(_make_advertisement(rssi=-72))
        assert mgr._get_cached_rssi() == -72

    @pytest.mark.asyncio
    async def test_get_advertisement_rssi_no_refresh(self) -> None:
        """get_advertisement_rssi returns cached RSSI without refresh."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mgr.on_advertisement_received(_make_advertisement(rssi=-55))
        result = await mgr.get_advertisement_rssi(refresh=False)
        assert result == -55

    @pytest.mark.asyncio
    async def test_get_advertisement_rssi_with_refresh(self) -> None:
        """get_advertisement_rssi with refresh delegates to get_latest_advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mgr.on_advertisement_received(_make_advertisement(rssi=-55))
        # Without hass, refresh is a no-op
        result = await mgr.get_advertisement_rssi(refresh=True)
        assert result == -55

    @pytest.mark.asyncio
    async def test_get_advertisement_rssi_none_without_ad(self) -> None:
        """get_advertisement_rssi returns None when no advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        result = await mgr.get_advertisement_rssi()
        assert result is None

    def test_read_rssi_sync_returns_value(self) -> None:
        """read_rssi_sync returns the cached RSSI."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mgr.on_advertisement_received(_make_advertisement(rssi=-68))
        assert mgr.read_rssi_sync() == -68

    def test_read_rssi_sync_raises_when_no_ad(self) -> None:
        """read_rssi_sync raises ValueError when no advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        with pytest.raises(ValueError, match="No RSSI available"):
            mgr.read_rssi_sync()


# ---------------------------------------------------------------------------
# get_latest_advertisement tests
# ---------------------------------------------------------------------------


class TestGetLatestAdvertisement:
    """Tests for get_latest_advertisement."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_ad(self) -> None:
        """Returns None when no advertisement has been received."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        assert await mgr.get_latest_advertisement() is None

    @pytest.mark.asyncio
    async def test_returns_cached_ad(self) -> None:
        """Returns the last received advertisement."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        ad = _make_advertisement(rssi=-60)
        mgr.on_advertisement_received(ad)
        result = await mgr.get_latest_advertisement()
        assert result is ad

    @pytest.mark.asyncio
    async def test_refresh_with_hass(self) -> None:
        """Refresh fetches from HA Bluetooth when hass is set."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        mock_hass = MagicMock()
        mgr.set_hass(mock_hass)

        mock_service_info = MagicMock()
        mock_service_info.address = "AA:BB:CC:DD:EE:FF"
        mock_service_info.rssi = -50
        mock_service_info.manufacturer_data = {}
        mock_service_info.service_data = {
            "00002a19-0000-1000-8000-00805f9b34fb": bytes([0x4B]),
        }
        mock_service_info.service_uuids = [
            "00002a19-0000-1000-8000-00805f9b34fb",
        ]
        mock_service_info.connectable = True
        mock_service_info.time = 0
        mock_service_info.name = "Test"
        mock_service_info.tx_power = None
        mock_service_info.device = MagicMock()
        mock_service_info.device.details = {}
        mock_service_info.raw = None

        with patch(
            "custom_components.bluetooth_sig_devices.advertisement_manager.bluetooth.async_last_service_info",
            return_value=mock_service_info,
        ):
            result = await mgr.get_latest_advertisement(refresh=True)

        assert result is not None
        assert result.rssi == -50

    @pytest.mark.asyncio
    async def test_refresh_no_hass_is_noop(self) -> None:
        """Refresh without hass does not attempt to fetch."""
        mgr = AdvertisementManager("AA:BB:CC:DD:EE:FF")
        result = await mgr.get_latest_advertisement(refresh=True)
        assert result is None


# ---------------------------------------------------------------------------
# Static helper tests
# ---------------------------------------------------------------------------


class TestGetManufacturerName:
    """Tests for get_manufacturer_name."""

    def test_returns_company_name(self) -> None:
        """Returns the company name from manufacturer data."""
        mfr = ManufacturerData.from_id_and_payload(0x004C, b"\x01\x02")
        ad = _make_advertisement(manufacturer_data={0x004C: mfr})
        name = get_manufacturer_name(ad)
        assert name is not None
        assert not name.startswith("Unknown")

    def test_returns_interpreter_name_when_no_mfr_data(self) -> None:
        """Falls back to interpreter_name when no manufacturer data."""
        ad = _make_advertisement(interpreter_name="TestInterpreter")
        name = get_manufacturer_name(ad)
        assert name == "TestInterpreter"

    def test_returns_none_when_nothing(self) -> None:
        """Returns None when no manufacturer data or interpreter."""
        ad = _make_advertisement()
        name = get_manufacturer_name(ad)
        assert name is None

    def test_skips_unknown_company_name(self) -> None:
        """Skips manufacturer entries with 'Unknown' company name."""
        mfr = MagicMock()
        mfr.company = MagicMock()
        mfr.company.name = "Unknown Company"
        ad = _make_advertisement(manufacturer_data={0xFFFF: mfr})
        name = get_manufacturer_name(ad)
        assert name is None


class TestGetModelName:
    """Tests for get_model_name."""

    def test_returns_local_name(self) -> None:
        """Returns local_name from advertisement."""
        ad = _make_advertisement(local_name="Test Device")
        name = get_model_name(ad)
        assert name == "Test Device"

    def test_returns_none_when_no_name(self) -> None:
        """Returns None when no local_name."""
        ad = _make_advertisement(local_name="")
        name = get_model_name(ad)
        assert name is None
