#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive-root",
        default=os.environ.get("CODEX_HISTORY_ARCHIVE_ROOT"),
        help="Private archive root. Defaults to CODEX_HISTORY_ARCHIVE_ROOT.",
    )
    parser.add_argument(
        "--hook-json",
        help="Optional path to a saved hook payload for testing.",
    )
    parser.add_argument("--transcript-path", help="Override transcript path.")
    parser.add_argument("--cwd", help="Override current working directory.")
    parser.add_argument("--session-id", help="Override session id.")
    parser.add_argument(
        "--html-backend",
        default=os.environ.get("CODEX_HISTORY_HTML_BACKEND", "builtin"),
        help="HTML backend: builtin, codex-transcripts, or codex-transcript-viewer.",
    )
    return parser.parse_args()


def load_hook_payload(args: argparse.Namespace) -> dict:
    if args.hook_json:
        return json.loads(Path(args.hook_json).read_text())
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return slug or "unknown-project"


def format_local_timestamp(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    if dt.tzinfo is None:
        return value
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def git_root_for(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(result.stdout.strip())


def load_session_index() -> dict[str, dict]:
    index_path = Path.home() / ".codex" / "session_index.jsonl"
    sessions: dict[str, dict] = {}
    if not index_path.exists():
        return sessions
    for line in index_path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        session_id = item.get("id")
        if session_id:
            sessions[session_id] = item
    return sessions


def extract_text_parts(parts: list[dict]) -> str:
    collected: list[str] = []
    for part in parts:
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            collected.append(text.rstrip())
    return "\n\n".join(collected).strip()


def parse_transcript(transcript_path: Path) -> dict:
    session_meta: dict = {}
    messages: list[dict] = []

    for line in transcript_path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        item_type = item.get("type")
        payload = item.get("payload", {})

        if item_type == "session_meta":
            session_meta = payload
            continue

        if item_type != "response_item":
            continue
        if payload.get("type") != "message":
            continue

        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue

        content = payload.get("content", [])
        text = extract_text_parts(content)
        if not text:
            continue

        messages.append(
            {
                "timestamp": item.get("timestamp"),
                "role": role,
                "phase": payload.get("phase"),
                "text": text,
            }
        )

    return {
        "session_meta": session_meta,
        "messages": messages,
    }


def render_markdown(meta: dict, messages: list[dict]) -> str:
    header = [
        f"# {meta['title']}",
        "",
        f"- Session ID: `{meta['session_id']}`",
        f"- Project: `{meta['project_slug']}`",
        f"- CWD: `{meta['cwd']}`",
        f"- Transcript: `{meta['transcript_source']}`",
        f"- Updated: `{meta['updated_at_local']}`",
        "",
    ]
    body: list[str] = []
    for message in messages:
        role = "User" if message["role"] == "user" else "Assistant"
        phase = f" ({message['phase']})" if message.get("phase") else ""
        body.extend(
            [
                f"## {role}{phase}",
                "",
                f"_Timestamp: `{message['timestamp_local']}`_",
                "",
                message["text"],
                "",
            ]
        )
    return "\n".join(header + body).strip() + "\n"


def render_html(meta: dict, messages: list[dict]) -> str:
    title = html.escape(meta["title"])
    rows = []
    for message in messages:
        role = "User" if message["role"] == "user" else "Assistant"
        phase = f" ({message['phase']})" if message.get("phase") else ""
        rows.append(
            "<section class='message'>"
            f"<h2>{html.escape(role + phase)}</h2>"
            f"<p class='timestamp'>{html.escape(str(message['timestamp_local']))}</p>"
            f"<pre>{html.escape(message['text'])}</pre>"
            "</section>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{
      font-family: Georgia, serif;
      margin: 2rem auto;
      max-width: 900px;
      line-height: 1.5;
      padding: 0 1rem 4rem;
      background: #f7f4ed;
      color: #1d1b19;
    }}
    h1, h2 {{ line-height: 1.2; }}
    .meta {{ margin-bottom: 2rem; }}
    .message {{
      background: #fffdfa;
      border: 1px solid #d8cfc1;
      padding: 1rem 1.25rem;
      margin: 1rem 0;
    }}
    .timestamp {{
      color: #6b6257;
      font-size: 0.9rem;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font-family: "Iosevka Fixed", "SFMono-Regular", Consolas, monospace;
    }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="meta">
    <p><strong>Session ID:</strong> <code>{html.escape(meta["session_id"])}</code></p>
    <p><strong>Project:</strong> <code>{html.escape(meta["project_slug"])}</code></p>
    <p><strong>CWD:</strong> <code>{html.escape(meta["cwd"])}</code></p>
    <p><strong>Transcript:</strong> <code>{html.escape(meta["transcript_source"])}</code></p>
    <p><strong>Updated:</strong> <code>{html.escape(meta["updated_at_local"])}</code></p>
  </div>
  {''.join(rows)}
</body>
</html>
"""


def render_html_with_backend(
    backend: str, transcript_path: Path, html_path: Path, meta: dict, messages: list[dict]
) -> str:
    backend_cmd = os.environ.get("CODEX_HISTORY_HTML_BACKEND_CMD")
    if backend_cmd:
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered = backend_cmd.format(
                input=shlex.quote(str(transcript_path)),
                output=shlex.quote(str(html_path)),
                output_dir=shlex.quote(tmpdir),
            )
            result = subprocess.run(rendered, shell=True, capture_output=True, text=True)
            generated = Path(tmpdir) / "index.html"
            if result.returncode == 0:
                if generated.exists():
                    html_path.write_text(generated.read_text())
                    return "command-override"
                if html_path.exists():
                    return "command-override"

    if backend == "codex-transcripts":
        executable = shutil.which("codex-transcripts")
        if executable:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    [
                        executable,
                        "json",
                        str(transcript_path),
                        "-o",
                        tmpdir,
                    ],
                    capture_output=True,
                    text=True,
                )
                generated = Path(tmpdir) / "index.html"
                if result.returncode == 0 and generated.exists():
                    html_path.write_text(generated.read_text())
                    return "codex-transcripts"

    if backend == "codex-transcript-viewer":
        executable = shutil.which("codex-transcript-viewer")
        if executable:
            result = subprocess.run(
                [executable, str(transcript_path), str(html_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and html_path.exists():
                return "codex-transcript-viewer"

    html_path.write_text(render_html(meta, messages))
    return "builtin"


def write_session_exports(
    project_dir: Path,
    session_meta: dict,
    messages: list[dict],
    transcript_path: Path,
    html_backend: str,
) -> dict:
    sessions_dir = project_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_id = session_meta["session_id"]
    raw_path = sessions_dir / f"{session_id}.jsonl"
    md_path = sessions_dir / f"{session_id}.md"
    html_path = sessions_dir / f"{session_id}.html"
    meta_path = sessions_dir / f"{session_id}.meta.json"

    shutil.copyfile(transcript_path, raw_path)
    md_path.write_text(render_markdown(session_meta, messages))
    session_meta = dict(session_meta)
    session_meta["html_backend_requested"] = html_backend
    session_meta["html_backend_used"] = render_html_with_backend(
        html_backend, transcript_path, html_path, session_meta, messages
    )
    meta_path.write_text(json.dumps(session_meta, indent=2) + "\n")

    return {
        "raw_path": raw_path,
        "md_path": md_path,
        "html_path": html_path,
        "meta_path": meta_path,
    }


def rebuild_project_index(project_dir: Path) -> None:
    sessions_dir = project_dir / "sessions"
    meta_files = sorted(sessions_dir.glob("*.meta.json"))
    entries = []
    for meta_file in meta_files:
        meta = json.loads(meta_file.read_text())
        entries.append(meta)
    entries.sort(key=lambda item: item.get("updated_at", ""), reverse=True)

    md_lines = [
        f"# Codex History Index: {project_dir.name}",
        "",
    ]
    html_rows = []
    for item in entries:
        session_id = item["session_id"]
        title = item["title"]
        updated_at = item["updated_at"]
        md_lines.extend(
            [
                f"## {title}",
                "",
                f"- Updated: `{item.get('updated_at_local', updated_at)}`",
                f"- Session ID: `{session_id}`",
                f"- [Markdown](sessions/{session_id}.md)",
                f"- [HTML](sessions/{session_id}.html)",
                f"- [Raw JSONL](sessions/{session_id}.jsonl)",
                "",
            ]
        )
        html_rows.append(
            "<tr>"
            f"<td>{html.escape(title)}</td>"
            f"<td><code>{html.escape(item.get('updated_at_local', updated_at))}</code></td>"
            f"<td><a href='sessions/{html.escape(session_id)}.md'>md</a></td>"
            f"<td><a href='sessions/{html.escape(session_id)}.html'>html</a></td>"
            f"<td><a href='sessions/{html.escape(session_id)}.jsonl'>raw</a></td>"
            "</tr>"
        )

    (project_dir / "index.md").write_text("\n".join(md_lines).strip() + "\n")
    (project_dir / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Codex History Index: {html.escape(project_dir.name)}</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 1000px; padding: 0 1rem 4rem; background: #f7f4ed; color: #1d1b19; }}
    table {{ border-collapse: collapse; width: 100%; background: #fffdfa; }}
    th, td {{ border: 1px solid #d8cfc1; padding: 0.75rem; text-align: left; }}
    th {{ background: #efe5d5; }}
  </style>
</head>
<body>
  <h1>Codex History Index: {html.escape(project_dir.name)}</h1>
  <table>
    <thead>
      <tr><th>Title</th><th>Updated</th><th>Markdown</th><th>HTML</th><th>Raw</th></tr>
    </thead>
    <tbody>
      {''.join(html_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    )


def build_metadata(payload: dict, parsed_transcript: dict, transcript_path: Path, archive_root: Path) -> tuple[Path, dict]:
    cwd = Path(payload.get("cwd") or parsed_transcript["session_meta"].get("cwd") or str(Path.home()))
    project_root = git_root_for(cwd) or cwd
    project_slug = sanitize_slug(project_root.name)
    session_id = payload.get("session_id") or parsed_transcript["session_meta"].get("id") or transcript_path.stem
    session_index = load_session_index().get(session_id, {})
    first_user = next((m["text"] for m in parsed_transcript["messages"] if m["role"] == "user"), "")
    title = session_index.get("thread_name") or first_user.splitlines()[0][:80] or session_id
    updated_at = session_index.get("updated_at") or parsed_transcript["messages"][-1]["timestamp"] if parsed_transcript["messages"] else parsed_transcript["session_meta"].get("timestamp", "")

    localized_messages = []
    for message in parsed_transcript["messages"]:
        localized = dict(message)
        localized["timestamp_local"] = format_local_timestamp(message.get("timestamp"))
        localized_messages.append(localized)
    parsed_transcript["messages"] = localized_messages

    project_dir = archive_root / "projects" / project_slug
    meta = {
        "session_id": session_id,
        "title": title,
        "cwd": str(cwd),
        "project_root": str(project_root),
        "project_slug": project_slug,
        "transcript_source": str(transcript_path),
        "updated_at": updated_at,
        "updated_at_local": format_local_timestamp(updated_at),
    }
    return project_dir, meta


def main() -> int:
    args = parse_args()
    if not args.archive_root:
        print(json.dumps({"continue": True, "systemMessage": "CODEX_HISTORY_ARCHIVE_ROOT is not set; skipping Codex history archive."}))
        return 0

    payload = load_hook_payload(args)
    transcript_value = args.transcript_path or payload.get("transcript_path")
    if not transcript_value:
        print(json.dumps({"continue": True}))
        return 0

    transcript_path = Path(transcript_value)
    if not transcript_path.exists():
        print(json.dumps({"continue": True}))
        return 0

    if args.cwd:
        payload["cwd"] = args.cwd
    if args.session_id:
        payload["session_id"] = args.session_id

    archive_root = Path(args.archive_root).expanduser()
    archive_root.mkdir(parents=True, exist_ok=True)

    parsed = parse_transcript(transcript_path)
    project_dir, meta = build_metadata(payload, parsed, transcript_path, archive_root)
    write_session_exports(project_dir, meta, parsed["messages"], transcript_path, args.html_backend)
    rebuild_project_index(project_dir)

    print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
