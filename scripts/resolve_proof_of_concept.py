#!/usr/bin/env python3
"""Inspect a live Resolve installation and optionally create a disposable project.

This is the Phase 2 proof-of-concept utility. It never deletes anything.

Read-only:
    python3 scripts/resolve_proof_of_concept.py

Create a disposable project (requires explicit authorization):
    python3 scripts/resolve_proof_of_concept.py --create --preset reels
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_project_creator.presets import get_preset  # noqa: E402
from video_project_creator.resolve_api import ResolveAdapter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--preset", choices=("reels", "youtube"), default="reels")
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    adapter = ResolveAdapter()
    adapter.connect()

    print(f"version: {adapter.get_version()}")
    print(f"library: {adapter.get_library_identity()}")
    current = adapter.get_current_project()
    print(f"current project: {current.GetName() if current is not None else None}")

    if not args.create:
        print("read-only inspection complete")
        return 0

    name = args.name or f"VPC Test {datetime.now():%Y%m%d-%H%M%S}"
    preset = get_preset(args.preset)
    adapter.ensure_current_project_saved()
    adapter.ensure_name_available(name)
    print(f"creating: {name} ({preset.id})")
    project = adapter.create_project(name)
    print(f"project id: {adapter.get_project_id(project)}")
    print(f"settings warnings: {adapter.apply_preset(project, preset)}")
    timeline = adapter.create_timeline(project, preset.timeline_name)
    print(f"timeline: {timeline.GetName()}")
    print(f"bins warnings: {adapter.create_bins(project, ('Camera Footage', 'Music', 'Graphics'))}")
    adapter.save_project(project, name)
    print(f"settings: {project.GetSettings()}")
    print("project left open in Resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
