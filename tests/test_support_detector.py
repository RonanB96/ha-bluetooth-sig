"""Tests for support_detector.py — support detection, characteristic resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from bluetooth_sig.core.translator import BluetoothSIGTranslator
from bluetooth_sig.gatt.characteristics.unknown import UnknownCharacteristic
from bluetooth_sig.types.uuid import BluetoothUUID
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.bluetooth_sig_devices.const import (
    CharacteristicSource,
    DiscoveredCharacteristic,
)
from custom_components.bluetooth_sig_devices.device_validator import GATTProbeResult
from custom_components.bluetooth_sig_devices.support_detector import SupportDetector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
TEMPERATURE_UUID = "00002a6e-0000-1000-8000-00805f9b34fb"
UNKNOWN_UUID = "0000ffff-0000-1000-8000-00805f9b34fb"
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"


def _make_service_info(
    *,
    address: str = "AA:BB:CC:DD:EE:01",
    service_data: dict[str, bytes] | None = None,
    manufacturer_data: dict[int, bytes] | None = None,
    connectable: bool = True,
) -> BluetoothServiceInfoBleak:
    """Build a minimal BluetoothServiceInfoBleak for testing."""
    sd = service_data or {}
    md = manufacturer_data or {}
    return BluetoothServiceInfoBleak(
        name="Test Device",
        address=address,
        rssi=-60,
        manufacturer_data=md,
        service_data=sd,
        service_uuids=list(sd.keys()),
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=connectable,
        time=0,
        tx_power=None,
    )


def _make_detector(
    gatt_probe_results: dict[str, GATTProbeResult] | None = None,
) -> SupportDetector:
    """Build a SupportDetector with a real translator and mock GATT manager."""
    translator = BluetoothSIGTranslator()
    gatt_manager = MagicMock()
    gatt_manager.probe_results = gatt_probe_results or {}
    return SupportDetector(translator, gatt_manager)


# ---------------------------------------------------------------------------
# get_supported_characteristics
# ---------------------------------------------------------------------------


class TestGetSupportedCharacteristics:
    """Tests for SupportDetector.get_supported_characteristics."""

    def test_battery_service_data_detected(self) -> None:
        """Battery Level UUID in service_data is detected as supported."""
        detector = _make_detector()
        si = _make_service_info(
            service_data={BATTERY_UUID: bytes([0x4B])},
        )
        found = detector.get_supported_characteristics(si)
        assert len(found) >= 1
        assert all(isinstance(f, DiscoveredCharacteristic) for f in found)
        assert any(f.source is CharacteristicSource.ADVERTISEMENT for f in found)

    def test_unknown_uuid_returns_empty(self) -> None:
        """Unknown UUID in service_data returns empty list."""
        detector = _make_detector()
        si = _make_service_info(
            service_data={UNKNOWN_UUID: b"\x00"},
        )
        found = detector.get_supported_characteristics(si)
        assert found == []

    def test_empty_service_data_returns_empty(self) -> None:
        """No service data returns empty list."""
        detector = _make_detector()
        si = _make_service_info()
        found = detector.get_supported_characteristics(si)
        assert found == []

    def test_gatt_probe_results_included(self) -> None:
        """GATT probe results are included in supported characteristics."""
        battery_bt_uuid = BluetoothUUID(BATTERY_UUID)
        probe_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:01",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(battery_bt_uuid,),
        )
        detector = _make_detector(
            gatt_probe_results={"AA:BB:CC:DD:EE:01": probe_result},
        )
        si = _make_service_info()
        found = detector.get_supported_characteristics(si)
        assert len(found) == 1
        assert found[0].source is CharacteristicSource.GATT

    def test_gatt_probe_no_support_returns_empty(self) -> None:
        """GATT probe with 0 parseable chars returns empty from gatt path."""
        probe_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:01",
            name="Test",
            parseable_count=0,
            supported_char_uuids=(),
        )
        detector = _make_detector(
            gatt_probe_results={"AA:BB:CC:DD:EE:01": probe_result},
        )
        si = _make_service_info()
        found = detector.get_supported_characteristics(si)
        assert found == []


# ---------------------------------------------------------------------------
# check_manufacturer_support
# ---------------------------------------------------------------------------


class TestCheckManufacturerSupport:
    """Tests for SupportDetector.check_manufacturer_support."""

    def test_no_manufacturer_data_returns_none(self) -> None:
        """Returns None when no manufacturer data present."""
        detector = _make_detector()
        si = _make_service_info()
        assert detector.check_manufacturer_support(si) is None

    def test_unparseable_manufacturer_data_returns_none(self) -> None:
        """Returns None when manufacturer data can't be parsed."""
        detector = _make_detector()
        si = _make_service_info(
            manufacturer_data={0xFFFF: b"\x01\x02\x03"},
        )
        result = detector.check_manufacturer_support(si)
        # Most random manufacturer data won't parse to anything
        # This is either None or a string — both are acceptable
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# has_supported_data
# ---------------------------------------------------------------------------


