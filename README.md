# Codex Memory Compiler

Knowledge pipeline for Codex sessions:
`transcript -> daily -> compile -> knowledge`.

## Origin

This project was ported from:
[coleam00/claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler).

The current repository adapts the workflow for Codex App/CLI hooks and Codex-compatible runtime behavior.

## What It Does

- Captures session context from Codex hooks (`SessionStart`, `Stop`)
- Flushes durable memory into `daily/YYYY-MM-DD.md`
- Compiles `daily/` logs into structured `knowledge/` articles
- Supports querying and linting the compiled knowledge base

## Requirements

- Python `>=3.12`
- `uv`
- Codex CLI (`codex --login`)

Runtime dependencies (from `pyproject.toml`):
- `openai>=2.0.0`
- `python-dotenv>=1.0.0`
- `tzdata>=2024.1`

Version locking:
- `uv.lock` stores the resolved dependency graph used by `uv sync`.

## Setup

1. Clone once (single central compiler instance).

Windows (PowerShell):
```powershell
git clone https://github.com/AHTI6IOTIK/codex-memory-compiler.git "$HOME\ai-tools\codex-memory-compiler"
cd "$HOME\ai-tools\codex-memory-compiler"
```

Unix-like (bash/zsh):
```bash
git clone https://github.com/AHTI6IOTIK/codex-memory-compiler.git ~/ai-tools/codex-memory-compiler
cd ~/ai-tools/codex-memory-compiler
```

2. Install dependencies:
```bash
uv sync
```

3. Enable Codex hooks in config.

You can enable hooks globally or per project:
- Global config (recommended): applies to all projects
- Local project config: applies only to the current project
Global config location:
- Windows: `%USERPROFILE%\.codex\config.toml`
- Unix-like: `~/.codex/config.toml`

```toml
suppress_unstable_features_warning = true

[features]
codex_hooks = true
```

4. Set storage root (optional) in `AGENTS.md` (top-level line, outside code blocks):

Windows:
```text
wiki_path: D:\codex-memory
```

Unix-like:
```text
wiki_path: /home/you/codex-memory
```

If `wiki_path` is not set, storage defaults to project root:
- `<project_root>/daily`
- `<project_root>/knowledge`

When hooks run globally, they automatically derive `<project_root>` from the active Codex session `cwd` (git toplevel when available), so logs are written to the project you are currently working in.

`KB_WIKI_PATH` environment variable has highest priority for direct script runs (`compile/lint/query`) and overrides `wiki_path`.
For Codex hooks (`SessionStart`/`Stop`), storage root is always derived from the hook event `cwd` (git toplevel when available) to prevent cross-session leakage between simultaneously opened projects.

This stores:
- `daily` in `<wiki_path>/daily`
- `knowledge` in `<wiki_path>/knowledge`

When `wiki_path` is explicitly set, runtime tries to create:
- `<wiki_path>/daily`
- `<wiki_path>/knowledge`

If creation fails (permissions/path issues), runtime stops with a clear configuration error.

5. Configure backend (Codex OAuth mode):

Windows (PowerShell):
```powershell
$env:KB_MODEL="gpt-5-codex"
$env:KB_BACKEND="codex"
$env:KB_CODEX_CMD="codex"
```

Unix-like (bash/zsh):
```bash
export KB_MODEL=gpt-5-codex
export KB_BACKEND=codex
export KB_CODEX_CMD=codex
```

## Hooks

Use template: [.codex/hooks.global.example.json](.codex/hooks.global.example.json)

Replace `<MEMORY_COMPILER_ROOT>` with absolute path:
- Windows example: `$HOME\ai-tools\codex-memory-compiler`
- Unix-like example: `$HOME/ai-tools/codex-memory-compiler`

Per-project opt-in:
- Create `.codex-memory-enable` in the target project root.

SessionStart context verbosity:
- `SessionStart` always reports Memory Compiler status in `additionalContext`:
  - `Статус: вкл` when `.codex-memory-enable` exists in project root
  - `Статус: выкл` when marker file is missing
- `SessionStart` injects knowledge context (index + recent daily log) when enabled.

## One-line Commands via Codex

Important:
- `--cd` points to the compiler code location (`codex-memory-compiler`).
- `KB_WIKI_PATH` points to the target project where `daily/` and `knowledge/` are read/written.
- Run commands from the target project directory so `KB_WIKI_PATH="$PWD"` points to that repo.
- Set env vars inline before each script command invocation.
- With `--dangerously-bypass-approvals-and-sandbox`, `UV_CACHE_DIR` is optional (keep it only if you want explicit uv cache location).

