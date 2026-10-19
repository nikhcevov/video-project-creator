"""XDG paths, minimal configuration and logging setup."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_DIR_NAME = "video-project-creator"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    default_preset: str = "reels"
    auto_close_on_success: bool = True


def _home() -> Path:
    return Path.home()


def _xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME", "")
    path = Path(value) if value else _home() / ".config"
    return path if path.is_absolute() else _home() / ".config"


def _xdg_state_home() -> Path:
    value = os.environ.get("XDG_STATE_HOME", "")
    path = Path(value) if value else _home() / ".local" / "state"
    return path if path.is_absolute() else _home() / ".local" / "state"


def _read_user_dir(entry: str) -> Path | None:
    """Read one entry from the XDG user-dirs file without assuming a name."""
    path = _xdg_config_home() / "user-dirs.dirs"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    prefix = f"{entry}="
    for line in lines:
        line = line.strip()
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        value = value.replace("${HOME}", str(_home())).replace("$HOME", str(_home()))
        candidate = Path(os.path.expanduser(value))
        if candidate.is_absolute():
            return candidate
    return None


def xdg_user_dir(entry: str, fallback: Path) -> Path:
    """Resolve an XDG user directory, preferring the user-dirs file."""
    configured = _read_user_dir(entry)
    if configured is not None:
        return configured

    executable = shutil.which("xdg-user-dir")
    if executable:
        try:
            result = subprocess.run(
                [executable, entry],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            value = result.stdout.strip()
            candidate = Path(value) if value else None
            # The fallback for an unconfigured directory is $HOME; prefer a
            # sensible named directory in that case.
            if candidate is not None and candidate.is_absolute() and candidate != _home():
                return candidate

    return fallback


def videos_dir() -> Path:
    return xdg_user_dir("VIDEOS", _home() / "Videos")


def projects_dir() -> Path:
    return videos_dir() / "Projects"


def config_path() -> Path:
    return _xdg_config_home() / APP_DIR_NAME / "config.toml"


def state_dir() -> Path:
    return _xdg_state_home() / APP_DIR_NAME


def log_path() -> Path:
    return state_dir() / "app.log"


def recovery_dir() -> Path:
    return state_dir() / "recovery"


def lock_path() -> Path:
    return state_dir() / "creation.lock"


def load_config(path: Path | None = None) -> AppConfig:
    """Load config.toml, falling back to safe defaults on any invalid input."""
    from .presets import KNOWN_PRESET_IDS

    target = path if path is not None else config_path()
    defaults = AppConfig()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return defaults
    except OSError as exc:
        _log.warning("Could not read configuration %s: %s", target, exc)
        return defaults

    try:
        data = tomllib.loads(raw)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        _log.warning("Invalid configuration %s: %s", target, exc)
        return defaults

    if not isinstance(data, dict):
        _log.warning("Invalid configuration %s: expected a table", target)
        return defaults

    preset = data.get("default_preset", defaults.default_preset)
    if not isinstance(preset, str) or preset not in KNOWN_PRESET_IDS:
        _log.warning("Invalid default_preset in %s; using %s", target, defaults.default_preset)
        preset = defaults.default_preset

    auto_close = data.get("auto_close_on_success", defaults.auto_close_on_success)
    if not isinstance(auto_close, bool):
        _log.warning("Invalid auto_close_on_success in %s; using default", target)
        auto_close = defaults.auto_close_on_success

    return AppConfig(default_preset=preset, auto_close_on_success=auto_close)


def setup_logging(path: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure the application logger once."""
    logger = logging.getLogger("video_project_creator")
    if logger.handlers:
        return logger

    target = path if path is not None else log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        target,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    debug = os.environ.get("VIDEO_PROJECT_CREATOR_DEBUG")
    if debug:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(stream)

    return logger
