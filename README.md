# ocdu — OpenCode Disk Usage

An `ncdu`-style TUI to inspect and safely clean everything OpenCode stores on
your machine: sessions, messages, events, snapshots, logs and more.

ocdu never deletes anything on its own. Inspection is read-only, deletion is
delegated to the official `opencode` CLI, and every destructive command is a
dry-run unless you pass `--yes`.

## What it inspects

| Root | Path | Category |
|---|---|---|
| Database | `<data>/opencode.db` (+ `-wal`, `-shm`) | managed |
| Session diffs | `<data>/storage/session_diff/` | managed |
| Backups | `<data>/backups/` (ocdu archives) | managed |
| Log files | `<data>/log/` | managed |
| Snapshots | `<data>/snapshot/` | info |
| Tool output | `<data>/tool-output/` | info |
| Repositories | `<data>/repos/` | info |
| State | `~/.local/state/opencode/` | locked |
| Cache | `~/.cache/opencode/` | locked |
| Config | `~/.config/opencode/` | locked |

* **managed** — ocdu may clean or operate on this root.
* **info** — shown for information; OpenCode manages it itself.
* **locked** — shown but never deleted (state / cache / configuration).

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependencies and running

## Installation

Run straight from a checkout:

```sh
uv sync            # create the virtual environment and install dependencies
uv run ocdu        # launch the interactive TUI
```

Install it as a tool so the `ocdu` command is always on your `PATH`:

```sh
uv tool install .  # provides the `ocdu` command
ocdu --help
```

The equivalent `make` targets: `make venv-install` installs into the project
virtualenv (`.venv`), `make venv-install-dev` is an editable install for
development, and `make tool-install` installs the global uv tool (remove it with
`make tool-uninstall`).

## Usage

```sh
uv run ocdu            # interactive TUI (default; starts on the browse screen)

# inspection (read-only)
uv run ocdu footprint                    # size of every data root
uv run ocdu dirs [-n N]                  # session data size by directory
uv run ocdu sessions [--flat] [-n N]     # session sizes (children included)
uv run ocdu orphans                      # provably-orphaned data
uv run ocdu check                        # integrity check + environment probe

# maintenance
uv run ocdu delete <sessionID> [--yes]   # delete via `opencode session delete`
uv run ocdu prune [--yes] [--backup]     # remove provably-orphaned data
uv run ocdu vacuum [--yes] [--force]     # checkpoint + VACUUM the database
uv run ocdu checkpoint                   # checkpoint the WAL only
uv run ocdu backup                       # create a backup archive (keep last N)
uv run ocdu clean-logs [--days N] [--yes]# delete old log files
uv run ocdu move <sessionID> <dir> [--yes] [--backup] [--force]
uv run ocdu rename <sessionID> <title>
uv run ocdu stats                        # token/cost statistics

# export
uv run ocdu export <sessionID> -f md     # Markdown transcript
uv run ocdu export <sessionID> -f json   # OpenCode-compatible JSON
uv run ocdu export <sessionID> -o out.md [--thinking] [--no-tool-details] [--no-metadata]
```

`delete`, `prune`, `vacuum`, `move` and `clean-logs` are **dry-runs unless
`--yes` is given**.

### TUI keys

| Key | Screen | Action |
|---|---|---|
| `Enter` | browse / sessions | Open the selected directory / session |
| `Enter` | detail | Open the selected message reply |
| `d` | browse | Delete every session in the selected directory |
| `d` | sessions / detail | Delete the selected session (CLI, with confirmation) |
| `space` | sessions | Mark/unmark a session for bulk deletion |
| `m` | sessions / detail | Move the session (and children) to another directory |
| `n` | sessions / detail | Rename the session title |
| `/` | sessions | Filter by title |
| `o` | sessions | Cycle sort: size ↓, size ↑, date ↓, date ↑ |
| `o` | detail | Toggle the message order |
| `e` / `j` | sessions / detail | Export the session as Markdown / JSON (with confirmation) |
| `y` | browse / sessions / disk stats / token stats | Copy the selected row (TSV) |
| `r` | any | Reload the current view |
| `p` | any | Prune orphaned data (optionally with backup) |
| `v` | any | VACUUM the database |
| `q` / `Esc` | any | Go to the home screen (browse) |
| `Backspace` / `Alt+Left` | any | Back |
| `Ctrl+C` | any | Copy the selection if any, otherwise quit |

