"""Application version from the package built using server/pyproject.toml."""

from importlib.metadata import version

APP_VERSION = version("modbus-monitor-server")
