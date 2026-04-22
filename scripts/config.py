"""Path constants and configuration for the personal knowledge base."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
APP_ROOT = Path(__file__).resolve().parent.parent
# Backward-compatible alias used across scripts.
ROOT_DIR = APP_ROOT


def _expand_env_vars(raw: str) -> str:
    """Expand %VAR%, $VAR and ${VAR} placeholders across platforms."""

    def lookup_env(key: str) -> str | None:
        value = os.environ.get(key)
        if value is not None:
            return value
        if key == "HOME":
            return os.environ.get("USERPROFILE")
        if key == "USERPROFILE":
            return os.environ.get("HOME")
        return None

    def repl_percent(match: re.Match[str]) -> str:
        key = match.group(1)
        return lookup_env(key) or match.group(0)

    def repl_dollar(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return lookup_env(key) or match.group(0)

    value = re.sub(r"%([^%]+)%", repl_percent, raw)
    value = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([^}]+)\}", repl_dollar, value)
    return value


def _parse_path_override_from_agents(key: str) -> tuple[Path | None, bool]:
    """Read optional `<key>: <path>` override from AGENTS.md."""
    agents_file = APP_ROOT / "AGENTS.md"
    if not agents_file.exists():
        return None, False

    try:
        content = agents_file.read_text(encoding="utf-8")
    except OSError:
        return None, False

    in_code_block = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        match = re.match(rf"(?i)^{re.escape(key)}\s*[:=]\s*(.+?)\s*$", line)
        if not match:
            continue

        raw = match.group(1).strip().strip("'\"`")
        if not raw:
            return None, True

        expanded = _expand_env_vars(raw)
        path = Path(expanded).expanduser()
        return (path if path.is_absolute() else APP_ROOT / path), True
    return None, False


def _parse_path_override_from_env(key: str) -> tuple[Path | None, bool]:
    """Read optional `<key>` override from environment variables."""
    raw = os.environ.get(key)
    if raw is None:
        return None, False
    raw = raw.strip()
    if not raw:
        return None, True

    expanded = _expand_env_vars(raw)
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path, True


env_wiki_path, env_wiki_path_explicit = _parse_path_override_from_env("KB_WIKI_PATH")
agents_wiki_path, agents_wiki_path_explicit = _parse_path_override_from_agents("wiki_path")

if env_wiki_path_explicit:
    WIKI_PATH = env_wiki_path
    WIKI_PATH_EXPLICIT = True
    _wiki_path_source = "KB_WIKI_PATH"
else:
    WIKI_PATH = agents_wiki_path
    WIKI_PATH_EXPLICIT = agents_wiki_path_explicit
    _wiki_path_source = "AGENTS.md wiki_path"

if WIKI_PATH_EXPLICIT:
    if WIKI_PATH is None:
        raise RuntimeError(f"{_wiki_path_source} is explicitly set but is empty.")

    DAILY_DIR = WIKI_PATH / "daily"
    KNOWLEDGE_DIR = WIKI_PATH / "knowledge"
    for target in (DAILY_DIR, KNOWLEDGE_DIR):
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to create directories for explicit path override ({_wiki_path_source}). "
                f"wiki_path={WIKI_PATH}, target={target}, error={exc}"
            ) from exc
else:
    DAILY_DIR = ROOT_DIR / "daily"
    KNOWLEDGE_DIR = ROOT_DIR / "knowledge"
    for target in (DAILY_DIR, KNOWLEDGE_DIR):
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                "Failed to create project-local storage directories. "
                f"project_root={ROOT_DIR}, target={target}, error={exc}"
            ) from exc
CONCEPTS_DIR = KNOWLEDGE_DIR / "concepts"
CONNECTIONS_DIR = KNOWLEDGE_DIR / "connections"
QA_DIR = KNOWLEDGE_DIR / "qa"
REPORTS_DIR = ROOT_DIR / "reports"
SCRIPTS_DIR = ROOT_DIR / "scripts"
HOOKS_DIR = ROOT_DIR / "hooks"
AGENTS_FILE = ROOT_DIR / "AGENTS.md"

INDEX_FILE = KNOWLEDGE_DIR / "index.md"
LOG_FILE = KNOWLEDGE_DIR / "log.md"
STATE_FILE = SCRIPTS_DIR / "state.json"

# ── Timezone ───────────────────────────────────────────────────────────
TIMEZONE = "Europe/Moscow"


def now_iso() -> str:
    """Current time in ISO 8601 format."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    """Current date in ISO 8601 format."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
