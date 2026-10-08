"""Configuration loader for ocdu.

ocdu reads a single JSON file at ``~/.config/opencode/ocdu-ui.json``. Every key
defined there overrides the built-in defaults below; missing keys fall back to
the default, so an empty or absent file is perfectly valid. Values support
``${KEY}`` references (expanded after all values are merged) and ``~`` is
expanded to the user home directory.
"""

from __future__ import annotations
import contextlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# Location of the single configuration file. This is intentionally fixed (it is
# not read from the file itself) to avoid a chicken-and-egg problem.
CONFIG_DIR = Path(os.path.expanduser("~/.config/opencode"))
CONFIG_FILE = CONFIG_DIR / "ocdu-ui.json"

# Authoritative defaults. Anything omitted from the JSON file resolves here.
_DEFAULTS = {
    "OPENCODE_DATA_DIR": "~/.local/share/opencode",
    "OPENCODE_STATE_DIR": "~/.local/state/opencode",
    "OPENCODE_CACHE_DIR": "~/.cache/opencode",
    "OPENCODE_CONFIG_DIR": "~/.config/opencode",
    "OPENCODE_DB_FILE": "opencode.db",
    "BACKUP_DIR": "${OPENCODE_DATA_DIR}/backups",
    "BACKUP_KEEP": "3",
    "EXPORT_DIR": "${OPENCODE_DATA_DIR}/exports",
    "SCREENSHOT_DIR": "${OPENCODE_DATA_DIR}/screenshots",
    "OPENCODE_BIN": "opencode",
    "OPENCODE_CLI_TIMEOUT": "120",
    "LOG_RETENTION_DAYS": "30",
    "TUI_REFRESH_SECONDS": "0",
    "THEME": "textual-dark",
    "DIST_DIR": "dist",
}

_REFERENCE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def _read_raw_config(path: Path) -> dict:
    """Read the JSON config file, preserving value types."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def _parse_config_file(path: Path) -> dict[str, str]:
    """Read the JSON config file as a flat ``KEY -> VALUE`` string mapping."""
    return {str(key): str(value) for key, value in _read_raw_config(path).items()}

def _expand_references(values: dict[str, str], max_passes: int = 10) -> dict[str, str]:
    """Resolve ``${KEY}`` references between values."""

    def resolve(value: str, depth: int) -> str:
        """Resolve references within a single value up to ``max_passes``."""
        if depth > max_passes:
            return value

        def replace(match: re.Match[str]) -> str:
            """Resolve the key captured by a ``${KEY}`` match."""
            key = match.group(1)
            return resolve(values.get(key, ""), depth + 1)

        return _REFERENCE_RE.sub(replace, value)

    return {key: resolve(value, 0) for key, value in values.items()}

def _norm_path(value: str) -> str:
    """Expand ``~`` and trim whitespace from a path string."""
    return os.path.expanduser(value.strip())

@dataclass(frozen=True)
class Config:
    """Resolved configuration with typed accessors."""

    values: dict[str, str]

    # -- raw access ----------------------------------------------------------
    def get(self, key: str, fallback: str = "") -> str:
        """Return the string value for ``key`` or ``fallback`` when empty."""
        value = self.values.get(key, "")
        return value if value != "" else fallback

    def get_int(self, key: str, fallback: int = 0) -> int:
        """Return the integer value for ``key`` or ``fallback`` when invalid."""
        raw = self.get(key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return fallback

    # -- paths ---------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        """Return the resolved data directory."""
        return Path(_norm_path(self.get("OPENCODE_DATA_DIR")))

    @property
    def state_dir(self) -> Path:
        """Return the resolved state directory."""
        return Path(_norm_path(self.get("OPENCODE_STATE_DIR")))

    @property
    def cache_dir(self) -> Path:
        """Return the resolved cache directory."""
        return Path(_norm_path(self.get("OPENCODE_CACHE_DIR")))

    @property
    def config_dir(self) -> Path:
        """Return the resolved config directory."""
        return Path(_norm_path(self.get("OPENCODE_CONFIG_DIR")))

    @property
    def db_path(self) -> Path:
        """Return the resolved database file path."""
        return self.data_dir / self.get("OPENCODE_DB_FILE", "opencode.db")

    @property
    def backup_dir(self) -> Path:
        """Return the resolved backup directory."""
        return Path(_norm_path(self.get("BACKUP_DIR")))

    @property
    def export_dir(self) -> Path:
        """Return the resolved export directory."""
        return Path(_norm_path(self.get("EXPORT_DIR")))

    @property
    def screenshot_dir(self) -> Path:
        """Return the resolved screenshot directory."""
        return Path(_norm_path(self.get("SCREENSHOT_DIR")))

    @property
    def dist_dir(self) -> Path:
        """Return the resolved build output directory."""
        return Path(_norm_path(self.get("DIST_DIR", "dist")))

    @property
    def opencode_bin(self) -> str:
        """Return the configured opencode executable name."""
        return self.get("OPENCODE_BIN", "opencode")

    @property
    def opencode_cli_timeout(self) -> int:
        """Return the opencode CLI timeout in seconds."""
        return self.get_int("OPENCODE_CLI_TIMEOUT", 120)

    @property
    def backup_keep(self) -> int:
        """Return the number of backups to keep."""
        return max(1, self.get_int("BACKUP_KEEP", 3))

    @property
    def log_retention_days(self) -> int:
        """Return the log retention window in days."""
        return self.get_int("LOG_RETENTION_DAYS", 30)

    @property
    def tui_refresh_seconds(self) -> int:
        """Return the TUI refresh interval in seconds."""
        return self.get_int("TUI_REFRESH_SECONDS", 0)

    @property
    def theme(self) -> str:
        """Return the configured TUI theme name."""
        return self.get("THEME", "textual-dark")

def load_config(config_file: Path = CONFIG_FILE) -> Config:
    """Build the effective config from built-in defaults + the JSON file."""
    merged = dict(_DEFAULTS)
    merged.update(_parse_config_file(config_file))
    merged = _expand_references(merged)
    return Config(merged)

def save_ui_overrides(updates: dict[str, str], config_file: Path = CONFIG_FILE) -> Path:
    """Merge ``updates`` into the JSON config file and return its path.

    The file is written atomically (temp file + ``os.replace``) so a crash mid
    write cannot leave a truncated JSON that would reset every user override.
    """
    data = _read_raw_config(config_file)
    data.update(updates)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temp_file = config_file.with_name(config_file.name + ".part")
    try:
        temp_file.write_text(payload, encoding="utf-8")
        os.replace(temp_file, config_file)
    except BaseException:
        with contextlib.suppress(OSError):
            temp_file.unlink()
        raise
    return config_file

config = load_config()
