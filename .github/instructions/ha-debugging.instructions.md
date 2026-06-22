---
description: "Build, lint, test, and live Home Assistant debugging commands"
alwaysApply: false
---

# HA Debugging — Build Commands & Live HA

## Local Development

See [tests/TESTING.md](../../tests/TESTING.md) for setup, install, and test-run commands.

Lint, format, and type-check (not covered in TESTING.md):
```bash
ruff check . --fix && ruff format .
mypy custom_components/bluetooth_sig_devices
```

## Live HA Debugging

The HA instance runs in a supervised Docker environment. **Always read real logs before diagnosing — never guess at root causes.**

```bash
# Read recent HA Core logs
ha core logs
ha core logs --lines 5000

# Filter for this integration
ha core logs 2>&1 | grep -i "bluetooth_sig_devices"
ha core logs --lines 5000 2>&1 | grep -i "bluetooth_sig" | grep -iE "firing|discovery|flow|trigger"

# Restart HA Core after code changes
ha core restart

# Run a command inside the HA Core container
docker exec homeassistant <command>
```

HA config directory: `/homeassistant/`

## Key Log Namespaces

| Namespace | What it covers |
|-----------|---------------|
| `custom_components.bluetooth_sig_devices` | This integration |
| `bluetooth_sig` | Upstream library |
| `habluetooth.wrappers` | BLE connection path selection (upstream HA) |

For how to enable debug logging, see [docs/how-to/enable-debug-logging.md](../../docs/how-to/enable-debug-logging.md).
