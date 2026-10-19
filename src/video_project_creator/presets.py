"""Declarative DaVinci Resolve project presets."""

from __future__ import annotations

from dataclasses import dataclass

REC709_SCENE = "Rec.709 (Scene)"


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    width: int
    height: int
    fps: int
    timeline_name: str
    orientation: str

    @property
    def description(self) -> str:
        return f"{self.orientation} · {self.width} × {self.height}"

    def resolve_settings(self) -> dict[str, str]:
        """Settings applied through Project.SetSettings()."""
        return {
            "timelineResolutionWidth": str(self.width),
            "timelineResolutionHeight": str(self.height),
            "timelinePixelAspectRatio": "square",
            "timelineFrameRate": str(self.fps),
            "colorScienceMode": "davinciYRGB",
            "isAutoColorManage": "0",
            "rcmPresetMode": "Custom",
            "colorSpaceTimeline": REC709_SCENE,
        }

    @property
    def expected_settings(self) -> dict[str, str | float]:
        """Settings that must be present after applying the preset."""
        expected: dict[str, str | float] = dict(self.resolve_settings())
        expected["timelineFrameRate"] = float(self.fps)
        expected["colorSpaceTimelineGamma"] = ""
        expected["separateColorSpaceAndGamma"] = "0"
        return expected


PRESETS: dict[str, Preset] = {
    "reels": Preset(
        id="reels",
        label="Reels / Shorts",
        width=1080,
        height=1920,
        fps=30,
        timeline_name="Main",
        orientation="Vertical",
    ),
    "youtube": Preset(
        id="youtube",
        label="YouTube",
        width=3840,
        height=2160,
        fps=30,
        timeline_name="Main",
        orientation="Horizontal",
    ),
}

DEFAULT_PRESET_ID = "reels"
KNOWN_PRESET_IDS = frozenset(PRESETS)


def get_preset(preset_id: str) -> Preset:
    try:
        return PRESETS[preset_id]
    except KeyError:
        raise ValueError(f"Unknown video format: {preset_id!r}") from None
