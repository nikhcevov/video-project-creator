#!/usr/bin/env bash
set -euo pipefail

DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
STATE_HOME=${XDG_STATE_HOME:-"$HOME/.local/state"}
CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}

rm -rf "$DATA_HOME/video-project-creator"
rm -f "$HOME/.local/bin/video-project-creator"
rm -f "$DATA_HOME/applications/video-project-creator.desktop"

if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR=$(xdg-user-dir DESKTOP)
else
    DESKTOP_DIR="$HOME/Desktop"
fi
if [ -n "$DESKTOP_DIR" ]; then
    rm -f "$DESKTOP_DIR/New Video Project.desktop"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
fi

rm -rf "$STATE_HOME/video-project-creator"
rm -rf "$CONFIG_HOME/video-project-creator"

printf 'Video Project Creator was uninstalled.\n'
printf 'Your footage, project folders and DaVinci Resolve Project Library were not touched.\n'
