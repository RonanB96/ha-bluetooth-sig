"""Tests for device_validator.py — probe results, track/probe decisions, and address classification."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.bluetooth_sig_devices.const import BLEAddressType
from custom_components.bluetooth_sig_devices.device_validator import (
    GATTProbeResult,
    _classify_random_address,
    classify_ble_address,
    is_static_address,
)


def _make_service_info(
    address: str,
    *,
    address_type: str | None = None,
    esphome_address_type: int | None = None,
) -> BluetoothServiceInfoBleak:
    """Build a minimal BluetoothServiceInfoBleak with configurable address type.

    Args:
        address: BLE MAC address string.
        address_type: BlueZ-style address type ("public", "random", or None).
        esphome_address_type: ESPHome proxy-style integer (0=public, 1=random).

    """
    device = MagicMock()
    if address_type is not None:
        device.details = {"props": {"AddressType": address_type}}
    elif esphome_address_type is not None:
        # ESPHome proxy format: {"source": "...", "address_type": 0|1}
        device.details = {"source": "esp32-proxy", "address_type": esphome_address_type}
    else:
        # No metadata (test mock)
        device.details = {}
    return BluetoothServiceInfoBleak(
        name="Test",
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=device,
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=None,
    )


class TestGATTProbeResult:
    """Test cases for GATTProbeResult dataclass."""

    def test_gatt_probe_result_has_support(self) -> None:
        """Test GATTProbeResult.has_support method."""
        # No parseable characteristics
        result_empty = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
            parseable_count=0,
        )
        assert result_empty.has_support() is False

        # Has parseable characteristics
        result_with_chars = GATTProbeResult(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Device",
            parseable_count=3,
        )
        assert result_with_chars.has_support() is True


class TestClassifyBLEAddress:
    """Test classify_ble_address with different address types and BlueZ metadata."""

    def test_public_address(self) -> None:
        """BlueZ reports public → PUBLIC."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF", address_type="public")
        assert classify_ble_address(si) == BLEAddressType.PUBLIC

    def test_random_static_address(self) -> None:
        """BlueZ reports random, MSB 0xC0-0xFF → RANDOM_STATIC."""
        # 0xC0 = 11000000 → top bits = 11
        si = _make_service_info("C0:11:22:33:44:55", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.RANDOM_STATIC

    def test_random_static_high_byte(self) -> None:
        """BlueZ reports random, MSB 0xFF → RANDOM_STATIC."""
        si = _make_service_info("FF:AA:BB:CC:DD:EE", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.RANDOM_STATIC

    def test_resolvable_private_address(self) -> None:
        """BlueZ reports random, MSB 0x40-0x7F → RESOLVABLE_PRIVATE."""
        # 0x5A = 01011010 → top bits = 01
        si = _make_service_info("5A:BB:CC:DD:EE:FF", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.RESOLVABLE_PRIVATE

    def test_resolvable_private_boundary_low(self) -> None:
        """BlueZ reports random, MSB 0x40 → RESOLVABLE_PRIVATE."""
        si = _make_service_info("40:00:00:00:00:00", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.RESOLVABLE_PRIVATE

    def test_resolvable_private_boundary_high(self) -> None:
        """BlueZ reports random, MSB 0x7F → RESOLVABLE_PRIVATE."""
        si = _make_service_info("7F:FF:FF:FF:FF:FF", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.RESOLVABLE_PRIVATE

    def test_non_resolvable_private_address(self) -> None:
        """BlueZ reports random, MSB 0x00-0x3F → NON_RESOLVABLE_PRIVATE."""
        # 0x1A = 00011010 → top bits = 00
        si = _make_service_info("1A:BB:CC:DD:EE:FF", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.NON_RESOLVABLE_PRIVATE

    def test_non_resolvable_private_zero(self) -> None:
        """BlueZ reports random, MSB 0x00 → NON_RESOLVABLE_PRIVATE."""
        si = _make_service_info("00:11:22:33:44:55", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.NON_RESOLVABLE_PRIVATE

    def test_reserved_random_address(self) -> None:
        """BlueZ reports random, MSB 0x80-0xBF (reserved) → UNKNOWN."""
        # 0x80 = 10000000 → top bits = 10 (reserved)
        si = _make_service_info("80:AA:BB:CC:DD:EE", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.UNKNOWN

    def test_no_bluez_metadata_returns_unknown(self) -> None:
        """No AddressType in device.details → UNKNOWN (assumed stable)."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF", address_type=None)
        assert classify_ble_address(si) == BLEAddressType.UNKNOWN

    def test_empty_details_dict(self) -> None:
        """Empty details dict → UNKNOWN."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF")
        si.device.details = {}
        assert classify_ble_address(si) == BLEAddressType.UNKNOWN

    def test_mock_device_no_details(self) -> None:
        """MagicMock device without explicit details → UNKNOWN."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF")
        # Reset to plain MagicMock (details is a MagicMock, not dict)
        si.device = MagicMock(spec=[])
        assert classify_ble_address(si) == BLEAddressType.UNKNOWN

    def test_malformed_address_returns_unknown(self) -> None:
        """Non-standard MAC format falls back to UNKNOWN."""
        si = _make_service_info("not-a-mac", address_type="random")
        assert classify_ble_address(si) == BLEAddressType.UNKNOWN


class TestIsStaticAddress:
    """Test is_static_address helper."""

    def test_public_is_static(self) -> None:
        """Public address is static."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF", address_type="public")
        assert is_static_address(si) is True

    def test_random_static_is_static(self) -> None:
        """Random Static address is static."""
        si = _make_service_info("C0:11:22:33:44:55", address_type="random")
        assert is_static_address(si) is True

    def test_unknown_is_static(self) -> None:
        """Unknown (no BlueZ metadata) is treated as static."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF", address_type=None)
        assert is_static_address(si) is True

    def test_resolvable_private_is_not_static(self) -> None:
        """RPA is NOT static."""
        si = _make_service_info("5A:BB:CC:DD:EE:FF", address_type="random")
        assert is_static_address(si) is False

    def test_non_resolvable_private_is_not_static(self) -> None:
        """NRPA is NOT static."""
        si = _make_service_info("1A:BB:CC:DD:EE:FF", address_type="random")
        assert is_static_address(si) is False


class TestClassifyRandomAddress:
    """Test _classify_random_address helper directly."""

    def test_random_static(self) -> None:
        """0xC0–0xFF → RANDOM_STATIC."""
        assert _classify_random_address("C0:11:22:33:44:55") == BLEAddressType.RANDOM_STATIC
        assert _classify_random_address("FF:AA:BB:CC:DD:EE") == BLEAddressType.RANDOM_STATIC

    def test_resolvable_private(self) -> None:
        """0x40–0x7F → RESOLVABLE_PRIVATE."""
        assert _classify_random_address("40:00:00:00:00:00") == BLEAddressType.RESOLVABLE_PRIVATE
        assert _classify_random_address("7F:FF:FF:FF:FF:FF") == BLEAddressType.RESOLVABLE_PRIVATE

    def test_non_resolvable_private(self) -> None:
        """0x00–0x3F → NON_RESOLVABLE_PRIVATE."""
        assert _classify_random_address("00:11:22:33:44:55") == BLEAddressType.NON_RESOLVABLE_PRIVATE
        assert _classify_random_address("3F:AA:BB:CC:DD:EE") == BLEAddressType.NON_RESOLVABLE_PRIVATE

    def test_reserved(self) -> None:
        """0x80–0xBF (reserved) → UNKNOWN."""
        assert _classify_random_address("80:AA:BB:CC:DD:EE") == BLEAddressType.UNKNOWN

    def test_malformed(self) -> None:
        """Malformed MAC → UNKNOWN."""
        assert _classify_random_address("not-a-mac") == BLEAddressType.UNKNOWN


class TestESPHomeProxyAddressType:
    """Test classify_ble_address with ESPHome proxy address_type format.

    ESPHome proxies (via bleak-esphome) pass ``{"address_type": 0|1}``
    in ``BLEDevice.details`` instead of the BlueZ format
    ``{"props": {"AddressType": "random"|"public"}}``.
    """

    def test_esphome_public_address(self) -> None:
        """ESPHome reports address_type=0 → PUBLIC."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF", esphome_address_type=0)
        assert classify_ble_address(si) == BLEAddressType.PUBLIC

    def test_esphome_random_static(self) -> None:
        """ESPHome reports random (1), MSB 0xC0 → RANDOM_STATIC."""
        si = _make_service_info("C0:11:22:33:44:55", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.RANDOM_STATIC

    def test_esphome_random_static_high(self) -> None:
        """ESPHome reports random (1), MSB 0xFF → RANDOM_STATIC."""
        si = _make_service_info("FF:AA:BB:CC:DD:EE", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.RANDOM_STATIC

    def test_esphome_rpa(self) -> None:
        """ESPHome reports random (1), MSB 0x40–0x7F → RESOLVABLE_PRIVATE."""
        si = _make_service_info("5A:BB:CC:DD:EE:FF", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.RESOLVABLE_PRIVATE

    def test_esphome_rpa_boundary_low(self) -> None:
        """ESPHome reports random (1), MSB 0x40 → RESOLVABLE_PRIVATE."""
        si = _make_service_info("40:00:00:00:00:00", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.RESOLVABLE_PRIVATE

    def test_esphome_rpa_boundary_high(self) -> None:
        """ESPHome reports random (1), MSB 0x7F → RESOLVABLE_PRIVATE."""
        si = _make_service_info("7F:FF:FF:FF:FF:FF", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.RESOLVABLE_PRIVATE

    def test_esphome_nrpa(self) -> None:
        """ESPHome reports random (1), MSB 0x00–0x3F → NON_RESOLVABLE_PRIVATE."""
        si = _make_service_info("1A:BB:CC:DD:EE:FF", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.NON_RESOLVABLE_PRIVATE

    def test_esphome_nrpa_zero(self) -> None:
        """ESPHome reports random (1), MSB 0x00 → NON_RESOLVABLE_PRIVATE."""
        si = _make_service_info("00:11:22:33:44:55", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.NON_RESOLVABLE_PRIVATE

    def test_esphome_reserved_random(self) -> None:
        """ESPHome reports random (1), MSB 0x80–0xBF → UNKNOWN."""
        si = _make_service_info("80:AA:BB:CC:DD:EE", esphome_address_type=1)
        assert classify_ble_address(si) == BLEAddressType.UNKNOWN

    def test_esphome_rpa_is_not_static(self) -> None:
        """ESPHome RPA should NOT pass is_static_address."""
        si = _make_service_info("5A:BB:CC:DD:EE:FF", esphome_address_type=1)
        assert is_static_address(si) is False

    def test_esphome_nrpa_is_not_static(self) -> None:
        """ESPHome NRPA should NOT pass is_static_address."""
        si = _make_service_info("1A:BB:CC:DD:EE:FF", esphome_address_type=1)
        assert is_static_address(si) is False

    def test_esphome_public_is_static(self) -> None:
        """ESPHome public address IS static."""
        si = _make_service_info("AA:BB:CC:DD:EE:FF", esphome_address_type=0)
        assert is_static_address(si) is True

    def test_esphome_random_static_is_static(self) -> None:
        """ESPHome random-static address IS static."""
        si = _make_service_info("C0:11:22:33:44:55", esphome_address_type=1)
        assert is_static_address(si) is True

    def test_esphome_real_log_addresses_filtered(self) -> None:
        """Addresses from the real HA logs that were incorrectly passing.

        These addresses appeared as spurious discovery flows because
        ESPHome proxy address_type was not being checked.
        """
        # From actual HA logs — all are RPA or NRPA rotating addresses
        rpa_addresses = [
            "4B:2C:F7:49:08:BC",  # 0x4B → RPA
            "66:47:53:29:F3:70",  # 0x66 → RPA
            "69:7E:B4:FA:A1:71",  # 0x69 → RPA
            "5B:4D:DB:96:C6:AA",  # 0x5B → RPA
            "65:2A:BD:8F:22:BD",  # 0x65 → RPA
        ]
        nrpa_addresses = [
            "31:30:29:18:F8:FD",  # 0x31 → NRPA
            "0D:8F:46:F2:CA:CF",  # 0x0D → NRPA
            "3F:D5:2B:67:18:5D",  # 0x3F → NRPA
            "13:01:4F:32:A4:FD",  # 0x13 → NRPA
            "0A:0E:D1:27:BF:60",  # 0x0A → NRPA
            "2A:15:F5:A8:9B:83",  # 0x2A → NRPA
            "03:41:DF:E0:8E:B3",  # 0x03 → NRPA
            "05:62:1B:F2:3A:F1",  # 0x05 → NRPA
            "00:29:09:CA:12:3C",  # 0x00 → NRPA
        ]
        for addr in rpa_addresses + nrpa_addresses:
            si = _make_service_info(addr, esphome_address_type=1)
            assert is_static_address(si) is False, (
                f"Address {addr} should be filtered as ephemeral"
            )
