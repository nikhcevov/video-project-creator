import json
from datetime import datetime, timedelta, timezone

import pytest

from fakes import FakeProject, FakeResolve, UnavailableResolve
from video_project_creator.errors import (
    ConcurrentCreationError,
    DirectoryConflictError,
    NameConflictError,
    PartialCreationError,
    ResolveOperationError,
    ResolveUnavailable,
    ValidationError,
)
from video_project_creator.filesystem import CreationLock
from video_project_creator.project_service import ProjectService
from video_project_creator.resolve_api import ResolveAdapter

FIXED_NOW = datetime(2026, 10, 19, 19, 30, tzinfo=timezone(timedelta(hours=4)))


@pytest.fixture
def env(tmp_path):
    fake = FakeResolve()
    projects = tmp_path / "Videos" / "Projects"
    state = tmp_path / "state"

    def factory():
        return ResolveAdapter(resolve=fake)

    service = ProjectService(
        adapter_factory=factory,
        projects_root=projects,
        state_root=state,
        now=lambda: FIXED_NOW,
    )
    return service, fake, projects, state


def test_happy_path_creates_project_and_metadata(env):
    service, fake, projects, _state = env

    result = service.create("Morning Matcha", "reels")

    final = projects / "2026-10-19-Morning-Matcha"
    assert result.project_dir == final
    assert (final / "Assets").is_dir()
    assert (final / "Exports").is_dir()
    assert not list(projects.glob(".creating-*"))
    assert not list(final.glob(".*.tmp-*"))

    metadata = json.loads((final / ".project.json").read_text(encoding="utf-8"))
    assert metadata == {
        "schema_version": 1,
        "project_name": "Morning Matcha",
        "resolve_project_name": "Morning Matcha",
        "resolve_project_id": "unique-id",
        "resolve_library": {
            "db_type": "Disk",
            "db_name": "Local Database",
            "folder": "Master",
        },
        "preset": "reels",
        "created_at": "2026-10-19T19:30:00+04:00",
        "status": "active",
    }

    project = fake.pm.projects["Morning Matcha"]
    assert fake.pm.current is project
    assert project.GetSettings()["timelineResolutionWidth"] == "1080"
    assert project.GetSettings()["timelineResolutionHeight"] == "1920"
    assert [timeline.GetName() for timeline in project.timelines] == ["Main"]
    bins = {
        folder.GetName()
        for folder in project.GetMediaPool().GetRootFolder().GetSubFolderList()
    }
    assert bins == {"Camera Footage", "Music", "Graphics"}
    assert result.warnings == ()
    assert result.resolve_version == "21.1.1"


def test_youtube_preset_is_applied(env):
    service, fake, projects, _state = env
    result = service.create("Autumn Vlog", "youtube")

    project = fake.pm.projects["Autumn Vlog"]
    assert project.GetSettings()["timelineResolutionWidth"] == "3840"
    assert project.GetSettings()["timelineResolutionHeight"] == "2160"
    assert (projects / "2026-10-19-Autumn-Vlog").is_dir()
    assert result.metadata["preset"] == "youtube"


def test_existing_project_is_saved_first(env):
    service, fake, projects, _state = env
    old = FakeProject("Old Project")
    fake.pm.projects["Old Project"] = old
    fake.pm.current = old

    service.create("Morning Matcha", "reels")

    assert fake.pm.save_calls >= 2
    assert fake.pm.current.name == "Morning Matcha"
    assert (projects / "2026-10-19-Morning-Matcha").is_dir()


def test_unavailable_resolve_creates_nothing(tmp_path):
    projects = tmp_path / "Videos" / "Projects"
    service = ProjectService(
        adapter_factory=lambda: ResolveAdapter(resolve=UnavailableResolve()),
        projects_root=projects,
        state_root=tmp_path / "state",
        now=lambda: FIXED_NOW,
    )

    with pytest.raises(ResolveUnavailable):
        service.create("Morning Matcha", "reels")

    assert not projects.exists()


def test_existing_project_save_failure_creates_nothing(env):
    service, fake, projects, _state = env
    old = FakeProject("Old Project")
    fake.pm.projects["Old Project"] = old
    fake.pm.current = old
    fake.pm.fail_save_always = True

    with pytest.raises(ResolveOperationError, match="Could not save"):
        service.create("Morning Matcha", "reels")

    assert fake.pm.create_calls == 0
    assert not projects.exists()


def test_resolve_name_conflict_is_rejected(env):
    service, fake, projects, _state = env
    fake.pm.projects["Morning Matcha"] = FakeProject("Morning Matcha")

    with pytest.raises(NameConflictError):
        service.create("Morning Matcha", "reels")

    assert fake.pm.create_calls == 0
    assert not projects.exists()


