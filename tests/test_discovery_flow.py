"""Tests for the standard HA discovery flow and entity gating.

These tests prove that:
1. The hub coordinator fires ``discovery_flow.async_create_flow`` for new
   devices instead of creating entities directly.
2. Entities are NEVER created without the user explicitly confirming the
   device through the integration-discovery config flow.
3. After user confirmation, create_device_processor creates a processor.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.bluetooth_sig_devices.const import (
    DOMAIN,
)

from .conftest import (
    DEVICE_ADDRESS,
    DEVICE_NAME,
    make_device_entry,
    make_hub_entry,
    make_service_info,
)

# ===================================================================
# 1. Config-flow: integration_discovery step
# ===================================================================


class TestIntegrationDiscoveryFlow:
    """Test the integration_discovery config-flow steps."""

    async def test_discovery_shows_confirmation_form(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """A discovered device shows a confirmation form before creating an entry."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"address": DEVICE_ADDRESS, "name": DEVICE_NAME},
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "integration_discovery_confirm"

    async def test_discovery_shows_characteristics_in_form(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """The discovery confirmation form includes detected characteristics."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={
                "address": DEVICE_ADDRESS,
                "name": DEVICE_NAME,
                "characteristics": "Battery Level, Temperature",
            },
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "integration_discovery_confirm"
        placeholders = result["description_placeholders"]
        assert placeholders["characteristics"] == "Battery Level, Temperature"

    async def test_discovery_without_characteristics_shows_fallback(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """When no characteristics are provided, a fallback message appears."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"address": DEVICE_ADDRESS, "name": DEVICE_NAME},
        )

        assert result["type"] == FlowResultType.FORM
        placeholders = result["description_placeholders"]
        assert "Unknown" in placeholders["characteristics"]

    async def test_discovery_confirm_creates_device_entry(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """Confirming the discovery form creates a device entry with address."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"address": DEVICE_ADDRESS, "name": DEVICE_NAME},
        )

        # User confirms
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == DEVICE_NAME
        assert result2["data"] == {"address": DEVICE_ADDRESS}

    async def test_discovery_duplicate_address_aborts(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """A second discovery for the same address is aborted."""
        # Pre-create the device entry
        existing = make_device_entry()
        existing.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"address": DEVICE_ADDRESS, "name": DEVICE_NAME},
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_discovery_sets_unique_id_to_address(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """The discovery flow sets unique_id to the BLE address."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"address": DEVICE_ADDRESS, "name": DEVICE_NAME},
        )

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["result"].unique_id == DEVICE_ADDRESS

    async def test_discovery_without_name_uses_fallback(
        self,
        hass: HomeAssistant,
        mock_bluetooth_disabled: Generator[None],
    ) -> None:
        """If no name is provided, a fallback is used."""
        addr = "11:22:33:44:55:66"
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={"address": addr},
        )

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        # Fallback name contains last 8 chars of address
        assert "44:55:66" in result2["title"] or "Bluetooth Device" in result2["title"]


# ===================================================================
# 2. Coordinator: _ensure_device_processor fires discovery, not entities
# ===================================================================


