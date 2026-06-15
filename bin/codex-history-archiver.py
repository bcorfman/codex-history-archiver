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

ARCHIVE_META_TAG = "codex-history-archive-meta"


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
        default=os.environ.get("CODEX_HISTORY_HTML_BACKEND", "codex-transcript-viewer"),
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


def summarize_entry(item: dict) -> tuple[str, str]:
    item_type = item.get("type", "unknown")
    payload = item.get("payload", {})

    if item_type == "session_meta":
        session_id = payload.get("id", "unknown-session")
        cwd = payload.get("cwd", "")
        return "Session Meta", f"Session `{session_id}` started in `{cwd}`"

    if item_type == "turn_context":
        cwd = payload.get("cwd", "")
        turn_id = payload.get("turn_id", "")
        return "Turn Context", f"Turn `{turn_id}` in `{cwd}`"

    if item_type == "event_msg":
        event_payload = payload.get("type", "unknown")
        message = payload.get("message") or payload.get("last_agent_message") or ""
        heading = f"Event: {event_payload}"
        return heading, message.strip()

    if item_type == "response_item":
        payload_type = payload.get("type", "unknown")
        if payload_type == "message":
            role = payload.get("role", "unknown")
            content = extract_text_parts(payload.get("content", []))
            phase = payload.get("phase")
            phase_text = f" ({phase})" if phase else ""
            return f"Message: {role}{phase_text}", content
        if payload_type == "function_call":
            name = payload.get("name", "unknown")
            arguments = payload.get("arguments", "")
            return f"Function Call: {name}", arguments
        if payload_type == "function_call_output":
            call_id = payload.get("call_id", "")
            output = payload.get("output", "")
            return f"Function Output: {call_id}", output
        if payload_type == "reasoning":
            summary = payload.get("summary", [])
            encrypted = payload.get("encrypted_content", "")
            reasoning_text = ""
            if summary:
                reasoning_text += "Summary:\n" + json.dumps(summary, indent=2)
            if encrypted:
                if reasoning_text:
                    reasoning_text += "\n\n"
                reasoning_text += "Encrypted content:\n" + encrypted
            return "Reasoning", reasoning_text
        return f"Response Item: {payload_type}", json.dumps(payload, indent=2)

    if item_type == "web_search_call":
        return "Web Search Call", json.dumps(payload, indent=2)

    return item_type.replace("_", " ").title(), json.dumps(payload, indent=2)


def parse_transcript(transcript_path: Path) -> dict:
    session_meta: dict = {}
    entries: list[dict] = []

    for line in transcript_path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") == "session_meta":
            session_meta = item.get("payload", {})

        heading, text = summarize_entry(item)
        entries.append(
            {
                "timestamp": item.get("timestamp"),
                "heading": heading,
                "text": text,
                "raw": json.dumps(item, indent=2),
            }
        )

    return {
        "session_meta": session_meta,
        "entries": entries,
    }


def render_markdown(meta: dict, entries: list[dict]) -> str:
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
    for entry in entries:
        body.extend(
            [
                f"## {entry['heading']}",
                "",
                f"_Timestamp: `{entry['timestamp_local']}`_",
                "",
                entry["text"] or "_No summarized text_",
                "",
                "### Raw Entry",
                "",
                "```json",
                entry["raw"],
                "```",
                "",
            ]
        )
    return "\n".join(header + body).strip() + "\n"