The command palette (`Ctrl+P`) opens **Theme**, **Token Stats**, **Disk Stats**,
**Database Backup**, **Copy selected row**, **Hide/Show info panel**,
**Screenshot**, **Show Keys** and **Quit**. The footprint info panel (total,
breakdown, data dir, running-instance warning) lives on the home screen.

## Configuration

All changeable values live in a single JSON file:

- **Linux / macOS:** `~/.config/opencode/ocdu-ui.json`
- **Windows:** `C:\Users\<you>\.config\opencode\ocdu-ui.json`

The file is **optional**. Any key you omit falls back to the built-in default
listed below, so an empty or missing file is valid. Values may reference other
keys with `${KEY}` (expanded after all values are merged) and `~` is expanded
to your home directory. The file is created automatically the first time you
pick a theme in the TUI, or you can create it yourself from
[`ocdu-ui.example.json`](ocdu-ui.example.json):

```sh
# Linux / macOS
mkdir -p ~/.config/opencode
cp ocdu-ui.example.json ~/.config/opencode/ocdu-ui.json
```

Example structure (every key, with its default):

```json
{
  "OPENCODE_DATA_DIR": "~/.local/share/opencode",
  "OPENCODE_STATE_DIR": "~/.local/state/opencode",
  "OPENCODE_CACHE_DIR": "~/.cache/opencode",
  "OPENCODE_CONFIG_DIR": "~/.config/opencode",
  "OPENCODE_DB_FILE": "opencode.db",
  "BACKUP_DIR": "${OPENCODE_DATA_DIR}/backups",
  "BACKUP_KEEP": 3,
  "EXPORT_DIR": "${OPENCODE_DATA_DIR}/exports",
  "SCREENSHOT_DIR": "${OPENCODE_DATA_DIR}/screenshots",
  "OPENCODE_BIN": "opencode",
  "OPENCODE_CLI_TIMEOUT": 120,
  "LOG_RETENTION_DAYS": 30,
  "TUI_REFRESH_SECONDS": 0,
  "THEME": "textual-dark",
  "DIST_DIR": "dist"
}
```

The file location is fixed; setting `OPENCODE_CONFIG_DIR` only changes where
OpenCode's own config data is read from, not where `ocdu-ui.json` lives.

| Key | Default | Purpose |
|---|---|---|
| `OPENCODE_DATA_DIR` | `~/.local/share/opencode` | OpenCode data root |
| `OPENCODE_STATE_DIR` | `~/.local/state/opencode` | TUI state root |
| `OPENCODE_CACHE_DIR` | `~/.cache/opencode` | cache root |
| `OPENCODE_CONFIG_DIR` | `~/.config/opencode` | config root |
| `OPENCODE_DB_FILE` | `opencode.db` | database file name |
| `BACKUP_DIR` | `${OPENCODE_DATA_DIR}/backups` | backup archives |
| `BACKUP_KEEP` | `3` | number of archives to keep |
| `EXPORT_DIR` | `${OPENCODE_DATA_DIR}/exports` | JSON/Markdown exports |
| `SCREENSHOT_DIR` | `${OPENCODE_DATA_DIR}/screenshots` | TUI screenshot output (command palette → Screenshot) |
| `OPENCODE_BIN` | `opencode` | OpenCode executable |
| `OPENCODE_CLI_TIMEOUT` | `120` | per-CLI-call timeout (s) |
| `LOG_RETENTION_DAYS` | `30` | log cleanup threshold |
| `TUI_REFRESH_SECONDS` | `0` | dashboard auto-refresh (0 = off) |
| `THEME` | `textual-dark` | TUI theme (set from the command palette) |
| `DIST_DIR` | `dist` | build output directory for `make package` / `make package-dir` |