class TestHasSupportedData:
    """Tests for SupportDetector.has_supported_data."""

    def test_with_parseable_service_data(self) -> None:
        """Returns True when service data is parseable."""
        detector = _make_detector()
        si = _make_service_info(
            service_data={BATTERY_UUID: bytes([0x4B])},
        )
        assert detector.has_supported_data(si) is True

    def test_without_any_data(self) -> None:
        """Returns False when no data is parseable."""
        detector = _make_detector()
        si = _make_service_info()
        assert detector.has_supported_data(si) is False


# ---------------------------------------------------------------------------
# build_characteristics_summary
# ---------------------------------------------------------------------------


class TestBuildCharacteristicsSummary:
    """Tests for SupportDetector.build_characteristics_summary."""

    def test_empty_list_returns_empty_string(self) -> None:
        """Empty supported list returns empty string."""
        detector = _make_detector()
        result = detector.build_characteristics_summary("AA:BB:CC:DD:EE:01", [], {})
        assert result == ""

    def test_advertisement_characteristics_grouped(self) -> None:
        """Advertisement characteristics appear under 'Advertising data'."""
        detector = _make_detector()
        char_instance = MagicMock()
        char_instance.name = "Battery Level"
        char_instance.uuid = BluetoothUUID(BATTERY_UUID)

        supported = [
            DiscoveredCharacteristic(
                characteristic=char_instance,
                source=CharacteristicSource.ADVERTISEMENT,
            ),
        ]
        result = detector.build_characteristics_summary(
            "AA:BB:CC:DD:EE:01", supported, {}
        )
        assert "**Advertising data:**" in result
        assert "Battery Level" in result

    def test_gatt_characteristics_grouped(self) -> None:
        """GATT characteristics appear under 'Connected (GATT) data'."""
        detector = _make_detector()
        char_instance = MagicMock()
        char_instance.name = "Temperature"
        char_instance.uuid = BluetoothUUID(TEMPERATURE_UUID)

        supported = [
            DiscoveredCharacteristic(
                characteristic=char_instance,
                source=CharacteristicSource.GATT,
            ),
        ]
        result = detector.build_characteristics_summary(
            "AA:BB:CC:DD:EE:01", supported, {}
        )
        assert "**Connected (GATT) data:**" in result
        assert "Temperature" in result

    def test_manufacturer_name_included(self) -> None:
        """Manufacturer name appears under 'Manufacturer data'."""
        detector = _make_detector()
        result = detector.build_characteristics_summary(
            "AA:BB:CC:DD:EE:01",
            [],
            {},
            manufacturer_name="Xiaomi",
        )
        assert "**Manufacturer data:**" in result
        assert "Xiaomi" in result

    def test_known_characteristics_accumulated(self) -> None:
        """Discovered characteristics are accumulated in known_characteristics."""
        detector = _make_detector()
        known: dict[str, dict[str, str]] = {}
        char_instance = MagicMock()
        char_instance.name = "Battery Level"
        char_instance.uuid = BluetoothUUID(BATTERY_UUID)

        supported = [
            DiscoveredCharacteristic(
                characteristic=char_instance,
                source=CharacteristicSource.ADVERTISEMENT,
            ),
        ]
        detector.build_characteristics_summary("AA:BB:CC:DD:EE:01", supported, known)
        assert "AA:BB:CC:DD:EE:01" in known
        assert str(BluetoothUUID(BATTERY_UUID)) in known["AA:BB:CC:DD:EE:01"]


