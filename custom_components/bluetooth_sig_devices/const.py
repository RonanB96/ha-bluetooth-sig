"""Constants for the Bluetooth SIG Devices integration."""

from datetime import timedelta

DOMAIN = "bluetooth_sig_devices"

# Configuration keys (CONF_POLL_INTERVAL is active; others reserved for
# planned custom-device configuration and bindkey support)
CONF_BINDKEY = "bindkey"
CONF_CUSTOM_DEVICES = "custom_devices"
CONF_DEVICE_ADDRESS = "address"
CONF_DEVICE_NAME = "name"
CONF_POLL_INTERVAL = "poll_interval"
CONF_FORCE_PROBE = "force_probe"

# Attributes (reserved for future entity extra-state attributes)
ATTR_MANUFACTURER = "manufacturer"
ATTR_MODEL = "model"
ATTR_SIGNAL_STRENGTH = "rssi"

# GATT connection defaults
DEFAULT_POLL_INTERVAL = timedelta(minutes=5)
MIN_POLL_INTERVAL_SECONDS = 30
MAX_POLL_INTERVAL_SECONDS = 86400  # 24 hours
# Canonical timeout values - import these in device_adapter.py
DEFAULT_CONNECTION_TIMEOUT = 30.0
DEFAULT_READ_TIMEOUT = 10.0

# Probe configuration
MAX_PROBE_FAILURES = 3
MAX_CONCURRENT_PROBES = 2
PROBE_FAILURE_BACKOFF_MINUTES = [5, 30, 120]  # Reserved for exponential backoff

# Services that should NOT count as "parseable SIG data"
# These are standard BLE services that any BLE monitor can expose
# The actual UUIDs are retrieved from the bluetooth-sig library at runtime
EXCLUDED_SERVICE_NAMES: frozenset[str] = frozenset(
    {
        "GAP",  # Generic Access Profile - basic device identity
        "GATT",  # Generic Attribute Profile - protocol infrastructure
    }
)

# Entity key prefixes (reserved for consistent key generation)
ENTITY_KEY_PREFIX_GATT = "gatt_"
ENTITY_KEY_PREFIX_ADVERT = "adv_"
