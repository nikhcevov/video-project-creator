#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR="$SCRIPT_DIR/src/video_project_creator"

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

note() {
    printf '%s\n' "$*"
}

[ -d "$SOURCE_DIR" ] || die "run this script from the repository root"

PYTHON_BIN=${PYTHON:-$(command -v python3 || true)}
[ -n "$PYTHON_BIN" ] || die "python3 was not found"

"$PYTHON_BIN" - <<'PY' || die "Python 3.11 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

"$PYTHON_BIN" - <<'PY' || die "PySide6 is missing (install it with: sudo pacman -S pyside6)"
import PySide6
PY

if [ ! -f /opt/resolve/Developer/Scripting/Modules/DaVinciResolveScript.py ]; then
    note "warning: the DaVinci Resolve scripting module was not found at the default path."
    note "         Install DaVinci Resolve Studio, or set RESOLVE_SCRIPT_API for your installation."
fi

DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
APP_HOME="$DATA_HOME/video-project-creator"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="$DATA_HOME/applications"
WRAPPER="$BIN_DIR/video-project-creator"

mkdir -p "$APP_HOME" "$BIN_DIR" "$APPLICATIONS_DIR"

rm -rf "$APP_HOME/video_project_creator"
cp -a "$SOURCE_DIR" "$APP_HOME/"
find "$APP_HOME/video_project_creator" -type d -name __pycache__ -prune -exec rm -rf {} +

{
    printf '#!/bin/sh\n'
    printf 'export PYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}"\n' "$APP_HOME"
    printf 'exec "%s" -m video_project_creator "$@"\n' "$PYTHON_BIN"
} > "$WRAPPER"
chmod +x "$WRAPPER"

PYTHONPATH="$APP_HOME" "$PYTHON_BIN" -c 'import video_project_creator.app' \
    || die "the installed application failed to import"

DESKTOP_FILE="$APPLICATIONS_DIR/video-project-creator.desktop"
sed "s#@EXEC@#$WRAPPER#g" "$SCRIPT_DIR/resources/video-project-creator.desktop" > "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR=$(xdg-user-dir DESKTOP)
else
    DESKTOP_DIR="$HOME/Desktop"
fi
if [ -n "$DESKTOP_DIR" ]; then
    mkdir -p "$DESKTOP_DIR"
    SHORTCUT="$DESKTOP_DIR/New Video Project.desktop"
    cp "$DESKTOP_FILE" "$SHORTCUT"
    chmod +x "$SHORTCUT"
    if command -v gio >/dev/null 2>&1; then
        gio set "$SHORTCUT" metadata::trusted true >/dev/null 2>&1 || true
    fi
fi

note "Installed Video Project Creator."
note "Launcher: $WRAPPER"
note "Menu entry: $DESKTOP_FILE"
if [ -n "${SHORTCUT:-}" ]; then
    note "Desktop shortcut: $SHORTCUT"
fi
note ""
note "Before first use, start DaVinci Resolve Studio and set:"
note "  Preferences -> System -> General -> External scripting using -> Local"
note "  Preferences -> System -> General -> Automatic scripted actions -> Allow all"
