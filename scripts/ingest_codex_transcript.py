"""
Windows-friendly fallback when Codex hooks are unavailable.

Reads a Codex transcript (or latest rollout), extracts recent dialogue,
and invokes flush.py to append memory to daily logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
UV_BIN = ROOT / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")

MAX_TURNS = 40
MAX_CONTEXT_CHARS = 20_000


def _slugify_project_name(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "project"


def _project_slug() -> str:
    wiki_path = os.environ.get("KB_WIKI_PATH", "").strip()
    if wiki_path:
        return _slugify_project_name(Path(wiki_path).expanduser().name)
    return _slugify_project_name(ROOT.name)


def find_latest_rollout() -> Path | None:
    codex_home = Path.home() / ".codex"
    sessions = codex_home / "sessions"
    if not sessions.exists():
        return None
    candidates = sorted(sessions.glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block.strip())
            elif isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    parts.append(block["text"].strip())
                elif isinstance(block.get("content"), str):
                    parts.append(block["content"].strip())
        return "\n".join(p for p in parts if p)
    return ""


def _extract_turn(entry: dict) -> tuple[str, object]:
    # Legacy nested transcript entries
    msg = entry.get("message", {})
    if isinstance(msg, dict):
        role = str(msg.get("role", ""))
        if role in ("user", "assistant"):
            return role, msg.get("content", "")

    # Flat fallback entries
    role = entry.get("role")
    if isinstance(role, str) and role in ("user", "assistant"):
        return role, entry.get("content", "")

    # Codex rollout format: {"type":"response_item","payload":{"type":"message","role":...}}
    entry_type = entry.get("type")
    payload = entry.get("payload")
    if entry_type == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "message":
            payload_role = payload.get("role")
            if isinstance(payload_role, str) and payload_role in ("user", "assistant"):
                return payload_role, payload.get("content", "")

    return "", ""


def extract_conversation_context(transcript_path: Path) -> tuple[str, int]:
    turns: list[str] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            role, content = _extract_turn(entry)
            if role not in ("user", "assistant"):
                continue

            text = _extract_text(content)
            if not text:
                continue
            label = "User" if role == "user" else "Assistant"
            turns.append(f"**{label}:** {text}\n")

    recent = turns[-MAX_TURNS:]
    context = "\n".join(recent)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[-MAX_CONTEXT_CHARS:]
    return context, len(recent)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Codex transcript into daily KB log")
    parser.add_argument("--transcript", help="Path to transcript JSONL. Defaults to latest Codex rollout.")
    parser.add_argument("--session-id", default="manual-ingest", help="Optional session id override")
    args = parser.parse_args()

    transcript = Path(args.transcript) if args.transcript else find_latest_rollout()
    if not transcript or not transcript.exists():
        print("No transcript found. Pass --transcript or ensure ~/.codex/sessions exists.")
        sys.exit(1)

    context, turn_count = extract_conversation_context(transcript)
    if not context.strip() or turn_count == 0:
        print("No user/assistant turns found in transcript.")
        return

    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = SCRIPTS_DIR / f"{_project_slug()}-manual-context-{args.session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")

    flush_script = SCRIPTS_DIR / "flush.py"
    uv_cmd = str(UV_BIN) if UV_BIN.exists() else "uv"
    cmd = [uv_cmd, "run", "--directory", str(ROOT), "python", str(flush_script), str(context_file), args.session_id]
    subprocess.run(cmd, check=True)
    print(f"Ingested transcript: {transcript}")


if __name__ == "__main__":
    main()