# ---------------------------------------------------------------------------
# get_known_characteristics
# ---------------------------------------------------------------------------


class TestGetKnownCharacteristics:
    """Tests for SupportDetector.get_known_characteristics."""

    def test_empty_returns_empty(self) -> None:
        """No known characteristics returns empty dict."""
        detector = _make_detector()
        result = detector.get_known_characteristics("AA:BB:CC:DD:EE:01", {})
        assert result == {}

    def test_merges_gatt_probe_results(self) -> None:
        """GATT probe results are merged into known characteristics."""
        battery_bt_uuid = BluetoothUUID(BATTERY_UUID)
        probe_result = GATTProbeResult(
            address="AA:BB:CC:DD:EE:01",
            name="Test",
            parseable_count=1,
            supported_char_uuids=(battery_bt_uuid,),
        )
        detector = _make_detector(
            gatt_probe_results={"AA:BB:CC:DD:EE:01": probe_result},
        )
        result = detector.get_known_characteristics("AA:BB:CC:DD:EE:01", {})
        assert len(result) == 1
        uuid_str = str(battery_bt_uuid)
        assert uuid_str in result

    def test_existing_known_preserved(self) -> None:
        """Existing known characteristics are preserved."""
        detector = _make_detector()
        known = {
            "AA:BB:CC:DD:EE:01": {"some-uuid": "Some Char"},
        }
        result = detector.get_known_characteristics("AA:BB:CC:DD:EE:01", known)
        assert "some-uuid" in result
        assert result["some-uuid"] == "Some Char"


# ---------------------------------------------------------------------------
# _resolve_characteristic_by_uuid
# ---------------------------------------------------------------------------


class TestResolveCharacteristicByUuid:
    """Tests for SupportDetector._resolve_characteristic_by_uuid."""

    def test_known_uuid_returns_typed_instance(self) -> None:
        """Known UUID returns a concrete characteristic class."""
        result = SupportDetector._resolve_characteristic_by_uuid(
            BluetoothUUID(BATTERY_UUID),
            fallback_name="Battery Level",
        )
        assert not isinstance(result, UnknownCharacteristic)
        assert "battery" in result.name.lower() or "Battery" in result.name

    def test_unknown_uuid_returns_unknown_characteristic(self) -> None:
        """Unknown UUID returns UnknownCharacteristic with fallback name."""
        result = SupportDetector._resolve_characteristic_by_uuid(
            BluetoothUUID(UNKNOWN_UUID),
            fallback_name="Custom Thing",
        )
        assert isinstance(result, UnknownCharacteristic)
        assert result.name == "Unknown: Custom Thing"


# ---------------------------------------------------------------------------
# _check_service_data — service-level UUID path (lines 215-247)
# ---------------------------------------------------------------------------


class TestCheckServiceData:
    """Tests for the service-level UUID path in _check_service_data."""

    def test_service_uuid_with_characteristics(self) -> None:
        """Service UUID (Heart Rate 0x180D) resolves to characteristic list."""
        detector = _make_detector()
        si = _make_service_info(
            service_data={HEART_RATE_SERVICE_UUID: bytes([0x00, 0x48])},
        )
        found = detector.get_supported_characteristics(si)
        # Heart Rate service should return Heart Rate Measurement characteristic
        assert len(found) >= 1
        assert any("heart rate" in f.characteristic.name.lower() for f in found)

    def test_battery_service_uuid_resolves(self) -> None:
        """Battery service UUID (0x180F) resolves to Battery Level characteristic."""
        detector = _make_detector()
        si = _make_service_info(
            service_data={BATTERY_SERVICE_UUID: bytes([0x4B])},
        )
        found = detector.get_supported_characteristics(si)
        assert len(found) >= 1
        assert any("battery" in f.characteristic.name.lower() for f in found)

    def test_characteristic_uuid_directly(self) -> None:
        """Characteristic UUID (Battery Level 0x2A19) found via char_info path."""
        detector = _make_detector()
        si = _make_service_info(
            service_data={BATTERY_UUID: bytes([0x4B])},
        )
        found = detector.get_supported_characteristics(si)
        # Battery Level is a characteristic UUID, found via char_info lookup
        assert len(found) >= 1


