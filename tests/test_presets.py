import pytest

from video_project_creator.presets import PRESETS, get_preset


def test_reels_profile():
    preset = PRESETS["reels"]
    assert (preset.width, preset.height) == (1080, 1920)
    assert preset.fps == 30
    assert preset.timeline_name == "Main"
    assert preset.resolve_settings() == {
        "timelineResolutionWidth": "1080",
        "timelineResolutionHeight": "1920",
        "timelinePixelAspectRatio": "square",
        "timelineFrameRate": "30",
        "colorScienceMode": "davinciYRGB",
        "isAutoColorManage": "0",
        "rcmPresetMode": "Custom",
        "colorSpaceTimeline": "Rec.709 (Scene)",
    }
    assert preset.expected_settings["timelineFrameRate"] == 30.0
    assert preset.expected_settings["colorSpaceTimelineGamma"] == ""
    assert preset.expected_settings["separateColorSpaceAndGamma"] == "0"


def test_youtube_profile():
    preset = PRESETS["youtube"]
    assert (preset.width, preset.height) == (3840, 2160)
    assert preset.fps == 30
    assert preset.timeline_name == "Main"
    assert preset.resolve_settings()["timelineResolutionWidth"] == "3840"
    assert preset.resolve_settings()["timelineResolutionHeight"] == "2160"


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="Unknown video format"):
        get_preset("square")
