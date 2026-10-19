"""In-memory doubles for the Resolve scripting API."""

from __future__ import annotations

from typing import Any


class FakeTimeline:
    def __init__(self, name: str) -> None:
        self.name = name

    def GetName(self) -> str:
        return self.name


class FakeFolder:
    def __init__(self, name: str) -> None:
        self.name = name
        self.subfolders: list[FakeFolder] = []

    def GetName(self) -> str:
        return self.name

    def GetSubFolderList(self) -> list[FakeFolder]:
        return list(self.subfolders)


class FakeMediaPool:
    def __init__(self, project: "FakeProject") -> None:
        self.project = project
        self.root = FakeFolder("Master")
        self.fail_timeline = False
        self.fail_bins = False
        self.added_bins: list[str] = []

    def GetRootFolder(self) -> FakeFolder:
        return self.root

    def AddSubFolder(self, parent: FakeFolder, name: str) -> FakeFolder | None:
        if self.fail_bins:
            return None
        folder = FakeFolder(name)
        parent.subfolders.append(folder)
        self.added_bins.append(name)
        return folder

    def CreateEmptyTimeline(self, name: str) -> FakeTimeline | None:
        if self.fail_timeline:
            return None
        timeline = FakeTimeline(name)
        self.project.timelines.append(timeline)
        return timeline


class FakeProject:
    def __init__(self, name: str, unique_id: str | None = "unique-id") -> None:
        self.name = name
        self.unique_id = unique_id
        self.settings: dict[str, Any] = {
            "timelineResolutionWidth": "1920",
            "timelineResolutionHeight": "1080",
            "timelinePixelAspectRatio": "square",
            "timelineFrameRate": 30.0,
            "timelinePlaybackFrameRate": "30",
            "colorScienceMode": "davinciYRGB",
            "isAutoColorManage": "0",
            "rcmPresetMode": "Custom",
            "colorSpaceTimeline": "Rec.709 (Scene)",
            "colorSpaceTimelineGamma": "",
            "separateColorSpaceAndGamma": "0",
        }
        self.ignore_settings: set[str] = set()
        self.timelines: list[FakeTimeline] = []
        self.media_pool = FakeMediaPool(self)

    def GetName(self) -> str:
        return self.name

    def GetUniqueId(self) -> str | None:
        return self.unique_id

    def GetSettings(self) -> dict[str, Any]:
        return dict(self.settings)

    def SetSettings(self, settings: dict[str, Any]) -> bool:
        rejected = False
        for key, value in settings.items():
            if key in self.ignore_settings:
                rejected = True
                continue
            self.settings[key] = float(value) if key == "timelineFrameRate" else value
        return not rejected

    def GetMediaPool(self) -> FakeMediaPool:
        return self.media_pool

    def GetTimelineCount(self) -> int:
        return len(self.timelines)


class FakeProjectManager:
    def __init__(self, resolve: "FakeResolve") -> None:
        self.resolve = resolve
        self.projects: dict[str, FakeProject] = {}
        self.current: FakeProject | None = None
        self.current_folder = "Master"
        self.database: dict[str, Any] = {
            "DbType": "Disk",
            "DbName": "Local Database",
        }
        self.save_calls = 0
        self.fail_save_always = False
        self.save_returns_none = False
        self.save_fail_for: str | None = None
        self.create_calls = 0
        self.fail_create = False

    def GetCurrentProject(self) -> FakeProject | None:
        return self.current

    def SaveProject(self) -> bool:
        self.save_calls += 1
        if self.fail_save_always:
            return False
        if self.save_returns_none:
            return None
        if (
            self.save_fail_for is not None
            and self.current is not None
            and self.current.name == self.save_fail_for
        ):
            return False
        return True

    def GetProjectListInCurrentFolder(self) -> list[str]:
        return list(self.projects)

    def GetCurrentDatabase(self) -> dict[str, Any]:
        return dict(self.database)

    def GetCurrentFolder(self) -> str:
        return self.current_folder

    def CreateProject(self, name: str) -> FakeProject | None:
        self.create_calls += 1
        if self.fail_create or name in self.projects:
            return None
        project = self.resolve.make_project(name)
        self.projects[name] = project
        self.current = project
        return project


class FakeResolve:
    def __init__(self) -> None:
        self.pm = FakeProjectManager(self)
        self.ignore_settings: set[str] = set()
        self.fail_timeline = False
        self.fail_bins = False
        self.unique_id: str | None = "unique-id"
        self.version = "21.1.1"
        self.studio = True

    def make_project(self, name: str) -> FakeProject:
        project = FakeProject(name, unique_id=self.unique_id)
        project.ignore_settings = set(self.ignore_settings)
        project.media_pool.fail_timeline = self.fail_timeline
        project.media_pool.fail_bins = self.fail_bins
        return project

    def GetProjectManager(self) -> FakeProjectManager:
        return self.pm

    def GetCurrentProject(self) -> FakeProject | None:
        return self.pm.current

    def GetVersionString(self) -> str:
        return self.version

    def IsStudio(self) -> bool:
        return self.studio


class UnavailableResolve:
    def GetProjectManager(self) -> None:
        return None

    def IsStudio(self) -> bool:
        return True


class FakeModule:
    def __init__(self, resolve: FakeResolve | None) -> None:
        self.resolve = resolve

    def scriptapp(self, _name: str) -> FakeResolve | None:
        return self.resolve
