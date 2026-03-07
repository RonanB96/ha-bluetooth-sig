# Remove the Integration

This guide explains how to completely uninstall the Bluetooth SIG Devices integration.

## Steps

1. Go to **Settings → Devices & Services**
2. Find **Bluetooth SIG Devices** in your integrations list
3. Select the three-dot menu (⋮) on the main integration entry
4. Choose **Delete**
5. Confirm the deletion

This removes:
- The hub entry (global BLE scanner)
- All device entries and their sensor entities
- All discovery state

## Uninstall the files

After removing the integration from Home Assistant:

### If installed via HACS

1. Open **HACS → Integrations**
2. Find **Bluetooth SIG Devices**
3. Select the three-dot menu (⋮) and choose **Remove**
4. Restart Home Assistant

### If installed manually

1. Delete the `custom_components/bluetooth_sig_devices` directory from your Home Assistant config folder
2. Restart Home Assistant