def test_directory_conflict_is_rejected_without_touching_resolve(env):
    service, fake, projects, _state = env
    existing = projects / "2026-10-19-Morning-Matcha"
    existing.mkdir(parents=True)

    with pytest.raises(DirectoryConflictError):
        service.create("Morning Matcha", "reels")

    assert fake.pm.create_calls == 0
    assert list(existing.iterdir()) == []


def test_create_project_failure_cleans_staging(env):
    service, fake, projects, state = env
    fake.pm.fail_create = True

    with pytest.raises(ResolveOperationError, match="did not create"):
        service.create("Morning Matcha", "reels")

    assert fake.pm.projects == {}
    assert not (projects / "2026-10-19-Morning-Matcha").exists()
    assert not list(projects.glob(".creating-*"))
    assert not (state / "recovery").exists()


def test_settings_verification_failure_records_partial_result(env):
    service, fake, projects, state = env
    fake.ignore_settings = {"timelineResolutionWidth"}
    final = projects / "2026-10-19-Morning-Matcha"

    with pytest.raises(PartialCreationError) as caught:
        service.create("Morning Matcha", "reels")

    error = caught.value
    assert error.project_name == "Morning Matcha"
    assert error.resolve_project_id == "unique-id"
    assert error.stage == "verify_settings"
    assert "Morning Matcha" in fake.pm.projects
    assert not final.exists()
    assert list(projects.glob(".creating-*"))

    recovery_files = list((state / "recovery").glob("*.json"))
    assert len(recovery_files) == 1
    recovery = json.loads(recovery_files[0].read_text(encoding="utf-8"))
    assert recovery["status"] == "partial"
    assert recovery["stage"] == "verify_settings"
    assert recovery["project_name"] == "Morning Matcha"


def test_timeline_failure_records_partial_result(env):
    service, fake, projects, state = env
    fake.fail_timeline = True

    with pytest.raises(PartialCreationError) as caught:
        service.create("Morning Matcha", "reels")

    assert caught.value.stage == "create_timeline"
    assert not (projects / "2026-10-19-Morning-Matcha").exists()
    assert list((state / "recovery").glob("*.json"))


def test_save_failure_records_partial_result(env):
    service, fake, projects, state = env
    fake.pm.save_fail_for = "Morning Matcha"

    with pytest.raises(PartialCreationError) as caught:
        service.create("Morning Matcha", "reels")

    assert caught.value.stage == "save_project"
    assert "Morning Matcha" in fake.pm.projects
    assert not (projects / "2026-10-19-Morning-Matcha").exists()
    assert list((state / "recovery").glob("*.json"))


def test_bin_creation_failure_does_not_block_creation(env):
    service, fake, projects, _state = env
    fake.fail_bins = True

    result = service.create("Morning Matcha", "reels")

    assert (projects / "2026-10-19-Morning-Matcha").is_dir()
    assert result.warnings
    assert any("Media Pool bins" in warning for warning in result.warnings)


def test_second_creation_is_locked_out(env):
    service, fake, projects, state = env
    with CreationLock(state / "creation.lock"):
        with pytest.raises(ConcurrentCreationError):
            service.create("Morning Matcha", "reels")

    assert fake.pm.create_calls == 0
    assert not projects.exists()


def test_invalid_name_fails_before_connecting(tmp_path):
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        raise AssertionError("must not connect")

    service = ProjectService(
        adapter_factory=factory,
        projects_root=tmp_path / "Projects",
        state_root=tmp_path / "state",
        now=lambda: FIXED_NOW,
    )
    with pytest.raises(ValidationError):
        service.create("   ", "reels")
    assert calls == 0


def test_unknown_preset_fails_before_connecting(tmp_path):
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        raise AssertionError("must not connect")

    service = ProjectService(
        adapter_factory=factory,
        projects_root=tmp_path / "Projects",
        state_root=tmp_path / "state",
        now=lambda: FIXED_NOW,
    )
    with pytest.raises(ValidationError):
        service.create("Morning Matcha", "square")
    assert calls == 0


def test_unicode_name_preserves_display_name(env):
    service, fake, projects, _state = env

    service.create("Café ☕", "reels")

    final = projects / "2026-10-19-Café"
    metadata = json.loads((final / ".project.json").read_text(encoding="utf-8"))
    assert metadata["project_name"] == "Café ☕"
    assert "Café ☕" in fake.pm.projects


def test_existing_resolve_project_is_not_reopened(env):
    service, fake, _projects, _state = env
    existing = FakeProject("Morning Matcha")
    fake.pm.projects["Morning Matcha"] = existing
    fake.pm.current = None

    with pytest.raises(NameConflictError):
        service.create("Morning Matcha", "reels")

    assert fake.pm.current is None
    assert fake.pm.create_calls == 0


def test_project_id_is_null_when_resolve_does_not_expose_one(env):
    service, fake, projects, _state = env
    fake.unique_id = None

    service.create("Morning Matcha", "reels")

    metadata = json.loads(
        (projects / "2026-10-19-Morning-Matcha" / ".project.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["resolve_project_id"] is None