## How operations work

- **Delete** runs the official `opencode session delete <id>`, so OpenCode's own
  cascade applies (child sessions, events, projections). ocdu never removes
  session rows by hand.
- **Prune** removes only *provably-orphaned* data: event aggregates with no
  owning session, and `session_diff` files whose session no longer exists.
  Deleting a session leaves its `session_diff` file behind, so this is the safe
  way to clean those up.
- **VACUUM** is a separate step. Because `auto_vacuum` is off, deleting rows
  frees pages but does not shrink the file until VACUUM runs. Close OpenCode
  first; use `--force` to override the running-instance check.
- **Backup** takes a consistent snapshot with the SQLite online backup API
  (WAL-safe), VACUUMs the snapshot, and stores the database plus any touched
  files in a single zip. Only the newest `BACKUP_KEEP` archives are kept.
- **Export** writes a Markdown transcript (built locally) or an
  OpenCode-compatible JSON file (produced by `opencode export`, so it can be
  re-imported with `opencode import`).
- **Move** rewrites the session's `directory`, `path` and `project_id` (and
  those of its subagent children). The target project id is resolved the same
  way OpenCode does it: git remote hash → `.git/opencode` cache → root commit →
  `global`. Cross-project moves may break `revert` history, so a backup is
  offered.

## Size semantics

A session's size is the sum of **everything `opencode session delete` removes**:
its `event`, `message`, `part`, `session_message` and `todo` rows, plus those of
all descendant (subagent) sessions. Sizes use UTF-8 byte length
(`length(cast(x AS blob))`), so they match on-disk usage.

## Make commands

The `Makefile` wraps the common tasks. Run `make` or `make help` to list them:

| Target | Description |
|---|---|
| `make sync` | create or refresh the virtual environment |
| `make run` (or `make tui`) | launch the interactive TUI |
| `make test` | run the pytest suite |
| `make test-cov` | run the tests with coverage (`htmlcov/` + `coverage.xml`) |
| `make lint` | `uv run ruff check .` |
| `make push-private` | push `master` to the private remote (`origin`) |
| `make push-public` | build the filtered `publish` branch and push it to `github` |
| `make package` | build a single-file executable at `dist/ocdu.exe` |
| `make package-dir` | build an onedir executable at `dist/ocdu/ocdu.exe` |
| `make venv-install` | install ocdu into the project virtualenv (`.venv`) |
| `make venv-install-dev` | editable install into the project virtualenv |
| `make tool-install` | install ocdu as a global uv tool (on `PATH`; `--force` refreshes it) |
| `make tool-uninstall` | remove the global uv tool |
| `make clean` | remove `build/` and `dist/` |

## Development

Packaging uses PyInstaller and bundles Textual's assets via `--collect-all textual`.
The build output directory comes from the `DIST_DIR` key in the JSON config,
resolved by the program through `ocdu build-dir` (default `dist`). If you point
`DIST_DIR` at another folder inside the repository, add it to `.gitignore` —
only `dist/` is ignored by default. Intermediate files always go to `build/`.

Tests live in `tests/` (pytest + `factory-boy`, config in `pytest.ini`). They run
against synthetic throwaway databases created by the fixtures — the real OpenCode
data is never opened — and external commands are blocked so tests must mock them.
`make test` runs the suite; `make test-cov` adds a coverage report.

Publishing is driven by `scripts/publish.py`. `make push-private` only pushes
`master` to `origin`. `make push-public` clones the committed state, drops the
private paths from the whole history with `git-filter-repo`, and force-pushes the
result to `github` as the `publish` branch. Neither target runs `git add` or
`git commit`, and the public branch never contains the private paths.

## License

ocdu is released under the GNU General Public License v3.0 only
(`GPL-3.0-only`). See [`LICENSE`](LICENSE) for the full text.
