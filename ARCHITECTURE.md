# ocdu — Architecture

`ocdu` (OpenCode Disk Usage) is an `ncdu`-style tool to inspect and safely
clean everything OpenCode stores on a machine. It ships a read-only analysis
core, a CLI, and a Textual TUI.

## Technology stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| TUI | [Textual](https://textual.textualize.io/) 8.x + Rich |
| Database | SQLite via the standard-library `sqlite3` module |
| Packaging | uv + Hatchling (`uv build`); PyInstaller for standalone binaries |
| Linting | ruff (lint only; formatting is not enforced) |

## Module boundaries

| Module | Responsibility | External deps |
|---|---|---|
| `config.py` | Load `~/.config/opencode/ocdu-ui.json`, merge defaults, expand `${KEY}`/`~` | stdlib only |
| `paths.py` | Build the ordered list of tracked data roots and their categories | `config`, `model` |
| `model.py` | Dataclasses shared across ocdu (sizes, reports, results) | stdlib only |
| `util.py` | Byte formatting, directory sizing, text sanitising | stdlib only |
| `db.py` | Read-only SQLite access and size/orphan queries (with a size cache) | `model` |
| `analyze.py` | Filesystem footprint, per-session/per-directory sizing, orphan detection | `db`, `model`, `util`, `config` |
| `opencode.py` | Wrapper around the official `opencode` CLI (`session delete`, `export`) | `config` |
| `safety.py` | Detect a running OpenCode instance and describe the risk | `config` |
| `backup.py` | SQLite online backup → VACUUM snapshot → single zip (rotation) | `config`, `model`, `util` |
| `cleanup.py` | Orphan prune, `VACUUM`, WAL checkpoint, integrity check, log cleanup | `db`, `model`, `util` |
| `export.py` | Markdown transcript and OpenCode-compatible JSON export | `conversation`, `opencode`, `config` |
| `conversation.py` | Load session messages and pair user turns with assistant replies | `db` |
| `move.py` | Recompute `directory`/`path`/`project_id`, resolve target project | `db`, `config` |
| `session_ops.py` | Rename a session title | `db` |
| `stats.py` | Token and cost statistics | `db` |
| `state.py` | Read/write pinned (favourite) session ids in OpenCode TUI state | stdlib only |
| `__main__.py` | CLI argument parser and command dispatch | all of the above |
| `tui/` | Textual application and screens | core modules |

### TUI layout

| Path | Role |
|---|---|
| `tui/app.py` | `OcduApp`, global CSS, command palette, theme persistence |
| `tui/table.py` | `CopyableDataTable` (row copy + single/double click) |
| `tui/listview.py` | `ClickSelectListView` for the detail message list |
| `tui/loading.py` | `LoadingOverlay` shown during blocking operations |
| `tui/format.py` | Column width/format helpers shared by tables |
| `tui/screens/base.py` | `OcduScreen` base with global bindings and `run_blocking` |
| `tui/screens/browse.py` | Home screen: per-directory sizes + footprint info panel |
| `tui/screens/sessions.py` | Session list: sort, filter, mark, move, rename, export, delete |
| `tui/screens/detail.py` | Session breakdown and message list |
| `tui/screens/reply.py` | Full user/assistant reply viewer |
| `tui/screens/dashboard.py` | Disk stats (size of every data root) |
| `tui/screens/stats.py` | Token/cost statistics |
| `tui/screens/{confirm,prompt,theme,keys}.py` | Modals: confirm, text input, theme picker, key help |

## Data roots and categories

Every tracked location has a category that decides what ocdu may do with it:

| Category | Meaning |
|---|---|
| `managed` | ocdu may clean or operate on it (database, session diffs, backups, logs) |
| `info` | shown for information; OpenCode manages it (snapshots, tool output, repos) |
| `locked` | shown but never deleted (state, cache, config) |
| `backup` | ocdu-created backup archives |

## Database schema overview

ocdu reads (and, for move/rename, minimally writes) these OpenCode tables:

| Table | Key columns | Notes |
|---|---|---|
| `session` | `id`, `parent_id`, `title`, `directory`, `path`, `project_id`, `time_created`, `time_updated`, `cost`, `tokens_input`, `tokens_output`, `tokens_reasoning`, `model` | `parent_id` links subagent children |
| `message` | `id`, `session_id`, `data` | JSON payload |
| `part` | `id`, `message_id`, `session_id`, `data` | JSON payload |
| `session_message` | `session_id`, `data` | JSON payload |
| `todo` | `session_id`, `content` | |
| `event` | `aggregate_id`, `data` | append-only event source; `aggregate_id` equals the session id |
| `event_sequence` | `aggregate_id`, … | one row per event aggregate |

