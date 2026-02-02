# Testing Guide for Bluetooth SIG Devices Integration

This integration provides **two ways** to test - you don't need to fork Home Assistant core!

## 1. Unit Testing (Automated)

Uses `pytest-homeassistant-custom-component` to run tests without a full HA installation.

### Setup
```bash
# Activate venv
source .venv/bin/activate

# Install with test dependencies
pip install -e ".[test]"

# Install missing USB watcher dependency
pip install aiousbwatcher
```

### Run Tests
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_sensor.py -v

# Run with coverage
pytest tests/ --cov=bluetooth_sig_devices --cov-report=term-missing
```

### Key Points
- Tests use HA's testing fixtures (hass, `MockConfigEntry`, etc.)
- Mocks Bluetooth adapters automatically
- No real HA instance needed
- Fast iteration for TDD

---

## 2. Live Testing (Manual)

Test in a real Home Assistant instance.

### Method A: Copy to Development HA Instance

1. **Set up a test HA instance**:
```bash
# Create a test directory
mkdir ~/homeassistant-test
cd ~/homeassistant-test

# Create venv with Python 3.14
python3.14 -m venv venv
source venv/bin/activate

# Install Home Assistant
pip install homeassistant
```

2. **Copy your integration**:
```bash
# Create custom_components directory
mkdir -p ~/homeassistant-test/config/custom_components

# Link or copy your integration
ln -s /home/ronan/Documents/GitHub/ha-bluetooth-sig/custom_components/bluetooth_sig_devices \
        ~/homeassistant-test/config/custom_components/bluetooth_sig_devices
```

3. **Run Home Assistant**:
```bash
hass -c ~/homeassistant-test/config --debug
```

4. **Access**: Open http://localhost:8123 in your browser

### Method B: Use Your Production HA (Carefully!)

1. **Copy integration to your running HA**:
```bash
# If using Home Assistant OS/Supervised
# Copy via SSH or Samba to /config/custom_components/bluetooth_sig_devices

# If using Container
cp -r custom_components/bluetooth_sig_devices /path/to/ha/config/custom_components/
```

2. **Restart Home Assistant** to load the integration

3. **Add via UI**: Settings → Devices & Services → Add Integration

### Method C: Use DevContainer (Recommended for Active Development)

The integration template supports VS Code devcontainers with a full HA development environment.

---

## Testing Workflow

### Development Cycle
1. **Write/modify code** in your integration
2. **Write unit tests** for the functionality
3. **Run pytest** to verify unit tests pass
4. **Copy to test HA** for integration testing
5. **Test real Bluetooth devices** with the live instance

### Before Committing
```bash
# Run all tests
pytest tests/ -v

# Check code quality (if you add ruff/mypy)
ruff check custom_components/
```

---

## Common Issues

### Missing Dependencies
If tests fail with `ModuleNotFoundError`, install the missing package:
```bash
pip install aiousbwatcher  # For USB-dependent tests
```

### Import Errors
Make sure `custom_components/__init__.py` exists (can be empty).

### Bluetooth Not Available in Tests
Tests use mocked Bluetooth - see `tests/conftest.py` for the mock setup.

---

## Resources
- [HA Testing Docs](https://developers.home-assistant.io/docs/development_testing/)
- [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
- [Integration Development Guide](https://developers.home-assistant.io/docs/creating_component_index/)
