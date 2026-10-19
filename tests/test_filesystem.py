import json
from datetime import date

import pytest

from video_project_creator import config
from video_project_creator.config import AppConfig, load_config
from video_project_creator.errors import (
    ConcurrentCreationError,
    DirectoryConflictError,
    ValidationError,
)
from video_project_creator.filesystem import (
    CreationLock,
    create_staging_directory,
    project_directory_name,
    publish_project,
    remove_staging_if_empty,
    slugify,
    validate_project_name,
    write_json_atomic,
)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "\t\n", "/", "a/b", "a\\b", "a\x00b", "a\nb", ".", "..", "x" * 121],
)
def test_invalid_names_are_rejected(raw):
    with pytest.raises(ValidationError):
        validate_project_name(raw)


def test_name_is_trimmed_and_unicode_is_preserved():
    assert validate_project_name("  Morning Matcha  ") == "Morning Matcha"
    assert validate_project_name("Café ☕") == "Café ☕"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Morning Matcha", "Morning-Matcha"),
        ("  Morning   Matcha  ", "Morning-Matcha"),
        ("Café ☕", "Café"),
        ("A/B", "A-B"),
        ("...", ""),
        ("hello_world.v2", "hello_world.v2"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_slug_is_byte_limited():
    slug = slugify("é" * 300)
    assert len(slug.encode("utf-8")) <= 200
    assert slug


def test_project_directory_name_is_date_prefixed():
    assert (
        project_directory_name("Morning Matcha", date(2026, 10, 19))
        == "2026-10-19-Morning-Matcha"
    )


def test_staging_and_publish(tmp_path):
    root = tmp_path / "Projects"
    staging = create_staging_directory(root)
    assert staging.parent == root
    assert (staging / "Assets").is_dir()
    assert (staging / "Exports").is_dir()

    final = root / "2026-10-19-Morning-Matcha"
    publish_project(staging, final)
    assert final.is_dir()
    assert not staging.exists()


def test_publish_never_overwrites(tmp_path):
    root = tmp_path / "Projects"
    staging = create_staging_directory(root)
    (staging / "Assets" / "keep.txt").write_text("asset", encoding="utf-8")
    final = root / "existing"
    final.mkdir()

    with pytest.raises(DirectoryConflictError):
        publish_project(staging, final)

    assert final.is_dir()
    assert list(final.iterdir()) == []
    assert (staging / "Assets" / "keep.txt").is_file()


def test_json_is_written_atomically_and_replaced(tmp_path):
    target = tmp_path / "meta" / ".project.json"
    write_json_atomic(target, {"name": "Café", "version": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "name": "Café",
        "version": 1,
    }
    write_json_atomic(target, {"name": "New", "version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "name": "New",
        "version": 2,
    }
    assert list(target.parent.iterdir()) == [target]


def test_remove_staging_only_when_empty(tmp_path):
    empty = tmp_path / "empty"
    (empty / "Assets").mkdir(parents=True)
    (empty / "Exports").mkdir()
    remove_staging_if_empty(empty)
    assert not empty.exists()

    with_file = tmp_path / "with-file"
    (with_file / "Assets").mkdir(parents=True)
    (with_file / "Assets" / "asset.txt").write_text("x", encoding="utf-8")
    remove_staging_if_empty(with_file)
    assert (with_file / "Assets" / "asset.txt").is_file()


def test_creation_lock_is_exclusive(tmp_path):
    path = tmp_path / "state" / "creation.lock"
    with CreationLock(path):
        with pytest.raises(ConcurrentCreationError):
            with CreationLock(path):
                pass

    with CreationLock(path):
        pass


def test_xdg_videos_dir_is_read_from_user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    user_dirs = tmp_path / "cfg" / "user-dirs.dirs"
    user_dirs.parent.mkdir(parents=True)
    user_dirs.write_text('XDG_VIDEOS_DIR="$HOME/My Clips"\n', encoding="utf-8")

    assert config.xdg_user_dir("VIDEOS", tmp_path / "fallback") == tmp_path / "My Clips"


def test_config_loads_valid_values(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'default_preset = "youtube"\nauto_close_on_success = false\n',
        encoding="utf-8",
    )
    assert load_config(path) == AppConfig(
        default_preset="youtube", auto_close_on_success=False
    )


@pytest.mark.parametrize(
    "text",
    [
        "not valid toml [",
        'default_preset = "unknown"',
        "default_preset = 42",
        "auto_close_on_success = \"yes\"",
    ],
)
def test_config_falls_back_on_invalid_values(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_config_missing_file_uses_defaults(tmp_path):
    assert load_config(tmp_path / "missing.toml") == AppConfig()
