# Video Project Creator

A small Linux desktop application that creates a ready-to-edit DaVinci Resolve
Studio project from a project name and one of two presets.

## What it does

1. The user launches **New Video Project** from the desktop.
2. They enter a project name and choose **Reels / Shorts** or **YouTube**.
3. The application checks the selected Resolve Project Library, saves any open
   project, and creates a new Resolve project.
4. It applies and verifies the resolution, frame rate and SDR Rec.709 color
   settings, creates an empty **Main** timeline, and creates three Media Pool
   bins.
5. It saves the Resolve project, writes `.project.json`, publishes the project
   folder, and leaves the new project open in Resolve.

The application never imports footage, copies source media, renders video, or
modifies `~/Videos/Library/`.

## Requirements

| Component | Requirement |
|---|---|
| OS | CachyOS / Arch Linux, KDE Plasma on Wayland |
| Editor | DaVinci Resolve Studio (external scripting is Studio-only) |
| Python | 3.11 or newer |
| GUI | PySide6 (system package) |
| Storage | XDG Videos directory (usually `~/Videos`) |

Install the system dependencies:

```sh
sudo pacman -S python pyside6
```

DaVinci Resolve must be running before the application starts, with:

```text
Preferences -> System -> General -> External scripting using -> Local
Preferences -> System -> General -> Automatic scripted actions -> Allow all
```

The application does not start Resolve automatically and does not enable
network scripting. **Allow safe** silently blocks project creation and saving,
even though read-only calls still work.

## Installation

From this repository:

```sh
./install.sh
```

The installer:

- verifies Python 3.11+, PySide6 and the Resolve scripting module;
- copies the application to `~/.local/share/video-project-creator/`;
- creates `~/.local/bin/video-project-creator`;
- installs a menu entry;
- creates a **New Video Project** shortcut on the KDE desktop.

No root privileges and no system Python changes are required.

To remove the application:

```sh
./uninstall.sh
```

Uninstalling never deletes `~/Videos/Library/`, `~/Videos/Projects/`,
`~/Videos/Shared/`, or the DaVinci Resolve Project Library.

## Usage

Double-click **New Video Project**, type a name, choose a format, and press
**Create Project** (or Enter). The window closes after a verified success.

If Resolve is not running or external scripting is disabled, the window stays
open with a **Retry** button. No project folder is created in that state.

## Presets

| Setting | Reels / Shorts | YouTube |
|---|---|---|
| Profile ID | `reels` | `youtube` |
| Resolution | 1080 × 1920 | 3840 × 2160 |
| Aspect ratio | 9:16 | 16:9 |
| Timeline FPS | 30 | 30 |
| Pixel aspect | Square | Square |
| Color | DaVinci YRGB, Rec.709 (Scene) | Same |
| Timeline | `Main` | `Main` |

The project frame rate and resolution are applied before the timeline is
created. Every requested setting is read back and compared. A mismatch stops
creation with an explicit error; the application never silently accepts
different settings.

On Resolve 21.1.1 the supported DaVinci YRGB values are:

```text
colorScienceMode        = davinciYRGB
isAutoColorManage       = 0
rcmPresetMode           = Custom
colorSpaceTimeline      = Rec.709 (Scene)
colorSpaceTimelineGamma = ""   (fixed by the Scene color space)
```

Resolve rejects `colorSpaceTimeline = Rec.709` and separate gamma overrides
such as `Gamma 2.4` in this mode. `Rec.709 (Scene)` is the supported SDR Rec.709
timeline space. The application verifies the actual returned strings.

`timelinePlaybackFrameRate` is read-only in the Resolve API and stayed at `24`
during live verification, although the timeline rate is `30`. The application
logs a warning but does not block project creation.

## Filesystem layout

The XDG Videos directory is resolved at runtime through the XDG user-dirs
configuration, so a translated or renamed Videos directory works.

```text
~/Videos/
├── Library/                  # owned by media importers; never modified here
│   ├── DJI/YYYY-MM-DD/
│   └── iPhone/YYYY-MM-DD/
├── Projects/                 # owned by this application and the user
│   └── 2026-10-19-Morning-Matcha/
│       ├── Assets/
│       ├── Exports/
│       └── .project.json
└── Shared/                   # referenced, never modified
    ├── Music/
    ├── SoundEffects/
    └── Graphics/
```

There is deliberately no redundant `footage/` directory under
`Library/DJI/`.

### Project naming

The visible Resolve name and `.project.json` keep the user's Unicode name after
trimming. The directory uses a deterministic slug:

```text
Morning Matcha  ->  2026-10-19-Morning-Matcha
Café ☕          ->  2026-10-19-Café
```

Slashes, backslashes and control characters are rejected. Empty names and
names that produce an empty slug are rejected. Existing directories and
existing Resolve project names are never overwritten. Name collisions are
reported; no suffix is appended silently.

Name comparison in Resolve is case-insensitive, which prevents confusing
near-duplicates in the Project Library.

### `.project.json`

```json
{
  "schema_version": 1,
  "project_name": "Morning Matcha",
  "resolve_project_name": "Morning Matcha",
  "resolve_project_id": "f0f0c0de-...",
  "resolve_library": {
    "db_type": "Disk",
    "db_name": "Local Database"
  },
  "preset": "reels",
  "created_at": "2026-10-19T19:30:00+04:00",
  "status": "active"
}
```

The file is written atomically. `resolve_project_id` comes from
`Project.GetUniqueId()`; it is `null` when the installed API does not expose an
ID. No ID is derived from the name or path. The file is bookkeeping only; the
Resolve Project Library remains the source of truth.

## Safety behavior

- The currently open Resolve project is saved before a new project is created.
  If that save fails, creation stops.
