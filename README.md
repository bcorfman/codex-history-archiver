# Codex History Archiver

Incremental local archiving for Codex conversations using the official `Stop`
hook.

Primary target:

- WSL2 + VS Code + Codex

Also intended to work with:

- generic Ubuntu/Linux setups
- native Windows setups

This tool is specifically meant to work with the Codex VS Code extension. It
uses the same `~/.codex/config.toml` hook surface that Codex documents for the
IDE extension, app, and CLI.

The archiver keeps:

- the raw transcript JSONL as the canonical source of truth
- a readable Markdown export per session
- a readable HTML export per session
- a per-project Markdown/HTML index

It is designed for people who want project chat history preserved outside the
VS Code sidebar, with minimal risk of losing searchable conversation memory.

## How It Works

Codex fires a `Stop` hook at the end of a turn. The hook payload includes a
`transcript_path`, `cwd`, `session_id`, and `turn_id`.

This project uses that event to:

1. determine the project root from the current working directory
2. copy the current transcript JSONL into a private archive
3. regenerate Markdown and HTML exports for that session
4. regenerate a per-project session index

## Archive Layout

The archive location is controlled by an environment variable:

`CODEX_HISTORY_ARCHIVE_ROOT`

Inside that root, archives are written like this:

```text
projects/<project-slug>/
  index.md
  index.html
  sessions/
    <session-id>.jsonl
    <session-id>.md
    <session-id>.html
    <session-id>.meta.json
```

## Configure A Private Archive Directory

Set a private archive location outside the repo, for example:

```bash
export CODEX_HISTORY_ARCHIVE_ROOT=/mnt/c/Users/your-user/codex-history-archive
```

For persistence on WSL2 or Ubuntu, add that export to `.bash_profile` or
another login-shell startup file that Codex will inherit.

For native Windows, set `CODEX_HISTORY_ARCHIVE_ROOT` as a user environment
variable.

### Windows Persistent User Env Var

PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
  "CODEX_HISTORY_ARCHIVE_ROOT",
  "C:\\Users\\your-user\\codex-history-archive",
  "User"
)
```

Then restart VS Code so the Codex extension inherits the updated environment.

To verify in a new PowerShell session:

```powershell
$env:CODEX_HISTORY_ARCHIVE_ROOT
```

### WSL2 Persistent Env Var

For WSL2 or Ubuntu, add the export to a login-shell startup file such as
`.bash_profile`:

```bash
export CODEX_HISTORY_ARCHIVE_ROOT="/mnt/c/Users/your-user/codex-history-archive"
```

Then restart VS Code so the remote WSL extension host and Codex pick it up.

## Install

```bash
python3 bin/install-hook.py --config ~/.codex/config.toml
```

This appends or updates a managed hook block in `~/.codex/config.toml`.

- On WSL2/Linux, the generated hook uses `bash -lc` so login-shell environment
  variables are available.
- On Windows, run the installer from a Windows checkout so it can generate the
  Windows-specific hook command.

### Non-WSL Windows Install Flow

1. Clone the repo in Windows, for example:

```powershell
git clone https://github.com/bcorfman/codex-history-archiver.git `
  C:\Users\your-user\dev\codex-history-archiver
cd C:\Users\your-user\dev\codex-history-archiver
```

2. Set the persistent user environment variable:

```powershell
[Environment]::SetEnvironmentVariable(
  "CODEX_HISTORY_ARCHIVE_ROOT",
  "C:\\Users\\your-user\\codex-history-archive",
  "User"
)
```

3. Install the hook into your Codex config:

```powershell
py -3 .\bin\install-hook.py --config $HOME\.codex\config.toml
```

4. Restart VS Code.

5. Finish a Codex turn and verify files appear under:

```powershell
Get-ChildItem -Recurse $env:CODEX_HISTORY_ARCHIVE_ROOT
```

### Non-WSL Windows Backfill

After installing, you can backfill existing sessions with:

```powershell
py -3 .\bin\backfill-history.py
```

## Verify

After installation, finish a Codex turn in VS Code and check:

```bash
find "$CODEX_HISTORY_ARCHIVE_ROOT" -maxdepth 4 -type f | sort
```

## Backfill Existing Sessions

To archive the Codex transcripts you already have on disk:

```bash
python3 bin/backfill-history.py
```

## Privacy Model

- The repo is safe to publish publicly.
- Transcript exports are written only to the private directory named by
  `CODEX_HISTORY_ARCHIVE_ROOT`.
- No transcript data is stored inside the tool repo unless you do that
  deliberately yourself.

## Related Tools

This project is intentionally small and focused on automatic incremental
archiving from the Codex hook system.

If you want richer browsing or standalone export tools, these are worth a look:

- `codex-export`
  Markdown export for Codex sessions, including Codex Desktop/CLI style flows.
- `codex-transcript-viewer`
  Single-session HTML viewer with a richer browser UI.
- `agent-trace`
  Terminal UI for browsing and exporting local session histories.
- `CodexMonitor`
  Session inspection and monitoring tools, including VS Code extension session
  support.
- `codex-trace-viewer`
  Local trace viewer focused on inspecting session internals.

## Why This Exists

Those tools are useful, but this repo solves a narrower operational problem:

- export automatically at the end of a Codex interaction
- work well with the Codex VS Code extension on WSL2
- keep raw transcripts plus readable exports
- keep the archive path private and outside the public repo

## Notes

- The raw JSONL transcript is the canonical backup.
- The Markdown and HTML are derived convenience exports.
- The VS Code UI may still show only a recent subset of threads, but the full
  archived session set remains available on disk.

## Troubleshooting

### `CODEX_HISTORY_ARCHIVE_ROOT` is not visible to Codex

Symptoms:

- no archive files are written
- the hook returns a message saying the archive root is not set

Checks:

- On WSL2/Linux:

```bash
bash -lc 'echo "$CODEX_HISTORY_ARCHIVE_ROOT"'
```

- On Windows:

```powershell
$env:CODEX_HISTORY_ARCHIVE_ROOT
```

Fix:

- make sure the variable is set persistently
- restart VS Code completely after setting it
- on WSL2, prefer a login-shell startup file such as `.bash_profile`

### Hook is installed but does not seem to fire

Checks:

- confirm the hook block exists in `~/.codex/config.toml`
- confirm the repo/project is trusted in Codex
- finish a full Codex turn in the VS Code extension, then inspect the archive
  root

Reinstall:

```bash
python3 bin/install-hook.py --config ~/.codex/config.toml
```

Windows:

```powershell
py -3 .\bin\install-hook.py --config $HOME\.codex\config.toml
```

### Archive files appear under the wrong project slug

The tool uses `git rev-parse --show-toplevel` when available and falls back to
the current working directory otherwise.

Checks:

- verify the Codex session is actually running in the repo you expect
- verify that repo is a real Git checkout
- compare the session `cwd` stored in the exported `.meta.json` file

If needed, you can still find the transcript by session ID in the archive even
if the project slug is not what you expected.
