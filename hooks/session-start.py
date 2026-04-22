"""
SessionStart hook - injects knowledge base context into every conversation.

This is the "context injection" layer. When Codex starts a session,
this hook reads the knowledge base index and recent daily log, then injects
them as additional context so Codex always "remembers" what it has learned.

Configure for Codex in `.codex/hooks.json` using the SessionStart event.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Paths relative to project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MAX_CONTEXT_CHARS = 20_000
MAX_LOG_LINES = 30
ENABLE_MARKER = ".codex-memory-enable"
SESSIONSTART_MODE_ENV = "KB_SESSIONSTART_CONTEXT_MODE"


def _parse_hook_input() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _is_enabled(hook_input: dict) -> bool:
    cwd = hook_input.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return False
    return (Path(cwd) / ENABLE_MARKER).exists()


def _status_context(enabled: bool) -> str:
    status = "вкл" if enabled else "выкл"
    return f"## Memory Compiler\nСтатус: {status} (по файлу .codex-memory-enable)"


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


def get_recent_log(daily_dir: Path) -> str:
    """Read the most recent daily log (today or yesterday)."""
    today = datetime.now(timezone.utc).astimezone()

    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = daily_dir / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            # Return last N lines to keep context small
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)

    return "(no recent daily log)"


def _extract_index_rows(index_content: str, limit: int = 5) -> list[str]:
    rows: list[str] = []
    for line in index_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("| [["):
            rows.append(stripped)
            if len(rows) >= limit:
                break
    return rows


def build_context(daily_dir: Path, index_file: Path) -> str:
    """Assemble the context to inject into the conversation."""
    parts = []

    # Today's date
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    # Knowledge base index (the core retrieval mechanism)
    if index_file.exists():
        index_content = index_file.read_text(encoding="utf-8")
        parts.append(f"## Knowledge Base Index\n\n{index_content}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")

    # Recent daily log
    recent_log = get_recent_log(daily_dir)
    parts.append(f"## Recent Daily Log\n\n{recent_log}")

    context = "\n\n---\n\n".join(parts)

    # Truncate if too long
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"

    return context


def build_minimal_context(daily_dir: Path, index_file: Path) -> str:
    """Build compact context to avoid noisy hook banners in Codex UI."""
    parts = []

    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    if index_file.exists():
        index_content = index_file.read_text(encoding="utf-8")
        rows = _extract_index_rows(index_content, limit=5)
        if rows:
            parts.append("## Knowledge Highlights\n" + "\n".join(rows))
        else:
            parts.append("## Knowledge Highlights\n(index has no article rows yet)")
    else:
        parts.append("## Knowledge Highlights\n(index file not found)")

    recent_log = get_recent_log(daily_dir)
    parts.append(f"## Recent Daily Log\n\n{recent_log}")
    return "\n\n---\n\n".join(parts)


def main():
    hook_input = _parse_hook_input()
    enabled = _is_enabled(hook_input)

    if not enabled:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": _status_context(enabled=False),
                    }
                }
            )
        )
        return

    # Always bind storage root to the hook event cwd/git root to avoid
    # cross-session leakage when KB_WIKI_PATH is exported in a parent shell.
    wiki_root = _resolve_wiki_root(hook_input)
    if wiki_root is not None:
        os.environ["KB_WIKI_PATH"] = str(wiki_root)

    from config import DAILY_DIR, INDEX_FILE

    mode = os.environ.get(SESSIONSTART_MODE_ENV, "off").strip().lower()
    if mode == "full":
        context = "\n\n---\n\n".join([_status_context(enabled=True), build_context(DAILY_DIR, INDEX_FILE)])
    elif mode == "off":
        context = _status_context(enabled=True)
    else:
        context = "\n\n---\n\n".join(
            [_status_context(enabled=True), build_minimal_context(DAILY_DIR, INDEX_FILE)]
        )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
