"""Thin, verifying wrapper around the DaVinci Resolve scripting API."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

from .errors import NameConflictError, ResolveOperationError, ResolveUnavailable
from .presets import Preset

_log = logging.getLogger(__name__)

DEFAULT_MODULE_DIRECTORIES = (
    Path("/opt/resolve/Developer/Scripting/Modules"),
)
_SIZE_KEYS = {"timelineResolutionWidth", "timelineResolutionHeight"}


def _default_module_loader() -> Any:
    try:
        import DaVinciResolveScript as module
    except ImportError:
        candidates: list[Path] = []
        api = os.environ.get("RESOLVE_SCRIPT_API")
        if api:
            candidates.append(Path(api) / "Modules")
        candidates.extend(DEFAULT_MODULE_DIRECTORIES)
        for candidate in candidates:
            if (candidate / "DaVinciResolveScript.py").is_file():
                sys.path.insert(0, str(candidate))
                break
        import DaVinciResolveScript as module
    return module


class ResolveAdapter:
    """Wraps the parts of the Resolve API this application depends on."""

    def __init__(
        self,
        resolve: Any | None = None,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._resolve = resolve
        self._project_manager: Any | None = None
        self._module_loader = module_loader or _default_module_loader

    def connect(self) -> None:
        if self._resolve is None:
            try:
                module = self._module_loader()
            except Exception as exc:
                raise ResolveUnavailable(
                    "DaVinci Resolve scripting support could not be loaded. "
                    "Check that DaVinci Resolve Studio is installed."
                ) from exc
            try:
                resolve = module.scriptapp("Resolve")
            except Exception as exc:
                raise ResolveUnavailable(
                    "Could not connect to DaVinci Resolve. Start Resolve, then retry."
                ) from exc
            if resolve is None:
                raise ResolveUnavailable(
                    "DaVinci Resolve is not running, or external scripting is disabled. "
                    "Open Resolve, set Preferences → System → General → "
                    "External scripting using → Local, then retry."
                )
            self._resolve = resolve

        is_studio = getattr(self._resolve, "IsStudio", None)
        if callable(is_studio):
            try:
                if not is_studio():
                    raise ResolveUnavailable(
                        "DaVinci Resolve Studio is required for external scripting."
                    )
            except ResolveUnavailable:
                raise
            except Exception:
                pass

        try:
            project_manager = self._resolve.GetProjectManager()
        except Exception as exc:
            raise ResolveUnavailable(
                "DaVinci Resolve is still starting. Wait for the Project Manager, then retry."
            ) from exc
        if project_manager is None:
            raise ResolveUnavailable(
                "DaVinci Resolve is still starting. Wait for the Project Manager, then retry."
            )
        self._project_manager = project_manager

    def _pm(self) -> Any:
        if self._project_manager is None:
            self.connect()
        if self._project_manager is None:
            raise ResolveUnavailable("The Resolve Project Manager is unavailable.")
        return self._project_manager

    def get_version(self) -> str:
        try:
            return str(self._resolve.GetVersionString())
        except Exception:
            return "unknown"

    def get_current_project(self) -> Any | None:
        try:
            return self._resolve.GetCurrentProject()
        except Exception:
            try:
                return self._pm().GetCurrentProject()
            except Exception:
                return None

    def ensure_current_project_saved(self) -> None:
        project = self.get_current_project()
        if project is None:
            return
        try:
            name = project.GetName()
        except Exception:
            name = "the open project"
        try:
            saved = self._pm().SaveProject()
        except Exception as exc:
            raise ResolveOperationError(
                f"Could not save the currently open project '{name}'. "
                "Save it in Resolve, then try again.",
                stage="save_existing",
                detail=str(exc),
            ) from exc
        if saved is False:
            raise ResolveOperationError(
                f"Could not save the currently open project '{name}'. "
                "Save it in Resolve, then try again.",
                stage="save_existing",
            )
        if saved is None:
            # Resolve 21.1.1 returns None instead of True when there are no
            # pending changes. Only an explicit False is treated as failure.
            _log.warning(
                "SaveProject returned no result for %r; assuming no pending changes", name
            )
        _log.info("Saved the previously open project %r", name)

    def get_library_identity(self) -> dict[str, Any]:
        identity: dict[str, Any] = {}
        try:
            database = self._pm().GetCurrentDatabase()
        except Exception:
            database = None
        if isinstance(database, dict):
            key_names = {
                "DbType": "db_type",
                "DbName": "db_name",
                "IpAddress": "ip_address",
            }
            for key, value in database.items():
                if isinstance(value, (str, int, float, bool)):
                    identity[key_names.get(key, key.lower())] = value
        try:
            folder = self._pm().GetCurrentFolder()
        except Exception:
            folder = None
        if isinstance(folder, str) and folder:
            identity["folder"] = folder
        return identity

    def ensure_name_available(self, name: str) -> None:
        try:
            projects = self._pm().GetProjectListInCurrentFolder()
        except Exception as exc:
            raise ResolveOperationError(
                "Could not check the project names in the current Project Library folder.",
                stage="check_name",
                detail=str(exc),
            ) from exc
        if not isinstance(projects, (list, tuple)):
            projects = []
        folded = name.casefold()
        if any(isinstance(existing, str) and existing.casefold() == folded for existing in projects):
            raise NameConflictError(
                f"A Resolve project named '{name}' already exists in the current "
                "Project Library folder. Choose another name."
            )

    def create_project(self, name: str) -> Any:
        try:
            project = self._pm().CreateProject(name)
        except Exception as exc:
            raise ResolveOperationError(
                f"DaVinci Resolve could not create the project '{name}'.",
                stage="create_project",
                detail=str(exc),
            ) from exc
        if project is None:
            raise ResolveOperationError(
                f"DaVinci Resolve did not create the project '{name}'. "
                "Check that the project name is not already used and that "
                "Preferences → System → General → Automatic scripted actions "
                "is set to Allow all; external scripts cannot create projects "
                "in Allow safe mode.",
                stage="create_project",
            )
        try:
            actual_name = project.GetName()
        except Exception as exc:
            raise ResolveOperationError(
                f"DaVinci Resolve created a project but its name could not be verified.",
                stage="create_project",
                detail=str(exc),
            ) from exc
        if actual_name != name:
            raise ResolveOperationError(
                f"DaVinci Resolve created a project named '{actual_name}' instead of '{name}'.",
                stage="create_project",
            )
        _log.info("Created Resolve project %r", name)
        return project

    def get_project_settings(self, project: Any) -> dict[str, Any]:
        try:
            settings = project.GetSettings()
        except Exception as exc:
            raise ResolveOperationError(
                "Could not read the Resolve project settings.",
                stage="verify_settings",
                detail=str(exc),
            ) from exc
        return settings if isinstance(settings, dict) else {}

    def apply_preset(self, project: Any, preset: Preset) -> list[str]:
        requested = preset.resolve_settings()
        try:
            applied = project.SetSettings(requested)
        except Exception as exc:
            raise ResolveOperationError(
                "DaVinci Resolve rejected the project settings.",
                stage="apply_settings",
                detail=str(exc),
            ) from exc

        actual = self.get_project_settings(project)
        mismatches = _setting_mismatches(preset.expected_settings, actual)
        if mismatches:
            details = "; ".join(mismatches)
            raise ResolveOperationError(
                "DaVinci Resolve did not apply the requested project settings. "
                f"Mismatched settings: {details}. The project was left open in "
                "Resolve for inspection; no silent fallback was used.",
                stage="verify_settings",
                detail=f"SetSettings returned {applied!r}. Actual: {actual!r}",
            )
        if not applied:
            _log.warning(
                "SetSettings reported a failure, but all requested settings verified correctly"
            )

        warnings: list[str] = []
        playback = actual.get("timelinePlaybackFrameRate")
        if playback not in (None, ""):
            try:
                if abs(float(playback) - float(preset.fps)) > 0.01:
                    warnings.append(
                        f"Resolve reports playback frame rate {playback}; "
                        f"the requested value was {preset.fps}."
                    )
            except (TypeError, ValueError):
                warnings.append(
                    f"Resolve reports an unreadable playback frame rate: {playback!r}."
                )
        return warnings

    def create_timeline(self, project: Any, name: str) -> Any:
        try:
            media_pool = project.GetMediaPool()
        except Exception as exc:
            raise ResolveOperationError(
                "Could not open the Media Pool.",
                stage="create_timeline",
                detail=str(exc),
            ) from exc
        if media_pool is None:
            raise ResolveOperationError(
                "Could not open the Media Pool.", stage="create_timeline"
            )
        try:
            timeline = media_pool.CreateEmptyTimeline(name)
        except Exception as exc:
            raise ResolveOperationError(
                f"DaVinci Resolve could not create the timeline '{name}'.",
                stage="create_timeline",
                detail=str(exc),
            ) from exc
        if timeline is None:
            raise ResolveOperationError(
                f"DaVinci Resolve could not create the timeline '{name}'.",
                stage="create_timeline",
            )
        try:
            actual_name = timeline.GetName()
            timeline_count = project.GetTimelineCount()
        except Exception as exc:
            raise ResolveOperationError(
                f"Could not verify the timeline '{name}'.",
                stage="verify_timeline",
                detail=str(exc),
            ) from exc
        if actual_name != name or timeline_count < 1:
            raise ResolveOperationError(
                f"The created timeline did not verify as '{name}'.",
                stage="verify_timeline",
                detail=f"name={actual_name!r}, count={timeline_count!r}",
            )
        _log.info("Created timeline %r", name)
        return timeline

    def create_bins(self, project: Any, names: tuple[str, ...]) -> list[str]:
        warnings: list[str] = []
        try:
            media_pool = project.GetMediaPool()
            root = media_pool.GetRootFolder() if media_pool is not None else None
        except Exception as exc:
            return [f"Media Pool bins were not created: {exc}"]
        if media_pool is None or root is None:
            return ["Media Pool bins were not created: the Media Pool root is unavailable."]

        for name in names:
            try:
                existing = {folder.GetName() for folder in (root.GetSubFolderList() or [])}
            except Exception:
                existing = set()
            if name in existing:
                continue
            try:
                folder = media_pool.AddSubFolder(root, name)
            except Exception as exc:
                warnings.append(f"Could not create the Media Pool bin '{name}': {exc}")
                continue
            if folder is None:
                warnings.append(f"Could not create the Media Pool bin '{name}'.")

        try:
            actual = {folder.GetName() for folder in (root.GetSubFolderList() or [])}
        except Exception:
            actual = set()
        missing = [name for name in names if name not in actual]
        if missing:
            warnings.append(
                "Some Media Pool bins could not be verified: " + ", ".join(missing)
            )
        return warnings

    def save_project(self, project: Any, expected_name: str) -> None:
        try:
            saved = self._pm().SaveProject()
        except Exception as exc:
            raise ResolveOperationError(
                f"DaVinci Resolve could not save the project '{expected_name}'.",
                stage="save_project",
                detail=str(exc),
            ) from exc
        if saved is False:
            raise ResolveOperationError(
                f"DaVinci Resolve could not save the project '{expected_name}'.",
                stage="save_project",
            )
        if saved is None:
            _log.warning(
                "SaveProject returned no result for %r; verifying the open project instead",
                expected_name,
            )
        current = self._pm().GetCurrentProject()
        if current is None:
            raise ResolveOperationError(
                "The project disappeared after saving.", stage="verify_save"
            )
        try:
            current_name = current.GetName()
        except Exception as exc:
            raise ResolveOperationError(
                "Could not verify the saved project.",
                stage="verify_save",
                detail=str(exc),
            ) from exc
        if current_name != expected_name:
            raise ResolveOperationError(
                "The active project changed while saving.",
                stage="verify_save",
                detail=f"expected {expected_name!r}, got {current_name!r}",
            )
        _log.info("Saved and verified Resolve project %r", expected_name)

    def get_project_id(self, project: Any) -> str | None:
        getter = getattr(project, "GetUniqueId", None)
        if not callable(getter):
            return None
        try:
            value = getter()
        except Exception as exc:
            _log.warning("Could not read the Resolve project ID: %s", exc)
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


def _setting_mismatches(
    expected: dict[str, str | float], actual: dict[str, Any]
) -> list[str]:
    mismatches: list[str] = []
    for key, wanted in expected.items():
        if key not in actual:
            mismatches.append(f"{key} is missing (wanted {wanted!r})")
            continue
        value = actual[key]
        if key in _SIZE_KEYS:
            try:
                matches = int(float(value)) == int(float(wanted))
            except (TypeError, ValueError):
                matches = False
        elif key == "timelineFrameRate":
            try:
                matches = abs(float(value) - float(wanted)) < 0.001
            except (TypeError, ValueError):
                matches = False
        else:
            matches = str(value).strip() == str(wanted).strip()
        if not matches:
            mismatches.append(f"{key} is {value!r} (wanted {wanted!r})")
    return mismatches
