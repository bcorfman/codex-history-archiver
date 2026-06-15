#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ARCHIVE_META_TAG = "codex-history-archive-meta"


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


def load_embedded_meta(html_path: Path) -> dict | None:
    text = html_path.read_text(errors="ignore")
    match = re.search(
        rf'<script id="{ARCHIVE_META_TAG}" type="application/json">(.*?)</script>',
        text,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def archiver_cmd() -> list[str]:
    checkout_root = Path(__file__).resolve().parents[2]
    local_script = checkout_root / "bin" / "codex-history-archiver.py"
    if (checkout_root / ".git").exists() and local_script.exists():
        return ["python3", str(local_script)]
    return [sys.executable, "-m", "codex_history_archiver.archiver"]


def rerender_session(
    archive_root: str,
    transcript_path: Path,
    cwd: str | None,
    session_id: str | None,
) -> None:
    cmd = archiver_cmd() + [
        "--archive-root",
        archive_root,
        "--transcript-path",
        str(transcript_path),
    ]
    if cwd:
        cmd.extend(["--cwd", cwd])
    if session_id:
        cmd.extend(["--session-id", session_id])
    subprocess.run(
        cmd,
        input=json.dumps({}),
        text=True,
        check=True,
        capture_output=True,
    )


def main() -> int:
    args = parse_args()
    if not args.archive_root:
        raise SystemExit("archive root is required; set --archive-root or CODEX_HISTORY_ARCHIVE_ROOT")
    codex_home = Path(args.codex_home).expanduser()

    transcript_paths = sorted((codex_home / "sessions").rglob("*.jsonl"))
    archived_root = codex_home / "archived_sessions"
    if archived_root.exists():
        transcript_paths.extend(sorted(archived_root.rglob("*.jsonl")))

    for transcript_path in transcript_paths:
        rerender_session(args.archive_root, transcript_path, None, None)

    archive_projects = Path(args.archive_root).expanduser() / "projects"
    if archive_projects.exists():
        for html_path in sorted(archive_projects.glob("*/sessions/*.html")):
            meta = load_embedded_meta(html_path)
            if not meta:
                continue
            transcript_source = meta.get("transcript_source")
            if not transcript_source:
                continue
            transcript_path = Path(transcript_source).expanduser()
            if not transcript_path.exists():
                continue
            rerender_session(
                args.archive_root,
                transcript_path,
                meta.get("cwd"),
                meta.get("session_id"),
            )

    print(f"Backfilled {len(transcript_paths)} transcript(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
