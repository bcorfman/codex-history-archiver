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

Set the default backend at install time with:

```bash
uvx --from git+https://github.com/bcorfman/codex-history-archiver \
  codex-history-install-hook \
  --config ~/.codex/config.toml \
  --archive-root /mnt/c/Users/your-user/codex-history-archive \
  --html-backend builtin
```

If you do not pass `--html-backend`, the builtin renderer is used. If a
requested external backend is not installed on `PATH`, the tool falls back
automatically to the builtin HTML export.

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

The archive location is normally written directly into the managed Codex hook by
the installer.

Inside that root, archives are written like this:

```text
projects/<project-slug>/
  index.html
  sessions/
    <session-id>.html
```

## Configure A Private Archive Directory

Choose a private archive location outside the repo, for example:

```text
/mnt/c/Users/your-user/codex-history-archive
```

Pass that path to the installer with `--archive-root`. The managed hook then
keeps using that path without depending on shell startup files or inherited
environment variables.

Optional overrides:

- `CODEX_HISTORY_ARCHIVE_ROOT`
  If set, overrides the archive directory embedded in the hook command.
- `CODEX_HISTORY_HTML_BACKEND`
  If set, overrides the backend embedded in the hook command.

Environment variables still work well for temporary overrides, but they are no
longer the recommended primary configuration mechanism.

## Install

Install the managed Codex hook directly from GitHub with `uvx`:

```bash
uvx --from git+https://github.com/bcorfman/codex-history-archiver \
  codex-history-install-hook \
  --config ~/.codex/config.toml \
  --archive-root /mnt/c/Users/your-user/codex-history-archive \
  --html-backend builtin
```

This appends or updates a managed hook block in `~/.codex/config.toml`.

- On WSL2/Linux, the installed hook runs through `uvx` via `bash -lc`.
- On Windows, the installed hook uses a Windows command entry in the same
  managed block.
- The archive root and backend are written directly into the hook command, so
  the default install does not depend on login-shell environment propagation.

### WSL2 Example

```bash
uvx --from git+https://github.com/bcorfman/codex-history-archiver \
  codex-history-install-hook \
  --config ~/.codex/config.toml \
  --archive-root /mnt/c/Users/your-user/codex-history-archive \
  --html-backend builtin
```

Restart VS Code after installing so the Codex extension picks up the updated
hook config.

### Native Windows Example

```powershell
uvx --from git+https://github.com/bcorfman/codex-history-archiver `
  codex-history-install-hook `
  --config $HOME\.codex\config.toml `
  --archive-root C:\Users\your-user\codex-history-archive `
  --html-backend builtin
```

Restart VS Code after installing so the Codex extension picks up the updated
hook config.

### Local Checkout Alternative

If you are developing locally and want the hook to point at the checkout instead
of `uvx`, run:

```bash
python3 bin/install-hook.py \
  --config ~/.codex/config.toml \
  --archive-root /mnt/c/Users/your-user/codex-history-archive \
  --html-backend builtin \
  --launcher local
```

## Verify

After installation, finish a Codex turn in VS Code and check:

```bash
find /mnt/c/Users/your-user/codex-history-archive -maxdepth 4 -type f | sort
```

## Backfill Existing Sessions

To archive the Codex transcripts you already have on disk:

```bash
uvx --from git+https://github.com/bcorfman/codex-history-archiver \
  codex-history-backfill \
  --archive-root /mnt/c/Users/your-user/codex-history-archive
```

## Privacy Model

- The repo is safe to publish publicly.
- Transcript exports are written only to the private archive directory you
  choose at install time, unless you deliberately override it.
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

### Archive files are not being written where you expect

Symptoms:

- no archive files are written
- files are written to an old archive path
- the hook returns a message saying the archive root is not set

Checks:

- inspect the managed hook block in `~/.codex/config.toml`
- confirm the `--archive-root` value is the path you meant to install
- if you are using env var overrides, verify them explicitly

On WSL2/Linux:

```bash
bash -lc 'echo "$CODEX_HISTORY_ARCHIVE_ROOT"'
```

On Windows:

```powershell
$env:CODEX_HISTORY_ARCHIVE_ROOT
```

Fix:

- reinstall the hook with the archive path you actually want
- restart VS Code completely after reinstalling
- remove `CODEX_HISTORY_ARCHIVE_ROOT` if an old override is shadowing the hook
  config

### Hook is installed but does not seem to fire

Checks:

- confirm the hook block exists in `~/.codex/config.toml`
- confirm the repo/project is trusted in Codex
- finish a full Codex turn in the VS Code extension, then inspect the archive
  root

Reinstall:

```bash
uvx --from git+https://github.com/bcorfman/codex-history-archiver \
  codex-history-install-hook \
  --config ~/.codex/config.toml \
  --archive-root /mnt/c/Users/your-user/codex-history-archive \
  --html-backend builtin
```

Windows:

```powershell
uvx --from git+https://github.com/bcorfman/codex-history-archiver `
  codex-history-install-hook `
  --config $HOME\.codex\config.toml `
  --archive-root C:\Users\your-user\codex-history-archive `
  --html-backend builtin
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