- Existing projects are never closed, deleted or reset.
- Project names are checked against the current Resolve Project Library folder
  before anything is created.
- A hidden staging directory is created next to the final project directory.
  The directory is published with `renameat2(RENAME_NOREPLACE)` so an existing
  directory cannot be overwritten, even in a race.
- A user-local `flock` prevents two application instances from creating
  projects at the same time.
- If Resolve project creation succeeds but a later step fails, the Resolve
  project is left open and untouched, a recovery record is written, and a
  second attempt with the same name is blocked by the name check.
- Only an empty staging directory is removed automatically. User files are
  never deleted.

## Resolve API notes

Verified against the installed DaVinci Resolve Studio 21.1.1 scripting API:

- The module is loaded from
  `/opt/resolve/Developer/Scripting/Modules/DaVinciResolveScript.py`.
  `RESOLVE_SCRIPT_API` can override the location.
- Connection uses `scriptapp("Resolve")`; `None` means Resolve is not running
  or external scripting is disabled.
- Project Library identity uses `ProjectManager.GetCurrentDatabase()` and
  `GetCurrentFolder()`. On the tested local library, the database reports
  `{"db_type": "Disk", "db_name": "Local Database"}`; `GetCurrentFolder()`
  returned `None` and is omitted.
- Name collisions use `GetProjectListInCurrentFolder()`.
- Projects are created with `CreateProject(name)`.
- Settings are applied with `Project.SetSettings(dict)` and verified with
  `Project.GetSettings()`.
- The empty timeline is created with
  `Project.GetMediaPool().CreateEmptyTimeline("Main")`.
- Bins are created with `MediaPool.AddSubFolder(root, name)` and verified with
  `Folder.GetSubFolderList()`.
- Saves use `ProjectManager.SaveProject()` and are followed by project-name
  verification. Resolve 21.1.1 returns `None` instead of `True` when there are
  no pending changes; only an explicit `False` is treated as a failure.
- The Resolve project ID uses `Project.GetUniqueId()`.

If the installed Resolve version cannot create Media Pool bins reliably, the
application records a warning and still completes a valid project. Bins are the
only Resolve operation with a non-blocking fallback.

## Configuration and logs

Optional configuration:

```toml
# ~/.config/video-project-creator/config.toml
default_preset = "reels"      # or "youtube"
auto_close_on_success = true
```

Invalid or missing configuration falls back to the defaults above.

Logs are written to:

```text
~/.local/state/video-project-creator/app.log
```

The log rotates at 1 MB with three backups. It records startup, connection
status, selected preset, requested name, stages, verified settings, API
failures, filesystem errors and the final outcome. It does not log directory
listings.

Set `VIDEO_PROJECT_CREATOR_DEBUG=1` to mirror logs to the terminal.

## Recovery after a partial creation

A partial failure means the Resolve project exists but the directory,
metadata, or save did not complete. Recovery records are written to:

```text
~/.local/state/video-project-creator/recovery/
```

To recover:

1. Open the named project in Resolve and inspect its timeline and settings.
2. Do not retry the same name until the existing Resolve project is renamed or
   deleted in the Project Manager.
3. If the recovery record lists an existing `staging_dir`, it contains any
   metadata that was already written; move it manually only if needed.
4. If the final project directory exists but Resolve creation failed, do not
   delete user assets from it.

## Development and tests

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The suite mocks the Resolve API and covers presets, naming, Unicode, unsafe
paths, duplicate names, directory generation, metadata, invalid configuration,
Resolve unavailable, connection failure, settings verification failure,
timeline failure, save failure, partial recovery, concurrent creation and the
main UI states.

Live integration tests are never run automatically. They require a running
Resolve Studio instance, external scripting set to **Local**, automatic
scripted actions set to **Allow all**, and explicit authorization to create a
disposable project in the selected Project Library.

### Live verification results

Validated on 2026-10-19 against DaVinci Resolve Studio 21.1.1.10 on CachyOS /
KDE Plasma / Wayland:

| Check | Result |
|---|---|
| Connect through `scriptapp("Resolve")` | Pass |
| Project Library identity | `{"db_type": "Disk", "db_name": "Local Database"}` |
| Reels project creation | Pass: 1080 × 1920, 30 fps |
| YouTube project settings | Pass: 3840 × 2160, 30 fps |
| DaVinci YRGB color workflow | Pass: `Rec.709 (Scene)` |
| Empty `Main` timeline | Pass |
| Media Pool bins | Pass: Camera Footage, Music, Graphics |
| Save and verify | Pass |
| Stable project ID | Pass: UUID from `GetUniqueId()` |
| Full service + UI worker | Pass: staging, `.project.json`, publish |
| `~/Videos/Library/` unchanged | Pass |
| `timelinePlaybackFrameRate` | Read-only, reported 24 (warning only) |

The proof-of-concept utility used for this verification is
`scripts/resolve_proof_of_concept.py`. It is read-only unless `--create` is
passed.

Live test projects are left in the Project Library; the application never
deletes them.

## Known limitations

- Resolve must already be running; startup automation is intentionally absent.
- The selected Project Library and folder come from Resolve. The application
  does not switch databases or folders.
- External scripting must be set to **Local**.
- Automatic scripted actions must be set to **Allow all**.
- `timelinePlaybackFrameRate` cannot be set through the API and is only
  verified as a warning. Live verification reported `24` for both presets.
- Resolve 21.1.1 requires **Automatic scripted actions = Allow all** for
  project creation and saving. **Allow safe** silently refuses those calls.
- Media Pool bin creation is best-effort on Resolve versions with incomplete
  folder APIs.
- Source footage is not imported; the user imports it manually from
  `~/Videos/Library/`.
- Rendering, proxies, transcoding, archiving and backups are out of scope.

## License

MIT. See [LICENSE](LICENSE).
