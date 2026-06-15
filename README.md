# Codex History Archiver

A safe, private, searchable local archive for every Codex conversation.

Codex History Archiver automatically exports each Codex conversation at the end
of every turn, creating durable per-project HTML history outside the built-in
VS Code sidebar.

Built for the real workflow:

- automatic export after every Codex interaction
- strong WSL2 + VS Code + Codex support
- clean HTML session pages plus a per-project index
- archive storage that stays outside your public repo

It uses the official Codex `Stop` hook, so the archive stays up to date with
minimal setup and minimal risk of losing useful conversation history.

Primary target:

- WSL2 + VS Code + Codex

Also intended to work with:

- generic Ubuntu/Linux setups
- native Windows setups

This tool is specifically meant to work with the Codex VS Code extension. It
uses the same `~/.codex/config.toml` hook surface that Codex documents for the
IDE extension, app, and CLI.

The archiver keeps:

- a session HTML export per conversation
- a per-project HTML index

It is designed for people who want project chat history preserved outside the
VS Code sidebar, with a durable archive they control.

## How It Works

Codex fires a `Stop` hook at the end of a turn. The hook payload includes a
`transcript_path`, `cwd`, `session_id`, and `turn_id`.

This project uses that event to:

1. determine the project root from the current working directory
2. regenerate an HTML export for that session
3. regenerate a per-project session index

## Export Backends

HTML is the only archived artifact.

HTML export defaults to the builtin conversation renderer, with optional
PATH-based backend overrides if you want a different renderer.

Supported HTML backend values:

- `builtin`
- `codex-transcript-viewer`
- `codex-transcripts`

Set with:

```bash
export CODEX_HISTORY_HTML_BACKEND=builtin
```

If you do not set `CODEX_HISTORY_HTML_BACKEND`, the builtin renderer is used.
If a requested external backend is not installed on `PATH`, the tool falls
back automatically to the builtin HTML export.

### Command Override

If you prefer to run an external exporter through a wrapper command instead of a
plain executable on `PATH`, set:

```bash
export CODEX_HISTORY_HTML_BACKEND_CMD='uvx --from git+https://github.com/masonc15/codex-transcript-viewer codex-transcript-viewer {input} {output}'
```

The archiver will use that command first for HTML export and substitute:

- `{input}` for the transcript path
- `{output}` for the output HTML path
- `{output_dir}` for a temporary output directory

When `CODEX_HISTORY_HTML_BACKEND_CMD` is set, it takes precedence over the
named backend selection.

## Archive Layout

The archive location is controlled by an environment variable:

`CODEX_HISTORY_ARCHIVE_ROOT`

Inside that root, archives are written like this:

```text
projects/<project-slug>/
  index.html
  sessions/
    <session-id>.html
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
[Environment]::SetEnvironmentVariable(
  "CODEX_HISTORY_HTML_BACKEND",
  "builtin",
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
export CODEX_HISTORY_HTML_BACKEND="builtin"
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
[Environment]::SetEnvironmentVariable(
  "CODEX_HISTORY_HTML_BACKEND",
  "builtin",
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

- `agent-trace`
  Terminal UI for browsing and exporting local session histories.
- `CodexMonitor`
  Session inspection and monitoring tools, including VS Code extension session
  support.
- `codex-trace-viewer`
  Local trace viewer focused on inspecting session internals.
- `codex-transcript-viewer`
  Single-session HTML viewer with sidebar filters such as `No tools`,
  `User only`, `Answers`, and `All`.
- `codex-transcripts`
  More capable HTML/TUI/export tool with picker flows, multi-select archives,
  `--cwd` filtering, and one-off `uvx` usage.

## Why This Exists

This repo stays intentionally narrow: reliable automatic archiving for Codex in
the workflow many people actually use, especially VS Code on WSL2.

The builtin renderer is the recommended default because it groups each user
prompt with the related Codex commentary and final answer, while keeping tool
activity collapsed into optional details.

## Notes

- The private archive keeps HTML only.
- The HTML exporter choice determines how much tool/system detail is visible.
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
- open the session HTML and inspect the embedded archive metadata block in page
  source if you need to confirm the stored `cwd`

If needed, you can still find the transcript by session ID in the archive even
if the project slug is not what you expected.
