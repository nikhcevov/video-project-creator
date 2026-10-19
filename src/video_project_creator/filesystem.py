"""Project names, staging directories, atomic metadata and locking."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import json
import os
import shutil
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from .errors import ConcurrentCreationError, DirectoryConflictError, ValidationError

MAX_PROJECT_NAME_CHARS = 120
MAX_SLUG_BYTES = 200
METADATA_FILENAME = ".project.json"
_ASSETS_DIR = "Assets"
_EXPORTS_DIR = "Exports"

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def validate_project_name(raw: str) -> str:
    """Return the trimmed display name or raise a user-facing error."""
    if not isinstance(raw, str):
        raise ValidationError("Enter a project name.")
    name = raw.strip()
    if not name:
        raise ValidationError("Enter a project name.")
    if len(name) > MAX_PROJECT_NAME_CHARS:
        raise ValidationError(
            f"Project names can be at most {MAX_PROJECT_NAME_CHARS} characters."
        )
    for char in name:
        if char in {"/", "\\"} or unicodedata.category(char) in {"Cc", "Cs"}:
            raise ValidationError(
                "Project names cannot contain slashes or control characters."
            )
    if name in {".", ".."}:
        raise ValidationError("That project name cannot be used.")
    if not slugify(name):
        raise ValidationError("That project name cannot be used.")
    return name


def slugify(name: str) -> str:
    """Create a deterministic, filesystem-safe slug while preserving Unicode."""
    normalized = unicodedata.normalize("NFC", name).strip()
    pieces: list[str] = []
    for char in normalized:
        if char.isspace():
            pieces.append("-")
        elif char.isalnum() or char in "._-":
            pieces.append(char)
        else:
            pieces.append("-")

    slug = "".join(pieces)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-._")
    encoded = slug.encode("utf-8")
    if len(encoded) > MAX_SLUG_BYTES:
        slug = encoded[:MAX_SLUG_BYTES].decode("utf-8", "ignore").rstrip("-._")
    return slug


def project_directory_name(name: str, day: date) -> str:
    slug = slugify(name)
    if not slug:
        raise ValidationError("That project name cannot be used.")
    return f"{day.isoformat()}-{slug}"


def create_staging_directory(projects_root: Path) -> Path:
    """Create a hidden staging directory next to the eventual project directory."""
    projects_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".creating-", dir=projects_root))
    staging.chmod(0o755)
    (staging / _ASSETS_DIR).mkdir()
    (staging / _EXPORTS_DIR).mkdir()
    return staging


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON with a same-directory temporary file and fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{os.urandom(4).hex()}")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def publish_project(staging: Path, final: Path) -> None:
    """Atomically move the staging directory to its final path without overwriting."""
    if final.exists():
        raise DirectoryConflictError(
            f"A project folder named '{final.name}' already exists. "
            "Choose another project name."
        )
    _rename_noreplace(staging, final)


def _rename_noreplace(source: Path, destination: Path) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        renameat2 = None

    if renameat2 is not None:
        result = renameat2(
            _AT_FDCWD,
            os.fsencode(source),
            _AT_FDCWD,
            os.fsencode(destination),
            _RENAME_NOREPLACE,
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise DirectoryConflictError(
                f"A project folder named '{destination.name}' already exists. "
                "Choose another project name."
            )
        if error not in {errno.ENOSYS, errno.EINVAL}:
            raise OSError(error, os.strerror(error), str(destination))

    if destination.exists():
        raise DirectoryConflictError(
            f"A project folder named '{destination.name}' already exists. "
            "Choose another project name."
        )
    os.rename(source, destination)


def remove_staging_if_empty(staging: Path) -> None:
    """Remove a staging directory only when it contains no files."""
    if not staging.exists():
        return
    for _root, _directories, filenames in os.walk(staging):
        if filenames:
            return
    shutil.rmtree(staging, ignore_errors=True)


class CreationLock:
    """Non-blocking, process-lifetime flock for project creation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def __enter__(self) -> "CreationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise ConcurrentCreationError(
                "Another project is already being created. Wait for it to finish, then try again."
            ) from None
        self._handle = handle
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None
