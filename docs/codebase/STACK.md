# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

| Area | Value | Evidence |
|------|-------|----------|
| Primary language | Python 3.12+ | `pyproject.toml` (`requires-python = ">=3.12"`), `.github/workflows/ci.yml` (`DEFAULT_PYTHON: "3.12"`) |
| Runtime + version | Home Assistant **2026.1.0+** custom integration | `hacs.json`, `docs/reference/configuration.md` |
| Package manager | pip (editable install for dev/test); hatchling for wheel build | `pyproject.toml` (`[build-system]`, `[project.optional-dependencies]`) |
| Module/build system | Hatchling + hatch-vcs (dynamic version from git tags) | `pyproject.toml` (`[tool.hatch.version]`) |

### 2) Production Frameworks and Dependencies

List only high-impact production dependencies (frameworks, data, transport, auth).

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| `bluetooth-sig` | `>=0.4.1` / `~=0.4.1` | Parses SIG GATT characteristics, manufacturer data, and advertisement payloads | `custom_components/bluetooth_sig_devices/manifest.json`, `pyproject.toml` |
| `bleak-retry-connector` | `>=3.0.0` | Resilient BLE GATT connections via Bleak | `custom_components/bluetooth_sig_devices/manifest.json`, `device_adapter.py` |
| Home Assistant `bluetooth` component | Provided by HA Core at runtime | Passive scanning, callbacks, `ActiveBluetoothProcessorCoordinator` | `manifest.json` (`dependencies: ["bluetooth"]`), `coordinator.py` |
| Home Assistant Core APIs | Provided by HA Core at runtime | Config entries, entities, diagnostics, event loop | `__init__.py`, `sensor.py`, `config_flow.py` |

### 3) Development Toolchain

| Tool | Purpose | Evidence |
|------|---------|----------|
| Ruff | Lint + format (E, W, F, I, UP, B, C4, SIM) | `pyproject.toml` (`[tool.ruff]`), `.github/workflows/ci.yml` |
| mypy | Strict static typing | `pyproject.toml` (`[tool.mypy]`, `strict = true`), `.github/workflows/ci.yml` |
| pytest | Test runner (`asyncio_mode = auto`) | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| pytest-homeassistant-custom-component | HA test fixtures without full HA fork | `pyproject.toml` (`[project.optional-dependencies].test`) |
| GitHub Actions | CI (ruff, mypy, pytest+coverage on 3.12/3.13) | `.github/workflows/ci.yml`, `.github/workflows/hacs.yml` |
| HACS validation workflow | Integration packaging checks | `.github/workflows/hacs.yml` |

### 4) Key Commands

```bash
# Install for development / testing
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[test,dev]"
pip install aiousbwatcher  # required by HA bluetooth test stack; see tests/TESTING.md

# Lint and format
ruff check . --fix && ruff format .

# Type check
mypy custom_components/bluetooth_sig_devices

# Run tests
pytest tests/ -v

# Run tests with coverage (matches CI)
pytest tests/ -v --cov=custom_components/bluetooth_sig_devices --cov-report=term-missing
```

### 5) Environment and Config

- Config sources: Home Assistant config entry data/options (no `.env` in repo); hub and per-device options in `custom_components/bluetooth_sig_devices/const.py` and `config_flow.py`
- Required env vars: none for the integration itself; HA runtime provides Bluetooth stack access
- Deployment/runtime constraints: Requires HA with working Bluetooth scanner (`bluetooth.async_scanner_count` check in `__init__.py`); `manifest.json` lists `after_dependencies: ["bluetooth_adapters"]`

### 6) Evidence

- `pyproject.toml`
- `custom_components/bluetooth_sig_devices/manifest.json`
- `.github/workflows/ci.yml`
- `tests/TESTING.md`