Windows (PowerShell):
```powershell
$env:KB_WIKI_PATH="$PWD"; codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME\ai-tools\codex-memory-compiler" "uv run python scripts/compile.py"
$env:KB_WIKI_PATH="$PWD"; codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME\ai-tools\codex-memory-compiler" "uv run python scripts/lint.py --structural-only"
$env:KB_WIKI_PATH="$PWD"; codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME\ai-tools\codex-memory-compiler" "uv run python scripts/query.py `"What auth patterns do I use?`""
```

Unix-like (bash/zsh):
```bash
KB_WIKI_PATH="$PWD" codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME/ai-tools/codex-memory-compiler" "uv run python scripts/compile.py"
KB_WIKI_PATH="$PWD" codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME/ai-tools/codex-memory-compiler" "uv run python scripts/lint.py --structural-only"
KB_WIKI_PATH="$PWD" codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME/ai-tools/codex-memory-compiler" "uv run python scripts/query.py \"What auth patterns do I use?\""
```

Unix-like (fish):
```fish
env KB_WIKI_PATH=(pwd) codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME/ai-tools/codex-memory-compiler" "uv run python scripts/compile.py"
env KB_WIKI_PATH=(pwd) codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME/ai-tools/codex-memory-compiler" "uv run python scripts/lint.py --structural-only"
env KB_WIKI_PATH=(pwd) codex exec --dangerously-bypass-approvals-and-sandbox --cd "$HOME/ai-tools/codex-memory-compiler" "uv run python scripts/query.py \"What auth patterns do I use?\""
```

What they do:
- `compile.py` - compiles new/changed `daily/*.md` logs into structured `knowledge/*` articles.
- `lint.py --structural-only` - runs free structural checks (links/orphans/staleness/backlinks/sparsity) without LLM contradiction check.
- `query.py "..."` - asks the compiled knowledge base and returns an answer from current `knowledge/*` content.

When to run:
- Run `compile.py` after new session logs are flushed (or before querying if you want latest notes included).
- Run `lint.py --structural-only` after compile or before commit/push to catch KB integrity issues.
- Run `query.py` when you need fast recall of patterns/decisions already captured in memory.

## Core Commands

```bash
uv run python scripts/compile.py
uv run python scripts/query.py "question"
uv run python scripts/query.py "question" --file-back
uv run python scripts/lint.py
uv run python scripts/lint.py --structural-only
```

```fish
env KB_WIKI_PATH=(pwd) uv run python scripts/compile.py
env KB_WIKI_PATH=(pwd) uv run python scripts/query.py "question"
env KB_WIKI_PATH=(pwd) uv run python scripts/query.py "question" --file-back
env KB_WIKI_PATH=(pwd) uv run python scripts/lint.py
env KB_WIKI_PATH=(pwd) uv run python scripts/lint.py --structural-only
```

## Manual Ingest Fallback

If hooks are unavailable in your environment:

```bash
uv run python scripts/ingest_codex_transcript.py
```

## Logs and State Files

Storage location depends on `KB_WIKI_PATH` (or `wiki_path` in `AGENTS.md`):
- Daily source logs: `<wiki_root>/daily/YYYY-MM-DD.md`
- Compiled KB index/log/articles: `<wiki_root>/knowledge/*`

Runtime files live in the compiler repo:
- Lint reports: `reports/<project>-lint-YYYY-MM-DD.md`
- Hook runtime logs/state (project-prefixed):
  - `scripts/<project>-flush.log`
  - `scripts/<project>-compile.log`
  - `scripts/<project>-last-flush.json`
  - `scripts/<project>-manual-context-<session>-<timestamp>.md` (temporary/manual ingest context)
- Stop hook temporary context handoff:
  - `scripts/stop-context-<session>-<timestamp>.md` (created by `hooks/stop.py`, then removed by `flush.py`)
- Stop hook logger: `scripts/flush.log` (hook-level diagnostics)
- Global compiler state: `scripts/state.json` (ingested hashes, query count, total cost, last lint)

How `<project>` is derived:
- If `KB_WIKI_PATH`/`wiki_path` is set: basename of that path (example: `.../b2b-casbin-server` -> `b2b-casbin-server`)
- Otherwise: compiler repo folder name (`codex-memory-compiler`)

## Optional OpenAI API Key Mode

Windows (PowerShell):
```powershell
$env:KB_BACKEND="openai"
$env:OPENAI_API_KEY="..."
```

Unix-like (bash/zsh):
```bash
export KB_BACKEND=openai
export OPENAI_API_KEY=...
```
