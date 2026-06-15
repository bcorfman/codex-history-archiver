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
ARCHIVE_OVERRIDE_STYLE_TAG = "codex-history-archive-style"
ARCHIVE_OVERRIDE_SCRIPT_TAG = "codex-history-archive-script"


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


def is_real_user_prompt(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("<environment_context>"):
        return False
    if stripped.startswith("<cwd>"):
        return False
    return True


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
    turns: list[dict] = []
    current_turn: dict | None = None

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

        item_type = item.get("type")
        payload = item.get("payload", {})
        if item_type != "response_item":
            if (
                item_type == "event_msg"
                and payload.get("type") == "task_complete"
                and current_turn
                and payload.get("last_agent_message")
                and not current_turn["final_answer"]
            ):
                current_turn["final_answer"] = payload["last_agent_message"].strip()
                current_turn["final_answer_timestamp"] = item.get("timestamp")
            continue

        payload_type = payload.get("type")
        if payload_type == "message":
            role = payload.get("role")
            phase = payload.get("phase")
            content = extract_text_parts(payload.get("content", []))
            if role == "user" and is_real_user_prompt(content):
                if current_turn:
                    turns.append(current_turn)
                current_turn = {
                    "user_text": content,
                    "user_timestamp": item.get("timestamp"),
                    "commentary": [],
                    "final_answer": "",
                    "final_answer_timestamp": None,
                    "tools": [],
                }
                continue
            if role == "assistant" and current_turn and content:
                if phase == "final_answer":
                    if current_turn["final_answer"]:
                        current_turn["final_answer"] += "\n\n" + content
                    else:
                        current_turn["final_answer"] = content
                    current_turn["final_answer_timestamp"] = item.get("timestamp")
                else:
                    current_turn["commentary"].append(
                        {
                            "timestamp": item.get("timestamp"),
                            "text": content,
                        }
                    )
            continue

        if not current_turn:
            continue

        if payload_type == "function_call":
            tool = {
                "call_id": payload.get("call_id"),
                "name": payload.get("name", "tool"),
                "arguments": payload.get("arguments", ""),
                "output": "",
                "timestamp": item.get("timestamp"),
            }
            current_turn["tools"].append(tool)
            continue

        if payload_type == "function_call_output":
            call_id = payload.get("call_id")
            output = payload.get("output", "")
            for tool in reversed(current_turn["tools"]):
                if tool.get("call_id") == call_id and not tool.get("output"):
                    tool["output"] = output
                    break
            else:
                current_turn["tools"].append(
                    {
                        "call_id": call_id,
                        "name": "tool_output",
                        "arguments": "",
                        "output": output,
                        "timestamp": item.get("timestamp"),
                    }
                )

    if current_turn:
        turns.append(current_turn)

    return {
        "session_meta": session_meta,
        "entries": entries,
        "turns": turns,
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


def tool_summary(tool: dict) -> str:
    name = tool.get("name", "tool")
    arguments = tool.get("arguments", "")
    if name == "exec_command":
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments.strip().splitlines()[0][:120] or name
        return parsed.get("cmd", name)
    if name == "apply_patch":
        return "apply_patch"
    if name == "search_query":
        return "search"
    if name == "open":
        return "open"
    if arguments:
        return arguments.strip().splitlines()[0][:120]
    return name


def render_chat_text(text: str) -> str:
    placeholders: list[str] = []

    def render_inline(value: str) -> str:
        parts: list[str] = []
        last = 0
        for match in re.finditer(r"`([^`]+)`", value):
            parts.append(html.escape(value[last : match.start()]))
            parts.append(f"<code>{html.escape(match.group(1))}</code>")
            last = match.end()
        parts.append(html.escape(value[last:]))
        return "".join(parts)

    def store(fragment: str) -> str:
        placeholders.append(fragment)
        return f"@@PLACEHOLDER{len(placeholders) - 1}@@"

    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: store(
            f'<a href="{html.escape(m.group(2), quote=True)}">{render_inline(m.group(1))}</a>'
        ),
        text,
    )

    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if lines and all(re.match(r"\d+\.\s+", line) for line in lines):
            items = []
            for line in lines:
                match = re.match(r"\d+\.\s+(.*)", line)
                items.append(f"<li>{render_inline(match.group(1) if match else line)}</li>")
            blocks.append(f"<ol>{''.join(items)}</ol>")
            continue
        if lines and all(line.startswith("- ") for line in lines):
            items = "".join(f"<li>{render_inline(line[2:])}</li>" for line in lines)
            blocks.append(f"<ul>{items}</ul>")
            continue
        blocks.append("<p>" + "<br>".join(render_inline(line) for line in lines) + "</p>")

    rendered = "".join(blocks)
    for idx, fragment in enumerate(placeholders):
        rendered = rendered.replace(f"@@PLACEHOLDER{idx}@@", fragment)
    return rendered


def render_html(meta: dict, turns: list[dict]) -> str:
    title = html.escape(meta["title"])
    sidebar_rows = []
    turn_rows = []
    for idx, turn in enumerate(turns, start=1):
        turn_id = f"turn-{idx}"
        prompt = turn["user_text"].strip()
        prompt_preview = prompt.splitlines()[0][:88]
        sidebar_rows.append(
            "<a class='sidebar-link' href='#{turn_id}'>"
            f"<span class='sidebar-index'>{idx:02d}</span>"
            f"<span class='sidebar-text'>{html.escape(prompt_preview)}</span>"
            "</a>".replace("{turn_id}", turn_id)
        )

        commentary_blocks = []
        for item in turn["commentary"]:
            commentary_blocks.append(
                "<div class='commentary-item'>"
                f"{render_chat_text(item['text'])}"
                "</div>"
            )

        final_answer_block = ""
        if turn["final_answer"]:
            final_answer_block = (
                "<div class='answer-block'>"
                f"<div class='answer-text'>{render_chat_text(turn['final_answer'])}</div>"
                "</div>"
            )

        tools_block = ""
        if turn["tools"]:
            tool_items = []
            for tool in turn["tools"]:
                output = (tool.get("output") or "").strip()
                output_html = ""
                if output:
                    output_html = (
                        "<pre class='tool-output'>"
                        f"{html.escape(output[:4000])}"
                        "</pre>"
                    )
                tool_items.append(
                    "<div class='tool-item'>"
                    f"<div class='tool-title'>{html.escape(tool.get('name', 'tool'))}</div>"
                    f"<div class='tool-summary'>{html.escape(tool_summary(tool))}</div>"
                    f"{output_html}"
                    "</div>"
                )
            tools_block = (
                "<details class='tool-details'>"
                f"<summary>Tool activity ({len(turn['tools'])})</summary>"
                f"{''.join(tool_items)}"
                "</details>"
            )

        turn_rows.append(
            f"""<section class="turn" id="{turn_id}">
  <div class="question-block">
    <div class="question-label">You</div>
    <div class="question-time">{html.escape(turn['user_timestamp_local'])}</div>
    <div class="question-text">{render_chat_text(prompt)}</div>
  </div>
  <div class="assistant-block">
    <div class="assistant-label">Codex</div>
    <div class="assistant-group">
      <div class="commentary-group">
        {''.join(commentary_blocks)}
      </div>
      {final_answer_block}
      {tools_block}
    </div>
  </div>
</section>"""
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #111318;
      --panel: #161922;
      --panel-2: #1a1f2b;
      --panel-3: #12161f;
      --border: #2b3345;
      --text: #edf2f8;
      --muted: #9eabc1;
      --accent: #7fb0ff;
      --accent-2: #67d4c5;
      --answer: #9ad36a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
      font-size: 19px;
      line-height: 1.65;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 1.5rem 1rem 2rem;
      background: #0d1016;
      border-right: 1px solid var(--border);
    }}
    .sidebar h1 {{
      margin: 0 0 0.35rem;
      font-size: 1.2rem;
      line-height: 1.2;
    }}
    .sidebar-meta {{
      margin: 0 0 1.25rem;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .sidebar-link {{
      display: grid;
      grid-template-columns: 2.4rem 1fr;
      gap: 0.75rem;
      align-items: start;
      padding: 0.8rem 0.85rem;
      margin-bottom: 0.6rem;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: #141925;
    }}
    .sidebar-index {{
      color: var(--muted);
      font-size: 0.82rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding-top: 0.15rem;
    }}
    .sidebar-text {{
      font-size: 0.96rem;
      line-height: 1.4;
    }}
    .content {{
      padding: 2rem 2.25rem 4rem;
      max-width: 980px;
    }}
    .page-title {{
      margin: 0 0 0.35rem;
      font-size: 2rem;
      line-height: 1.15;
    }}
    .page-subtitle {{
      margin: 0 0 2rem;
      color: var(--muted);
      font-size: 1rem;
    }}
    .turn {{
      margin-bottom: 2rem;
      padding-bottom: 2rem;
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }}
    .question-block, .assistant-group {{
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 1.15rem 1.25rem;
    }}
    .question-block {{
      background: linear-gradient(180deg, #24272d 0%, #1f2228 100%);
      border: 1px solid rgba(255,255,255,0.04);
      border-left: 0;
      margin-bottom: 0.9rem;
      margin-left: auto;
      max-width: min(72%, 720px);
      border-radius: 24px;
      padding: 1rem 1.2rem;
    }}
    .assistant-block {{
      margin-right: 2.5rem;
      max-width: 860px;
    }}
    .assistant-group {{
      background: transparent;
      border: 0;
      padding: 0;
    }}
    .question-label, .assistant-label {{
      font-size: 0.83rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 0.25rem;
    }}
    .question-time {{
      color: var(--muted);
      font-size: 0.92rem;
      margin-bottom: 0.45rem;
    }}
    .question-text, .answer-text, .commentary-item {{
      font-size: 1rem;
    }}
    .question-text p, .answer-text p, .commentary-item p {{
      margin: 0 0 0.8rem;
    }}
    .question-text p:last-child, .answer-text p:last-child, .commentary-item p:last-child {{
      margin-bottom: 0;
    }}
    .question-text ol, .answer-text ol, .question-text ul, .answer-text ul {{
      margin: 0.4rem 0 0.8rem 1.4rem;
    }}
    .question-text code, .answer-text code, .commentary-item code {{
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 0.92em;
      background: rgba(255,255,255,0.08);
      padding: 0.1rem 0.35rem;
      border-radius: 8px;
    }}
    .question-text a, .answer-text a, .commentary-item a {{
      color: #9bc2ff;
      text-decoration: none;
    }}
    .commentary-group {{
      display: grid;
      gap: 0.55rem;
    }}
    .commentary-group:empty {{
      display: none;
    }}
    .commentary-item {{
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: 0;
      color: var(--text);
    }}
    .commentary-item p {{
      margin: 0;
      white-space: pre-wrap;
    }}
    .answer-block {{
      margin-top: 1rem;
      padding: 1rem 1.05rem;
      border-radius: 16px;
      background: #151a23;
      border: 1px solid rgba(255,255,255,0.06);
    }}
    .tool-details {{
      margin-top: 1rem;
      border: 1px solid rgba(255,255,255,0.07);
      border-radius: 14px;
      background: #0f141d;
      overflow: hidden;
    }}
    .tool-details summary {{
      cursor: pointer;
      padding: 0.9rem 1rem;
      color: var(--muted);
    }}
    .tool-item {{
      padding: 0.95rem 1rem 1rem;
      border-top: 1px solid rgba(255,255,255,0.06);
    }}
    .tool-title {{
      font-size: 0.9rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #bfd0ea;
      margin-bottom: 0.3rem;
    }}
    .tool-summary {{
      color: #d9e2f0;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 0.95rem;
      margin-bottom: 0.6rem;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .tool-output {{
      margin: 0;
      padding: 0.9rem;
      border-radius: 12px;
      background: #0b1017;
      color: #a9b8cc;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 0.9rem;
      max-height: 18rem;
      overflow: auto;
    }}
    @media (max-width: 960px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }}
      .content {{
        padding: 1.25rem 1rem 3rem;
      }}
      .assistant-block {{
        margin-right: 0;
        max-width: 100%;
      }}
      body {{
        font-size: 20px;
      }}
      .question-block {{
        max-width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>{title}</h1>
      <div class="sidebar-meta">{html.escape(meta["project_slug"])} · {len(turns)} turn(s)</div>
      {''.join(sidebar_rows)}
    </aside>
    <main class="content">
      <h1 class="page-title">{title}</h1>
      <p class="page-subtitle">Archived conversation view grouped by prompt and response.</p>
      {''.join(turn_rows)}
    </main>
  </div>
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


def inject_archive_viewer_overrides(html_text: str) -> str:
    style_tag = f"""<style id="{ARCHIVE_OVERRIDE_STYLE_TAG}">
:root {{
  color-scheme: dark;
}}

body {{
  background: #0f1117 !important;
  color: #e6eaf2 !important;
  font-family: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif !important;
}}

#sidebar {{
  background: #0b0e14 !important;
  border-right: 1px solid #202637 !important;
}}

#content {{
  background: #0f1117 !important;
}}

.header {{
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
  padding: 1rem 0 1.25rem !important;
}}

.header h1 {{
  font-size: 1.65rem !important;
  letter-spacing: 0.01em !important;
}}

.header-info,
.footer {{
  display: none !important;
}}

.sidebar-header h2 {{
  letter-spacing: 0.08em !important;
}}

.filter-btn {{
  border-radius: 999px !important;
}}

.filter-btn.active {{
  background: #7dd3c7 !important;
  border-color: #7dd3c7 !important;
  color: #081015 !important;
}}

.tree-node {{
  border-radius: 10px !important;
}}

.user-message,
.assistant-message,
.commentary-message,
.tool-execution,
.system-event,
.token-count,
.thinking-block {{
  border-radius: 14px !important;
  border: 1px solid #273044 !important;
  box-shadow: none !important;
  margin: 1rem 0 !important;
  padding: 1rem 1.1rem !important;
}}

.user-message {{
  background: #131a22 !important;
  border-left: 4px solid #7dd3c7 !important;
}}

.assistant-message {{
  background: #121825 !important;
  border-left: 4px solid #8fb4ff !important;
}}

.commentary-message {{
  background: #151726 !important;
  border-left: 4px solid #f6c177 !important;
  color: #eef2ff !important;
}}

.final-answer {{
  background: #142116 !important;
  border-left: 4px solid #8bd450 !important;
}}

.tool-execution {{
  background: #11151d !important;
  border-left: 4px solid #5f6b85 !important;
}}

.system-event,
.token-count,
.thinking-block {{
  background: #10141b !important;
  border-left: 4px solid #394150 !important;
  color: #9aa5b1 !important;
}}

.message-timestamp {{
  color: #93a0b8 !important;
}}

.tool-header,
.tool-name,
.event-label {{
  color: #d9dfeb !important;
}}

.tool-command,
pre,
code {{
  font-family: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace !important;
}}

pre {{
  white-space: pre-wrap !important;
  word-break: break-word !important;
}}
</style>"""
    script_tag = f"""<script id="{ARCHIVE_OVERRIDE_SCRIPT_TAG}">
(function() {{
  if (window.__codexHistoryArchiveOverridesApplied) return;
  window.__codexHistoryArchiveOverridesApplied = true;

  function visibleMessageIds() {{
    return new Set(
      Array.from(document.querySelectorAll('.tree-node'))
        .filter((node) => node.style.display !== 'none')
        .map((node) => (node.getAttribute('href') || '').replace(/^#/, ''))
        .filter(Boolean)
    );
  }}

  function syncMainPane() {{
    var ids = visibleMessageIds();
    document.querySelectorAll('#messages > [id]').forEach(function(el) {{
      el.style.display = ids.has(el.id) ? '' : 'none';
    }});
  }}

  function wrapFiltering() {{
    if (typeof window.applyFilters === 'function' && !window.__codexHistoryApplyFiltersWrapped) {{
      var originalApplyFilters = window.applyFilters;
      window.applyFilters = function(search) {{
        var result = originalApplyFilters.call(this, search);
        syncMainPane();
        return result;
      }};
      window.__codexHistoryApplyFiltersWrapped = true;
    }}
  }}

  function boot() {{
    wrapFiltering();

    var treeContainer = document.getElementById('tree-container');
    if (treeContainer) {{
      var observer = new MutationObserver(function() {{
        syncMainPane();
      }});
      observer.observe(treeContainer, {{
        subtree: true,
        attributes: true,
        attributeFilter: ['style', 'class']
      }});
    }}

    var noToolsButton = document.querySelector('.filter-btn[data-filter="no-tools"]');
    if (noToolsButton && typeof window.setFilter === 'function') {{
      window.setFilter('no-tools', noToolsButton);
    }} else {{
      syncMainPane();
    }}
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', boot, {{ once: true }});
  }} else {{
    boot();
  }}
}})();
</script>"""
    if f'id="{ARCHIVE_OVERRIDE_STYLE_TAG}"' not in html_text and "</head>" in html_text:
        html_text = html_text.replace("</head>", f"  {style_tag}\n</head>", 1)
    if f'id="{ARCHIVE_OVERRIDE_SCRIPT_TAG}"' not in html_text and "</body>" in html_text:
        html_text = html_text.replace("</body>", f"  {script_tag}\n</body>", 1)
    return html_text


def render_html_with_backend(
    backend: str, transcript_path: Path, html_path: Path, meta: dict, turns: list[dict]
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
                    html_path.write_text(
                        inject_archive_viewer_overrides(
                            inject_archive_metadata(generated.read_text(), meta)
                        )
                    )
                    return "command-override"
                if html_path.exists():
                    html_path.write_text(
                        inject_archive_viewer_overrides(
                            inject_archive_metadata(html_path.read_text(), meta)
                        )
                    )
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
                    html_path.write_text(
                        inject_archive_viewer_overrides(
                            inject_archive_metadata(generated.read_text(), meta)
                        )
                    )
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
                html_path.write_text(
                    inject_archive_viewer_overrides(
                        inject_archive_metadata(html_path.read_text(), meta)
                    )
                )
                return "codex-transcript-viewer"

    html_path.write_text(
        inject_archive_viewer_overrides(
            inject_archive_metadata(render_html(meta, turns), meta)
        )
    )
    return "builtin"


def write_session_exports(
    project_dir: Path,
    session_meta: dict,
    turns: list[dict],
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
        html_backend, transcript_path, html_path, session_meta, turns
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


def session_specificity(meta: dict) -> tuple[int, int, int, str]:
    cwd = str(meta.get("cwd") or "")
    project_root = str(meta.get("project_root") or "")
    updated_at = str(meta.get("updated_at") or "")
    cwd_depth = len([part for part in Path(cwd).parts if part not in {"/"}])
    project_depth = len([part for part in Path(project_root).parts if part not in {"/"}])
    return (cwd_depth, project_depth, len(updated_at), updated_at)


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


def prune_duplicate_session_archives(archive_root: Path, session_id: str) -> list[Path]:
    matches = sorted(archive_root.glob(f"projects/*/sessions/{session_id}.html"))
    if len(matches) <= 1:
        return []

    candidates: list[tuple[tuple[int, int, int, str], Path, dict]] = []
    for path in matches:
        meta = load_embedded_meta(path)
        if not meta:
            continue
        candidates.append((session_specificity(meta), path, meta))

    if not candidates:
        return []

    candidates.sort(reverse=True, key=lambda item: item[0])
    keep_path = candidates[0][1]
    removed: list[Path] = []
    for _score, path, _meta in candidates[1:]:
        if path == keep_path:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


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
            if entry["heading"].startswith("Message: user") and is_real_user_prompt(entry["text"])
        ),
        "",
    )
    if not first_user:
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

    localized_turns = []
    for turn in parsed_transcript["turns"]:
        localized_turn = dict(turn)
        localized_turn["user_timestamp_local"] = format_local_timestamp(turn.get("user_timestamp"))
        localized_turn["final_answer_timestamp_local"] = format_local_timestamp(
            turn.get("final_answer_timestamp")
        )
        localized_turn["commentary"] = [
            {
                **item,
                "timestamp_local": format_local_timestamp(item.get("timestamp")),
            }
            for item in turn.get("commentary", [])
        ]
        localized_turn["tools"] = list(turn.get("tools", []))
        localized_turns.append(localized_turn)
    parsed_transcript["turns"] = localized_turns

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
    write_session_exports(project_dir, meta, parsed["turns"], transcript_path, args.html_backend)
    removed_duplicates = prune_duplicate_session_archives(archive_root, meta["session_id"])
    rebuild_project_index(project_dir)
    for removed in removed_duplicates:
        rebuild_project_index(removed.parent.parent)

    print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
