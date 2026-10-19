import pytest

from fakes import FakeModule, FakeProject, FakeResolve, UnavailableResolve
from video_project_creator.errors import (
    NameConflictError,
    ResolveOperationError,
    ResolveUnavailable,
)
from video_project_creator.presets import get_preset
from video_project_creator.resolve_api import ResolveAdapter


def make_adapter(resolve=None, module=None):
    loader = (lambda: module) if module is not None else None
    return ResolveAdapter(resolve=resolve, module_loader=loader)


def test_connect_uses_running_resolve():
    fake = FakeResolve()
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    assert adapter.get_version() == "21.1.1"


def test_connect_fails_when_scriptapp_returns_none():
    adapter = make_adapter(module=FakeModule(None))
    with pytest.raises(ResolveUnavailable, match="not running"):
        adapter.connect()


def test_connect_fails_without_project_manager():
    adapter = make_adapter(resolve=UnavailableResolve())
    with pytest.raises(ResolveUnavailable, match="still starting"):
        adapter.connect()


def test_connect_rejects_free_resolve():
    fake = FakeResolve()
    fake.studio = False
    adapter = make_adapter(resolve=fake)
    with pytest.raises(ResolveUnavailable, match="Studio"):
        adapter.connect()


def test_name_conflict_is_case_insensitive():
    fake = FakeResolve()
    fake.pm.projects["Morning Matcha"] = FakeProject("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    with pytest.raises(NameConflictError):
        adapter.ensure_name_available("morning matcha")


def test_apply_preset_sets_and_verifies_settings():
    fake = FakeResolve()
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    warnings = adapter.apply_preset(project, get_preset("reels"))
    assert warnings == []
    settings = project.GetSettings()
    assert settings["timelineResolutionWidth"] == "1080"
    assert settings["timelineResolutionHeight"] == "1920"
    assert settings["timelineFrameRate"] == 30.0
    assert settings["colorScienceMode"] == "davinciYRGB"
    assert settings["isAutoColorManage"] == "0"
    assert settings["colorSpaceTimeline"] == "Rec.709 (Scene)"
    assert settings["colorSpaceTimelineGamma"] == ""


def test_apply_preset_reports_mismatch_without_fallback():
    fake = FakeResolve()
    fake.ignore_settings = {"timelineResolutionWidth"}
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    with pytest.raises(ResolveOperationError, match="did not apply"):
        adapter.apply_preset(project, get_preset("reels"))


def test_apply_preset_warns_when_playback_rate_differs():
    fake = FakeResolve()
    project = fake.make_project("Morning Matcha")
    project.settings["timelinePlaybackFrameRate"] = "24"
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    warnings = adapter.apply_preset(project, get_preset("reels"))
    assert len(warnings) == 1
    assert "playback frame rate" in warnings[0]


def test_create_timeline_verifies_name_and_count():
    fake = FakeResolve()
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    timeline = adapter.create_timeline(project, "Main")
    assert timeline.GetName() == "Main"
    assert project.GetTimelineCount() == 1


def test_create_timeline_failure_raises():
    fake = FakeResolve()
    fake.fail_timeline = True
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    with pytest.raises(ResolveOperationError, match="could not create the timeline"):
        adapter.create_timeline(project, "Main")


def test_create_bins_creates_and_verifies():
    fake = FakeResolve()
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    warnings = adapter.create_bins(project, ("Camera Footage", "Music", "Graphics"))
    assert warnings == []
    root = project.GetMediaPool().GetRootFolder()
    assert {folder.GetName() for folder in root.GetSubFolderList()} == {
        "Camera Footage",
        "Music",
        "Graphics",
    }


def test_create_bins_warns_instead_of_blocking():
    fake = FakeResolve()
    fake.fail_bins = True
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    warnings = adapter.create_bins(project, ("Camera Footage",))
    assert warnings
    assert "Could not create" in warnings[0]


def test_project_id_is_read_or_omitted():
    fake = FakeResolve()
    project = fake.make_project("Morning Matcha")
    adapter = make_adapter(resolve=fake)
    assert adapter.get_project_id(project) == "unique-id"

    project.unique_id = None
    assert adapter.get_project_id(project) is None

    class NoId:
        pass

    assert adapter.get_project_id(NoId()) is None


def test_existing_project_is_saved_before_creation():
    fake = FakeResolve()
    existing = FakeProject("Old Project")
    fake.pm.projects["Old Project"] = existing
    fake.pm.current = existing
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    adapter.ensure_current_project_saved()
    assert fake.pm.save_calls == 1


def test_none_save_result_is_treated_as_no_pending_changes():
    fake = FakeResolve()
    existing = FakeProject("Old Project")
    fake.pm.projects["Old Project"] = existing
    fake.pm.current = existing
    fake.pm.save_returns_none = True
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    adapter.ensure_current_project_saved()
    adapter.save_project(existing, "Old Project")


def test_existing_project_save_failure_stops():
    fake = FakeResolve()
    existing = FakeProject("Old Project")
    fake.pm.projects["Old Project"] = existing
    fake.pm.current = existing
    fake.pm.fail_save_always = True
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    with pytest.raises(ResolveOperationError, match="Could not save"):
        adapter.ensure_current_project_saved()


def test_save_detects_changed_current_project():
    fake = FakeResolve()
    project = fake.make_project("Morning Matcha")
    fake.pm.current = project
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    fake.pm.current = FakeProject("Other Project")
    with pytest.raises(ResolveOperationError, match="active project changed"):
        adapter.save_project(project, "Morning Matcha")


def test_library_identity_is_preserved():
    fake = FakeResolve()
    adapter = make_adapter(resolve=fake)
    adapter.connect()
    assert adapter.get_library_identity() == {
        "db_type": "Disk",
        "db_name": "Local Database",
        "folder": "Master",
    }