class TestCoordinatorDiscoveryGating:
    """Verify the coordinator fires discovery flows instead of creating entities."""

    async def test_ensure_device_processor_fires_discovery_flow(
        self,
        hass: HomeAssistant,
    ) -> None:
        """When a new device with parseable data is seen, a discovery flow is
        fired — not a processor/entity creation.
        """
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        entry = make_hub_entry()
        entry.add_to_hass(hass)

        coordinator = BluetoothSIGCoordinator(hass, entry)
        service_info = make_service_info()

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.discovery_flow.async_create_flow"
        ) as mock_create_flow:
            coordinator._ensure_device_processor(service_info)

            # Discovery flow IS called
            mock_create_flow.assert_called_once()
            call_kwargs = mock_create_flow.call_args
            assert call_kwargs[0][1] == DOMAIN
            assert call_kwargs[1]["data"]["address"] == DEVICE_ADDRESS

        # No processor was created
        assert DEVICE_ADDRESS not in coordinator._processor_coordinators

    async def test_ensure_device_processor_does_not_duplicate_discovery(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A second advertisement for the same address does not fire another
        discovery flow.
        """
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        entry = make_hub_entry()
        entry.add_to_hass(hass)
        coordinator = BluetoothSIGCoordinator(hass, entry)
        service_info = make_service_info()

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.discovery_flow.async_create_flow"
        ) as mock_create_flow:
            coordinator._ensure_device_processor(service_info)
            coordinator._ensure_device_processor(service_info)

            # Called only once
            assert mock_create_flow.call_count == 1

    async def test_ensure_device_processor_no_flow_for_confirmed_device(
        self,
        hass: HomeAssistant,
    ) -> None:
        """If a config entry already exists for the address, no new discovery
        flow is fired.
        """
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)

        # Pre-create a confirmed device entry
        dev = make_device_entry()
        dev.add_to_hass(hass)

        coordinator = BluetoothSIGCoordinator(hass, hub)
        service_info = make_service_info()

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.discovery_flow.async_create_flow"
        ) as mock_create_flow:
            coordinator._ensure_device_processor(service_info)

            # No discovery flow — device already confirmed
            mock_create_flow.assert_not_called()

    async def test_has_config_entry_returns_false_without_entry(
        self,
        hass: HomeAssistant,
    ) -> None:
        """_has_config_entry returns False when no device entry exists."""
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)
        coordinator = BluetoothSIGCoordinator(hass, hub)

        assert coordinator._has_config_entry(DEVICE_ADDRESS) is False

    async def test_has_config_entry_returns_true_with_entry(
        self,
        hass: HomeAssistant,
    ) -> None:
        """_has_config_entry returns True when a confirmed entry exists."""
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)
        dev = make_device_entry()
        dev.add_to_hass(hass)

        coordinator = BluetoothSIGCoordinator(hass, hub)
        assert coordinator._has_config_entry(DEVICE_ADDRESS) is True

    async def test_has_config_entry_does_not_match_random_address(
        self,
        hass: HomeAssistant,
    ) -> None:
        """_has_config_entry returns False for an address with no device entry.

        The hub entry has unique_id==DOMAIN, so it won't match a real BLE
        address. This test verifies that only actual device entries match.
        """
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)
        coordinator = BluetoothSIGCoordinator(hass, hub)

        # A real BLE address does not match the hub's unique_id
        assert coordinator._has_config_entry("FF:FF:FF:FF:FF:FF") is False

    async def test_remove_device_allows_rediscovery(
        self,
        hass: HomeAssistant,
    ) -> None:
        """After remove_device, the same address can be rediscovered."""
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)
        coordinator = BluetoothSIGCoordinator(hass, hub)
        service_info = make_service_info()

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.discovery_flow.async_create_flow"
        ) as mock_create_flow:
            # First discovery
            coordinator._ensure_device_processor(service_info)
            assert mock_create_flow.call_count == 1

            # Remove device
            coordinator.remove_device(DEVICE_ADDRESS)

            # Second discovery after removal
            coordinator._ensure_device_processor(service_info)
            assert mock_create_flow.call_count == 2


# ===================================================================
# 3. End-to-end: discovery → no entities without user approval
# ===================================================================


class TestEndToEndGating:
    """End-to-end proof that entities are gated behind user confirmation."""

    async def test_unapproved_device_has_no_entities(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A device that has been discovered but NOT confirmed by the user
        must have zero entities and zero processors.
        """
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)
        coordinator = BluetoothSIGCoordinator(hass, hub)

        service_info = make_service_info()

        with patch(
            "custom_components.bluetooth_sig_devices.coordinator.discovery_flow.async_create_flow"
        ):
            coordinator._ensure_device_processor(service_info)

        # The device has NOT been confirmed — no processor whatsoever
        assert DEVICE_ADDRESS not in coordinator._processor_coordinators
        assert len(coordinator._processor_coordinators) == 0

    async def test_approved_device_can_get_processor(
        self,
        hass: HomeAssistant,
    ) -> None:
        """After the user confirms a device, create_device_processor creates
        an ActiveBluetoothProcessorCoordinator.
        """
        from custom_components.bluetooth_sig_devices.coordinator import (
            BluetoothSIGCoordinator,
        )

        hub = make_hub_entry()
        hub.add_to_hass(hass)
        dev = make_device_entry()
        dev.add_to_hass(hass)

        coordinator = BluetoothSIGCoordinator(hass, hub)

        mock_add = MagicMock()
        mock_entity_cls = MagicMock()

        with (
            patch(
                "custom_components.bluetooth_sig_devices.coordinator"
                ".ActiveBluetoothProcessorCoordinator"
            ) as mock_abpc,
            patch(
                "custom_components.bluetooth_sig_devices.coordinator"
                ".PassiveBluetoothDataProcessor"
            ),
        ):
            mock_abpc_instance = MagicMock()
            mock_abpc.return_value = mock_abpc_instance

            coordinator.create_device_processor(
                DEVICE_ADDRESS, dev, mock_add, mock_entity_cls
            )

        # Processor WAS created
        assert DEVICE_ADDRESS in coordinator._processor_coordinators
