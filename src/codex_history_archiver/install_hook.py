#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path


BEGIN_MARKER = "# BEGIN codex-history-archiver"
END_MARKER = "# END codex-history-archiver"
DEFAULT_UVX_SOURCE = "git+https://github.com/bcorfman/codex-history-archiver.git"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to ~/.codex/config.toml")
    parser.add_argument(
        "--archive-root",
        required=True,
        help="Private archive directory to write HTML exports into.",
    )
    parser.add_argument(
        "--html-backend",
        default="builtin",
        help="HTML backend to request in the hook. Defaults to builtin.",
    )
    parser.add_argument(
        "--launcher",
        choices=("auto", "local", "uvx"),
        default="auto",
        help="How the managed hook should invoke the archiver command.",
    )
    parser.add_argument(
        "--uvx-source",
        default=DEFAULT_UVX_SOURCE,
        help="Package source to use when the hook launcher is uvx.",
    )
    return parser.parse_args()


def local_repo_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    script_path = candidate / "bin" / "codex-history-archiver.py"
    if (candidate / ".git").exists() and script_path.exists():
        return candidate
    return None


def format_command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(part) for part in parts)


def managed_block(
    launcher: str,
    archive_root: str,
    html_backend: str,
    uvx_source: str,
) -> str:
    repo_root = local_repo_root()

    if launcher == "auto":
        launcher = "local" if repo_root else "uvx"

    if launcher == "local":
        if not repo_root:
            raise SystemExit("local launcher requested, but no repository checkout was detected")
        script_path = repo_root / "bin" / "codex-history-archiver.py"
        base_command = ["python3", str(script_path)]
    else:
        base_command = ["uvx", "--from", uvx_source, "codex-history-archiver"]

    base_command.extend(["--archive-root", archive_root, "--html-backend", html_backend])

    if os.name == "nt":
        command_line = format_command(base_command)
        extra_lines = [f'commandWindows = "{command_line}"']
    else:
        inner = format_command(base_command)
        command_line = f"bash -lc {shlex.quote(inner)}"
        extra_lines = [f'command = "{command_line}"']

    lines = [
        BEGIN_MARKER,
        "[[hooks.Stop]]",
        'matcher = ""',
        "",
        "[[hooks.Stop.hooks]]",
        'type = "command"',
        *extra_lines,
        "timeout = 30",
        'statusMessage = "Archiving Codex history"',
        END_MARKER,
        "",
    ]
    return "\n".join(lines)


def replace_or_append(text: str, block: str) -> str:
    if BEGIN_MARKER in text and END_MARKER in text:
        before, remainder = text.split(BEGIN_MARKER, 1)
        _, after = remainder.split(END_MARKER, 1)
        stripped_after = after.lstrip("\n")
        return before.rstrip() + "\n\n" + block + stripped_after

    base = text.rstrip()
    if base:
        return base + "\n\n" + block
    return block


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text() if config_path.exists() else ""
    updated = replace_or_append(
        existing,
        managed_block(
            args.launcher,
            args.archive_root,
            args.html_backend,
            args.uvx_source,
        ),
    )
    config_path.write_text(updated)
    print(f"Updated {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