def render_html(meta: dict, entries: list[dict]) -> str:
    title = html.escape(meta["title"])
    rows = []
    for entry in entries:
        rows.append(
            "<section class='message'>"
            f"<h2>{html.escape(entry['heading'])}</h2>"
            f"<p class='timestamp'>{html.escape(str(entry['timestamp_local']))}</p>"
            f"<pre>{html.escape(entry['text'] or '_No summarized text_')}</pre>"
            "<details><summary>Raw entry</summary>"
            f"<pre>{html.escape(entry['raw'])}</pre>"
            "</details>"
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


def inject_archive_metadata(html_text: str, meta: dict) -> str:
    payload = html.escape(json.dumps(meta, ensure_ascii=False))
    tag = f'<script id="{ARCHIVE_META_TAG}" type="application/json">{payload}</script>'
    if f'id="{ARCHIVE_META_TAG}"' in html_text:
        html_text = re.sub(
            rf'<script id="{ARCHIVE_META_TAG}" type="application/json">.*?</script>',
            tag,
            html_text,
            count=1,
            flags=re.DOTALL,
        )
        return html_text
    if "</head>" in html_text:
        return html_text.replace("</head>", f"  {tag}\n</head>", 1)
    return tag + "\n" + html_text


def render_html_with_backend(
    backend: str, transcript_path: Path, html_path: Path, meta: dict, entries: list[dict]
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
                    html_path.write_text(inject_archive_metadata(generated.read_text(), meta))
                    return "command-override"
                if html_path.exists():
                    html_path.write_text(inject_archive_metadata(html_path.read_text(), meta))
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
                    html_path.write_text(inject_archive_metadata(generated.read_text(), meta))
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
                html_path.write_text(inject_archive_metadata(html_path.read_text(), meta))
                return "codex-transcript-viewer"

    html_path.write_text(inject_archive_metadata(render_html(meta, entries), meta))
    return "builtin"


def write_session_exports(
    project_dir: Path,
    session_meta: dict,
    entries: list[dict],
    transcript_path: Path,
    html_backend: str,
) -> dict:
    sessions_dir = project_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_id = session_meta["session_id"]
    html_path = sessions_dir / f"{session_id}.html"
    session_meta = dict(session_meta)
    session_meta["html_backend_requested"] = html_backend
    session_meta["html_backend_used"] = render_html_with_backend(
        html_backend, transcript_path, html_path, session_meta, entries
    )
    for legacy_path in (
        sessions_dir / f"{session_id}.jsonl",
        sessions_dir / f"{session_id}.md",
        sessions_dir / f"{session_id}.meta.json",
    ):
        if legacy_path.exists():
            legacy_path.unlink()

    return {
        "html_path": html_path,
    }


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


def rebuild_project_index(project_dir: Path) -> None:
    sessions_dir = project_dir / "sessions"
    html_files = sorted(sessions_dir.glob("*.html"))
    entries = []
    for html_file in html_files:
        meta = load_embedded_meta(html_file)
        if meta:
            entries.append(meta)
    entries.sort(key=lambda item: item.get("updated_at", ""), reverse=True)

    html_rows = []
    for item in entries:
        session_id = item["session_id"]
        title = item["title"]
        updated_at = item["updated_at"]
        html_rows.append(
            "<tr>"
            f"<td>{html.escape(title)}</td>"
            f"<td><code>{html.escape(item.get('updated_at_local', updated_at))}</code></td>"
            f"<td><a href='sessions/{html.escape(session_id)}.html'>html</a></td>"
            "</tr>"
        )

    index_md = project_dir / "index.md"
    if index_md.exists():
        index_md.unlink()
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
      <tr><th>Title</th><th>Updated</th><th>Session</th></tr>
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
    first_user = next(
        (
            entry["text"]
            for entry in parsed_transcript["entries"]
            if entry["heading"].startswith("Message: user")
        ),
        "",
    )
    title = session_index.get("thread_name") or first_user.splitlines()[0][:80] or session_id
    updated_at = session_index.get("updated_at") or parsed_transcript["entries"][-1]["timestamp"] if parsed_transcript["entries"] else parsed_transcript["session_meta"].get("timestamp", "")

    localized_entries = []
    for entry in parsed_transcript["entries"]:
        localized = dict(entry)
        localized["timestamp_local"] = format_local_timestamp(entry.get("timestamp"))
        localized_entries.append(localized)
    parsed_transcript["entries"] = localized_entries

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
    write_session_exports(project_dir, meta, parsed["entries"], transcript_path, args.html_backend)
    rebuild_project_index(project_dir)

    print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
