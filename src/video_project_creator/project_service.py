"""Coordinates the filesystem and Resolve sides of project creation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config
from .errors import (
    DirectoryConflictError,
    PartialCreationError,
    ProjectCreatorError,
    ValidationError,
)
from .filesystem import (
    METADATA_FILENAME,
    CreationLock,
    create_staging_directory,
    project_directory_name,
    publish_project,
    remove_staging_if_empty,
    slugify,
    validate_project_name,
    write_json_atomic,
)
from .presets import Preset, get_preset
from .resolve_api import ResolveAdapter

_log = logging.getLogger(__name__)

BIN_NAMES = ("Camera Footage", "Music", "Graphics")
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CreationResult:
    project_name: str
    project_dir: Path
    metadata: dict[str, Any]
    warnings: tuple[str, ...]
    resolve_version: str


class ProjectService:
    def __init__(
        self,
        *,
        adapter_factory: Callable[[], ResolveAdapter] = ResolveAdapter,
        projects_root: Path | None = None,
        state_root: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._projects_root = projects_root
        self._state_root = state_root
        self._now = now

    def _root(self) -> Path:
        return self._projects_root if self._projects_root is not None else config.projects_dir()

    def _state(self) -> Path:
        return self._state_root if self._state_root is not None else config.state_dir()

    def check_resolve(self) -> str:
        adapter = self._adapter_factory()
        adapter.connect()
        return adapter.get_version()

    def create(self, raw_name: str, preset_id: str) -> CreationResult:
        name = validate_project_name(raw_name)
        try:
            preset = get_preset(preset_id)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None

        with CreationLock(self._state() / "creation.lock"):
            return self._create_locked(name, preset)

    def _create_locked(self, name: str, preset: Preset) -> CreationResult:
        _log.info("Starting project creation name=%r preset=%s", name, preset.id)

        adapter = self._adapter_factory()
        adapter.connect()
        resolve_version = adapter.get_version()

        # Never create anything until the open Resolve project is safely saved.
        adapter.ensure_current_project_saved()
        library = adapter.get_library_identity()
        _log.info("Selected Resolve library: %s", library)

        adapter.ensure_name_available(name)

        timestamp = self._now() if self._now is not None else datetime.now().astimezone()
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
        day = timestamp.date()
        final_dir = self._root() / project_directory_name(name, day)
        if final_dir.exists():
            raise DirectoryConflictError(
                f"A project folder for '{name}' already exists. Choose another project name."
            )

        try:
            staging = create_staging_directory(self._root())
        except OSError as exc:
            raise ProjectCreatorError(
                "Could not create the project folder. Check permissions for "
                f"{self._root()}."
            ) from exc

        _log.info("Prepared staging directory %s", staging)
        project_created = False
        resolve_project_id: str | None = None

        try:
            project = adapter.create_project(name)
            project_created = True
            resolve_project_id = adapter.get_project_id(project)

            warnings = adapter.apply_preset(project, preset)
            adapter.create_timeline(project, preset.timeline_name)
            warnings.extend(adapter.create_bins(project, BIN_NAMES))
            adapter.save_project(project, name)

            metadata = self._build_metadata(
                name=name,
                preset=preset,
                resolve_project_id=resolve_project_id,
                library=library,
                created_at=timestamp,
            )
            write_json_atomic(staging / METADATA_FILENAME, metadata)
            publish_project(staging, final_dir)

            if not final_dir.is_dir() or not (final_dir / METADATA_FILENAME).is_file():
                raise ProjectCreatorError(
                    "The project folder could not be verified after publishing."
                )

            _log.info("Created project %r at %s", name, final_dir)
            return CreationResult(
                project_name=name,
                project_dir=final_dir,
                metadata=metadata,
                warnings=tuple(warnings),
                resolve_version=resolve_version,
            )
        except ProjectCreatorError as exc:
            if project_created:
                raise self._partial_error(
                    name=name,
                    preset=preset,
                    resolve_project_id=resolve_project_id,
                    library=library,
                    created_at=timestamp,
                    staging=staging,
                    final_dir=final_dir,
                    cause=exc,
                ) from exc
            remove_staging_if_empty(staging)
            raise
        except Exception as exc:
            if project_created:
                raise self._partial_error(
                    name=name,
                    preset=preset,
                    resolve_project_id=resolve_project_id,
                    library=library,
                    created_at=timestamp,
                    staging=staging,
                    final_dir=final_dir,
                    cause=exc,
                ) from exc
            remove_staging_if_empty(staging)
            _log.exception("Unexpected project creation failure")
            raise ProjectCreatorError(
                "The project could not be created. See the application log for details."
            ) from exc

    def _build_metadata(
        self,
        *,
        name: str,
        preset: Preset,
        resolve_project_id: str | None,
        library: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "project_name": name,
            "resolve_project_name": name,
            "resolve_project_id": resolve_project_id,
            "resolve_library": library,
            "preset": preset.id,
            "created_at": created_at.isoformat(timespec="seconds"),
            "status": "active",
        }

    def _partial_error(
        self,
        *,
        name: str,
        preset: Preset,
        resolve_project_id: str | None,
        library: dict[str, Any],
        created_at: datetime,
        staging: Path,
        final_dir: Path,
        cause: BaseException,
    ) -> PartialCreationError:
        stage = str(getattr(cause, "stage", "post_creation"))
        recovery_path = self._record_recovery(
            name=name,
            preset=preset,
            resolve_project_id=resolve_project_id,
            library=library,
            created_at=created_at,
            staging=staging,
            final_dir=final_dir,
            cause=cause,
            stage=stage,
        )
        if isinstance(cause, ProjectCreatorError):
            detail = cause.user_message
        else:
            detail = "an unexpected error occurred"
        recovery_note = (
            f"Recovery details: {recovery_path}."
            if recovery_path is not None
            else "See the application log for details."
        )
        message = (
            f"DaVinci Resolve project '{name}' was created, but the operation failed "
            f"afterwards ({stage}): {detail} "
            "The Resolve project was left open and was not deleted. "
            f"{recovery_note} Check the project in Resolve before trying again."
        )
        _log.error("Partial project creation: %s", message)
        return PartialCreationError(
            message,
            project_name=name,
            resolve_project_id=resolve_project_id,
            stage=stage,
            recovery_path=recovery_path,
            staging_dir=staging,
            cause=cause,
        )

    def _record_recovery(
        self,
        *,
        name: str,
        preset: Preset,
        resolve_project_id: str | None,
        library: dict[str, Any],
        created_at: datetime,
        staging: Path,
        final_dir: Path,
        cause: BaseException,
        stage: str,
    ) -> Path | None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "project_name": name,
            "resolve_project_name": name,
            "resolve_project_id": resolve_project_id,
            "resolve_library": library,
            "preset": preset.id,
            "created_at": created_at.isoformat(timespec="seconds"),
            "status": "partial",
            "stage": stage,
            "error": str(cause),
            "staging_dir": str(staging),
            "final_dir": str(final_dir),
        }
        path = (
            self._state()
            / "recovery"
            / f"{created_at.strftime('%Y%m%dT%H%M%S')}-{slugify(name) or 'project'}.json"
        )
        try:
            write_json_atomic(path, payload)
        except OSError as exc:
            _log.error("Could not write recovery details to %s: %s", path, exc)
            return None
        _log.error("Wrote recovery details to %s", path)
        return path
