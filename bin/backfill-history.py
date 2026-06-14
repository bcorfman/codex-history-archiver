#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive-root",
        default=os.environ.get("CODEX_HISTORY_ARCHIVE_ROOT"),
        help="Archive root. Defaults to CODEX_HISTORY_ARCHIVE_ROOT.",
    )
    parser.add_argument(
        "--codex-home",
        default=str(Path.home() / ".codex"),
        help="Path to CODEX_HOME.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.archive_root:
        raise SystemExit("archive root is required; set --archive-root or CODEX_HISTORY_ARCHIVE_ROOT")
    codex_home = Path(args.codex_home).expanduser()
    archiver = Path(__file__).resolve().parent / "codex-history-archiver.py"

    transcript_paths = sorted((codex_home / "sessions").rglob("*.jsonl"))
    archived_root = codex_home / "archived_sessions"
    if archived_root.exists():
        transcript_paths.extend(sorted(archived_root.rglob("*.jsonl")))

    for transcript_path in transcript_paths:
        subprocess.run(
            [
                "python3",
                str(archiver),
                "--archive-root",
                args.archive_root,
                "--transcript-path",
                str(transcript_path),
            ],
            input=json.dumps({}),
            text=True,
            check=True,
            capture_output=True,
        )

    print(f"Backfilled {len(transcript_paths)} transcript(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