A session's size is the sum of `event` + `message` + `part` + `session_message`
+ `todo` bytes, including all descendant sessions — i.e. everything
`opencode session delete` removes. Sizes use UTF-8 byte length
(`length(cast(x AS blob))`).

## Safety model

- **Read-only inspection.** All analytical queries open the database with the
  `file:…?mode=ro` URI, so ocdu never mutates the live database while looking.
- **Deletion is delegated.** Removing a session runs the official
  `opencode session delete <id>` so OpenCode's own cascade applies; ocdu never
  deletes session rows by hand.
- **Prune is conservative.** Only *provably-orphaned* data is removed: `event`
  / `event_sequence` aggregates with no owning session, and `session_diff`
  files whose session no longer exists.
- **VACUUM is explicit.** Because `auto_vacuum` is off, freed pages do not
  shrink the file until `VACUUM` runs; it is a separate command and refuses to
  run while OpenCode appears to be running unless `--force` is given.
- **Subprocess discipline.** `opencode` is invoked with a list of arguments,
  `shell=False`, and `CREATE_NO_WINDOW` on Windows.
- **Backups before risk.** Backup uses the SQLite online backup API (WAL-safe),
  VACUUMs the snapshot, writes the archive atomically (`.part` + `os.replace`)
  and keeps only the newest `BACKUP_KEEP` archives.
- **The only self-write is the pin flag.** Toggling a favourite (`f` in the TUI)
  edits OpenCode's TUI state file (`<state>/session.json`): ocdu updates only the
  `pinned` list, preserves any other keys, and writes atomically. The database is
  never touched. A live OpenCode instance holds that file in memory and rewrites
  it on its own changes, so the TUI warns when one appears to be running.

## Configuration

A single optional JSON file, `~/.config/opencode/ocdu-ui.json`, is the only
configuration source. Missing keys fall back to built-in defaults, and values
may reference others with `${KEY}`. See the README for the full key table.

## Testing

The pytest suite lives in `tests/` (configuration in `pytest.ini`). Every test
runs against a **synthetic throwaway database** created from the schema embedded
in `tests/conftest.py`; the real OpenCode database is never opened or written.
The main fixtures are `make_db` (build a schema-only or pre-populated database),
`config_factory` (a `Config` rooted in `tmp_path`) and `apply_config` (install
that config into every module that holds a module-level `config` reference).
Row dicts come from the `factory-boy` factories in `tests/factories.py`.

An autouse fixture replaces `subprocess.run` with a failing stub, so any test that
exercises an external command (`opencode`, `git`, `tasklist`) must monkeypatch it
explicitly. Read-only analysis and file operations are covered by unit tests, the
CLI by `tests/test_cli.py`, and the TUI by headless `app.run_test()` tests under
`tests/tui/` (driven through `asyncio.run`; `pytest-asyncio` is intentionally not
used). `make test-cov` reports coverage (no enforced threshold).

## File structure

```text
ocdu/
├── pyproject.toml           # uv project; entry point `ocdu = ocdu.__main__:main`
├── ocdu-ui.example.json     # example config file
├── README.md
├── ARCHITECTURE.md
├── Makefile                 # dev/build helpers (run, test, package, installs)
├── pytest.ini               # pytest configuration (testpaths, pythonpath)
├── tests/                   # pytest suite (synthetic DB fixtures + TUI smoke)
├── packaging/               # PyInstaller launcher
├── scripts/                 # publish.py (private/public publishing helpers)
└── src/ocdu/
    ├── __main__.py          # CLI entry point
    ├── config.py
    ├── paths.py
    ├── model.py
    ├── util.py
    ├── db.py
    ├── analyze.py
    ├── opencode.py
    ├── safety.py
    ├── backup.py
    ├── cleanup.py
    ├── export.py
    ├── conversation.py
    ├── move.py
    ├── session_ops.py
    ├── stats.py
    ├── state.py
    └── tui/
        ├── app.py
        ├── table.py
        ├── listview.py
        ├── loading.py
        ├── format.py
        └── screens/
            ├── base.py
            ├── browse.py
            ├── sessions.py
            ├── detail.py
            ├── reply.py
            ├── dashboard.py
            ├── stats.py
            ├── confirm.py
            ├── prompt.py
            ├── theme.py
            └── keys.py
```
