"""
Codex Stop hook - captures transcript context and flushes it to daily memory.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("KB_INVOKED_BY"):
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATE_DIR = SCRIPTS_DIR
UV_BIN = ROOT / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "flush.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [stop-hook] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MAX_TURNS = 40
MAX_CONTEXT_CHARS = 20_000
MIN_TURNS_TO_FLUSH = 1
DISABLE_MARKER = ".codex-memory-disable"


def _is_disabled(hook_input: dict) -> bool:
    cwd = hook_input.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return False
    return (Path(cwd) / DISABLE_MARKER).exists()


def _resolve_wiki_root(hook_input: dict) -> Path | None:
    """Resolve storage root from hook cwd (prefer git toplevel)."""
    cwd = hook_input.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return None

    base = Path(cwd).expanduser()
    if not base.exists():
        return None

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(base),
            capture_output=True,
            text=True,
            check=True,
        )
        resolved = proc.stdout.strip()
        if resolved:
            return Path(resolved)
    except Exception:
        pass

    return base


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
        boundary = context.find("\n**")
        if boundary > 0:
            context = context[boundary + 1 :]
    return context, len(recent)


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as e:
        logging.error("Failed to parse hook stdin: %s", e)
        return

    if _is_disabled(hook_input):
        logging.info("SKIP: memory compiler disabled by marker file")
        return

    session_id = str(hook_input.get("session_id", "unknown"))
    transcript_path_str = hook_input.get("transcript_path")
    if not isinstance(transcript_path_str, str) or not transcript_path_str:
        logging.info("SKIP: no transcript path")
        return

    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        logging.info("SKIP: transcript missing: %s", transcript_path)
        return

    try:
        context, turn_count = extract_conversation_context(transcript_path)
    except Exception as e:
        logging.error("Context extraction failed: %s", e)
        return

    if not context.strip() or turn_count < MIN_TURNS_TO_FLUSH:
        logging.info("SKIP: empty or too few turns")
        return

    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = STATE_DIR / f"stop-context-{session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")

    flush_script = SCRIPTS_DIR / "flush.py"
    uv_cmd = str(UV_BIN) if UV_BIN.exists() else "uv"
    cmd = [
        uv_cmd,
        "run",
        "--directory",
        str(ROOT),
        "python",
        str(flush_script),
        str(context_file),
        session_id,
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    child_env = os.environ.copy()
    # Always bind storage root to the hook event cwd/git root to avoid
    # cross-session leakage when KB_WIKI_PATH is exported in a parent shell.
    wiki_root = _resolve_wiki_root(hook_input)
    if wiki_root is not None:
        child_env["KB_WIKI_PATH"] = str(wiki_root)
    child_env.setdefault("UV_CACHE_DIR", str(ROOT / ".uv-cache"))
    child_env.setdefault("UV_PYTHON_INSTALL_DIR", str(ROOT / ".uv-python"))
    child_env.setdefault("UV_TOOL_DIR", str(ROOT / ".uv-tools"))
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            env=child_env,
        )
        if wiki_root is not None:
            logging.info("Spawned flush.py from Stop for session %s (wiki_root=%s)", session_id, wiki_root)
        else:
            logging.info("Spawned flush.py from Stop for session %s", session_id)
    except Exception as e:
        logging.error("Failed to spawn flush.py: %s", e)


if __name__ == "__main__":
    main()
