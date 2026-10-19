"""User-facing exceptions for project creation."""

from __future__ import annotations

from pathlib import Path


class ProjectCreatorError(Exception):
    """Base class for failures that can be shown to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @property
    def user_message(self) -> str:
        return self.message


class ValidationError(ProjectCreatorError):
    """The requested project name or preset is not valid."""


class NameConflictError(ProjectCreatorError):
    """A Resolve project with this name already exists in the current folder."""


class DirectoryConflictError(ProjectCreatorError):
    """The filesystem project directory already exists."""


class ConcurrentCreationError(ProjectCreatorError):
    """Another instance is creating a project right now."""


class ResolveUnavailable(ProjectCreatorError):
    """DaVinci Resolve cannot be reached through its scripting API."""


class ResolveOperationError(ProjectCreatorError):
    """A specific Resolve operation failed or could not be verified."""

    def __init__(self, message: str, stage: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.detail = detail


class PartialCreationError(ProjectCreatorError):
    """The Resolve project exists but the combined operation did not finish."""

    def __init__(
        self,
        message: str,
        *,
        project_name: str,
        resolve_project_id: str | None,
        stage: str,
        recovery_path: Path | None,
        staging_dir: Path | None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.project_name = project_name
        self.resolve_project_id = resolve_project_id
        self.stage = stage
        self.recovery_path = recovery_path
        self.staging_dir = staging_dir
        self.cause = cause