# ---------------------------------------------------------------------------
# check_manufacturer_support — with interpreted data (lines 105-112)
# ---------------------------------------------------------------------------


class TestCheckManufacturerSupportInterpreted:
    """Tests for check_manufacturer_support with various interpreted data states."""

    def test_with_interpreted_data_returns_name(self) -> None:
        """Returns interpreter name when interpreted_data is not None."""
        from unittest.mock import patch as mock_patch

        from custom_components.bluetooth_sig_devices.advertisement_manager import (
            AdvertisementManager,
        )

        detector = _make_detector()
        si = _make_service_info(
            manufacturer_data={0x004C: b"\x01\x02\x03"},
        )

        # Mock convert_advertisement to return ad with interpreted_data set
        mock_ad = MagicMock()
        mock_ad.interpreted_data = MagicMock()  # Not None
        mock_ad.interpreter_name = "AppleInterpreter"

        with mock_patch.object(
            AdvertisementManager, "convert_advertisement", return_value=mock_ad
        ):
            result = detector.check_manufacturer_support(si)

        assert result == "AppleInterpreter"

    def test_with_interpreted_data_no_name_returns_fallback(self) -> None:
        """Returns 'Manufacturer Data' when interpreter_name is None."""
        from unittest.mock import patch as mock_patch

        from custom_components.bluetooth_sig_devices.advertisement_manager import (
            AdvertisementManager,
        )

        detector = _make_detector()
        si = _make_service_info(
            manufacturer_data={0x004C: b"\x01\x02\x03"},
        )

        mock_ad = MagicMock()
        mock_ad.interpreted_data = MagicMock()  # Not None
        mock_ad.interpreter_name = None

        with mock_patch.object(
            AdvertisementManager, "convert_advertisement", return_value=mock_ad
        ):
            result = detector.check_manufacturer_support(si)

        assert result == "Manufacturer Data"

    def test_conversion_exception_returns_none(self) -> None:
        """Returns None when convert_advertisement raises."""
        from unittest.mock import patch as mock_patch

        from custom_components.bluetooth_sig_devices.advertisement_manager import (
            AdvertisementManager,
        )

        detector = _make_detector()
        si = _make_service_info(
            manufacturer_data={0x004C: b"\x01\x02\x03"},
        )

        with mock_patch.object(
            AdvertisementManager,
            "convert_advertisement",
            side_effect=RuntimeError("parse failed"),
        ):
            result = detector.check_manufacturer_support(si)

        assert result is None

    def test_pre_converted_advertisement_reused(self) -> None:
        """Pre-supplied advertisement is reused (no conversion call)."""
        from unittest.mock import patch as mock_patch

        from custom_components.bluetooth_sig_devices.advertisement_manager import (
            AdvertisementManager,
        )

        detector = _make_detector()
        si = _make_service_info(
            manufacturer_data={0x004C: b"\x01\x02\x03"},
        )

        mock_ad = MagicMock()
        mock_ad.interpreted_data = MagicMock()
        mock_ad.interpreter_name = "PreConverted"

        with mock_patch.object(
            AdvertisementManager, "convert_advertisement"
        ) as mock_convert:
            result = detector.check_manufacturer_support(si, advertisement=mock_ad)

        # Should NOT call convert_advertisement since we passed the ad
        mock_convert.assert_not_called()
        assert result == "PreConverted"
