#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path


BEGIN_MARKER = "# BEGIN codex-history-archiver"
END_MARKER = "# END codex-history-archiver"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to ~/.codex/config.toml")
    return parser.parse_args()


def managed_block(repo_root: Path) -> str:
    script_path = repo_root / "bin" / "codex-history-archiver.py"

    if os.name == "nt":
        command_line = f'py -3 "{script_path}"'
        extra_lines = [f'commandWindows = "{command_line}"']
    else:
        inner = f"python3 {shlex.quote(str(script_path))}"
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
    repo_root = Path(__file__).resolve().parent.parent
    updated = replace_or_append(existing, managed_block(repo_root))
    config_path.write_text(updated)
    print(f"Updated {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
