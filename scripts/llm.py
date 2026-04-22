"""LLM backend helpers for OpenAI API key or Codex OAuth execution."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
# Load env from repo and optional parent workspace root.
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")


def _load_bom_tolerant_env(path: Path) -> None:
    if not path.exists():
        return
    for key, value in dotenv_values(path).items():
        if key is None or value is None:
            continue
        normalized_key = key.lstrip("\ufeff")
        if normalized_key not in os.environ:
            os.environ[normalized_key] = value


_load_bom_tolerant_env(ROOT / ".env")
_load_bom_tolerant_env(ROOT.parent / ".env")

DEFAULT_MODEL = os.environ.get("KB_MODEL", "gpt-5-codex")
DEFAULT_BACKEND = os.environ.get("KB_BACKEND", "auto").strip().lower()
CODEX_BIN = os.environ.get("KB_CODEX_CMD", "codex")


def _client() -> OpenAI:
    return OpenAI()


def _resolve_backend() -> str:
    backend = DEFAULT_BACKEND or "auto"
    if backend not in {"auto", "openai", "codex"}:
        return "auto"
    if backend == "auto":
        # Prefer subscription/OAuth path by default; OpenAI API key remains available explicitly.
        return "codex"
    return backend


def _is_openai_auth_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "api_key client option must be set",
            "incorrect api key",
            "invalid api key",
            "401",
            "authentication",
        )
    )


def _extract_text_from_json_event(event: dict[str, Any]) -> str:
    value: Any = event.get("message")
    if isinstance(value, str):
        return value.strip()

    value = event.get("content")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block.strip())
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text.strip())
        return "\n".join([p for p in parts if p])
    return ""


def _extract_text_from_item(item: dict[str, Any]) -> str:
    value: Any = item.get("text")
    if isinstance(value, str):
        return value.strip()

    value = item.get("content")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block.strip())
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text.strip())
        return "\n".join([p for p in parts if p])
    return ""


def _normalize_cmd_parts(command: str) -> list[str]:
    value = command.strip()
    if not value:
        return ["codex"]
    return shlex.split(value, posix=False)


def _resolve_windows_npm_shim(exe_name: str) -> Path | None:
    npm_bin = Path.home() / "AppData" / "Roaming" / "npm"
    for candidate in (
        npm_bin / f"{exe_name}.cmd",
        npm_bin / f"{exe_name}.exe",
        npm_bin / f"{exe_name}.ps1",
    ):
        if candidate.exists():
            return candidate
    return None


def _resolve_codex_invocation() -> list[str]:
    parts = _normalize_cmd_parts(CODEX_BIN)
    exe = parts[0]
    tail = parts[1:]

    direct = Path(exe)
    if direct.exists():
        if sys.platform == "win32" and direct.suffix.lower() == ".ps1":
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(direct), *tail]
        return [str(direct), *tail]

    resolved = shutil.which(exe)
    if resolved:
        path = Path(resolved)
        if sys.platform == "win32" and path.suffix.lower() == ".ps1":
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *tail]
        return [resolved, *tail]

    if sys.platform == "win32":
        shim = _resolve_windows_npm_shim(exe)
        if shim:
            if shim.suffix.lower() == ".ps1":
                return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(shim), *tail]
            return [str(shim), *tail]

    return [exe, *tail]


def _extract_assistant_text(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", ""))
    if event_type in {"agent_message", "assistant_message", "message"}:
        return _extract_text_from_json_event(event)

    if event_type == "item.completed":
        item = event.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type", ""))
            if item_type in {"agent_message", "assistant_message", "message"}:
                return _extract_text_from_item(item)

    # Codex JSON stream may wrap messages in response_item payload records.
    payload = event.get("payload")
    if event_type == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            return _extract_text_from_json_event(payload)

    return ""


def _prepare_codex_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    # Nested `codex exec` inside Codex sandbox often cannot write to ~/.codex/sessions.
    # Redirect nested Codex state to a writable location under ~/.codex/memories.
    if env.get("CODEX_SANDBOX") and not env.get("CODEX_HOME"):
        codex_root = Path.home() / ".codex"
        nested_home = codex_root / "memories" / "nested-codex-home"
        nested_home.mkdir(parents=True, exist_ok=True)
        for name in ("auth.json", "config.toml", "installation_id", "version.json", "models_cache.json"):
            src = codex_root / name
            dst = nested_home / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
        env["CODEX_HOME"] = str(nested_home)
    return env


def _generate_text_with_codex(prompt: str) -> str:
    """Run Codex CLI in non-interactive mode and return the assistant response text."""
    cmd = [
        *_resolve_codex_invocation(),
        "exec",
        "--json",
        "--cd",
        str(ROOT),
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_prepare_codex_subprocess_env(),
            check=False,
        )
    except OSError as e:
        raise RuntimeError(
            "failed to execute codex CLI. Ensure OAuth login is completed (`codex --login`) "
            "and set KB_CODEX_CMD to a runnable codex binary path if needed. "
            f"attempted command: {' '.join(cmd[:3])}"
        ) from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        raise RuntimeError(f"codex exec failed: {detail}")

    raw_lines = (proc.stdout or "").splitlines()
    messages: list[str] = []
    json_events_seen = 0
    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        json_events_seen += 1
        text = _extract_assistant_text(event)
        if text:
            messages.append(text)

    if messages:
        return "\n".join(messages).strip()

    if json_events_seen > 0:
        raise RuntimeError("codex exec returned JSON events without assistant message content")

    # Fallback for non-JSON output shapes
    text = (proc.stdout or "").strip()
    if text:
        return text
    raise RuntimeError("codex exec returned no assistant message")


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    reasoning_effort: str = "medium",
) -> str:
    """Generate a plain-text response via OpenAI Responses API."""
    backend = _resolve_backend()
    if backend == "codex":
        merged_prompt = prompt if not system else f"System instructions:\n{system}\n\nUser prompt:\n{prompt}"
        return _generate_text_with_codex(merged_prompt)

    try:
        client = _client()
        selected_model = model or DEFAULT_MODEL

        input_items: list[dict[str, Any]] = []
        if system:
            input_items.append({"role": "system", "content": system})
        input_items.append({"role": "user", "content": prompt})

        response = client.responses.create(
            model=selected_model,
            input=input_items,
            reasoning={"effort": reasoning_effort},
        )
        text = getattr(response, "output_text", None)
        return (text or "").strip()
    except Exception as e:
        if _is_openai_auth_error(e):
            merged_prompt = prompt if not system else f"System instructions:\n{system}\n\nUser prompt:\n{prompt}"
            return _generate_text_with_codex(merged_prompt)
        raise


def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    reasoning_effort: str = "medium",
) -> dict[str, Any]:
    """Generate JSON response and parse it into a dict."""
    raw = generate_text(
        prompt,
        system=system,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    return json.loads(raw)
