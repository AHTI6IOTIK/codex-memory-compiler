"""
Memory flush worker for Codex transcript hooks.

Usage:
    uv run python scripts/flush.py <context_file.md> <session_id>
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import DAILY_DIR, ROOT_DIR, SCRIPTS_DIR, WIKI_PATH, WIKI_PATH_EXPLICIT
from llm import generate_text

# Recursion guard for hook-triggered subprocesses
os.environ["KB_INVOKED_BY"] = "memory_flush"


def _slugify_project_name(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "project"


def _project_slug() -> str:
    if WIKI_PATH_EXPLICIT and WIKI_PATH is not None:
        name = Path(WIKI_PATH).name
    else:
        name = ROOT_DIR.name
    return _slugify_project_name(name)


PROJECT_SLUG = _project_slug()
STATE_FILE = SCRIPTS_DIR / f"{PROJECT_SLUG}-last-flush.json"
LOG_FILE = SCRIPTS_DIR / f"{PROJECT_SLUG}-flush.log"
UV_BIN = ROOT_DIR / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

COMPILE_AFTER_HOUR = 18


def _shorten(text: str, limit: int = 220) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _build_fallback_summary(context: str, error: Exception) -> str:
    turns: list[tuple[str, str]] = []
    for raw in context.splitlines():
        line = raw.strip()
        if line.startswith("**User:** "):
            turns.append(("User", line[len("**User:** ") :].strip()))
        elif line.startswith("**Assistant:** "):
            turns.append(("Assistant", line[len("**Assistant:** ") :].strip()))

    recent = turns[-8:]
    key_lines = "\n".join(f"- `{role}`: {_shorten(text)}" for role, text in recent) if recent else "- (no parsed turns)"

    return (
        "**Context**\n"
        "- Session summary generated in fallback mode because the LLM backend was unavailable.\n"
        f"- Flush backend error: `{type(error).__name__}`.\n\n"
        "**Key Exchanges**\n"
        f"{key_lines}\n\n"
        "**Decisions Made**\n"
        "- (not inferred automatically in fallback mode)\n\n"
        "**Lessons Learned**\n"
        "- Memory flush should remain resilient even when external model calls fail.\n\n"
        "**Action Items**\n"
        "- Verify Codex CLI auth (`codex --login`) and executable resolution (`KB_CODEX_CMD`).\n"
    )


def load_flush_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_flush_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def append_to_daily_log(content: str, section: str = "Session") -> None:
    now = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{now.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {now.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    entry = f"### {section} ({now.strftime('%H:%M')})\n\n{content.strip()}\n\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


def run_flush(context: str) -> str:
    prompt = f"""Review the conversation context and extract only durable knowledge.

Return markdown with these sections (omit empty ones):
- **Context**
- **Key Exchanges**
- **Decisions Made**
- **Lessons Learned**
- **Action Items**

If there is nothing worth saving, return exactly: FLUSH_OK

## Conversation Context
{context}
"""
    return generate_text(prompt, reasoning_effort="low")


def maybe_trigger_compilation() -> None:
    now = datetime.now(timezone.utc).astimezone()
    if now.hour < COMPILE_AFTER_HOUR:
        return

    compile_script = SCRIPTS_DIR / "compile.py"
    if not compile_script.exists():
        return

    uv_cmd = str(UV_BIN) if UV_BIN.exists() else "uv"
    cmd = [uv_cmd, "run", "--directory", str(ROOT_DIR), "python", str(compile_script)]
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    child_env = os.environ.copy()
    child_env.setdefault("UV_CACHE_DIR", str(ROOT_DIR / ".uv-cache"))
    child_env.setdefault("UV_PYTHON_INSTALL_DIR", str(ROOT_DIR / ".uv-python"))
    child_env.setdefault("UV_TOOL_DIR", str(ROOT_DIR / ".uv-tools"))

    try:
        log_handle = open(str(SCRIPTS_DIR / f"{PROJECT_SLUG}-compile.log"), "a", encoding="utf-8")
        subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, cwd=str(ROOT_DIR), env=child_env, **kwargs)
        logging.info("Triggered background compilation")
    except Exception as e:
        logging.error("Failed to trigger compile.py: %s", e)


def main() -> None:
    if len(sys.argv) < 3:
        logging.error("Usage: %s <context_file.md> <session_id>", sys.argv[0])
        sys.exit(1)

    context_file = Path(sys.argv[1])
    session_id = sys.argv[2]

    if not context_file.exists():
        logging.error("Context file not found: %s", context_file)
        return

    state = load_flush_state()
    if state.get("session_id") == session_id and time.time() - state.get("timestamp", 0) < 60:
        logging.info("Skipping duplicate flush for session %s", session_id)
        context_file.unlink(missing_ok=True)
        return

    context = context_file.read_text(encoding="utf-8").strip()
    if not context:
        context_file.unlink(missing_ok=True)
        return

    try:
        response = run_flush(context)
    except Exception as e:
        logging.exception("run_flush failed: %s", e)
        response = _build_fallback_summary(context, e)

    if response == "FLUSH_OK":
        append_to_daily_log("FLUSH_OK - Nothing worth saving from this session", "Memory Flush")
    elif response.startswith("FLUSH_ERROR:"):
        append_to_daily_log(response, "Memory Flush")
    else:
        append_to_daily_log(response, "Session")

    save_flush_state({"session_id": session_id, "timestamp": time.time()})
    context_file.unlink(missing_ok=True)
    maybe_trigger_compilation()


if __name__ == "__main__":
    main()
