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
git clone <repo-url> D:\tools\memory-compiler
cd D:\tools\memory-compiler
```

Unix-like (bash/zsh):
```bash
git clone <repo-url> ~/tools/memory-compiler
cd ~/tools/memory-compiler
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
[features]
codex_hooks = true
suppress_unstable_features_warning = true
```

4. Set storage root in `AGENTS.md` (top-level line, outside code blocks):

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
- Windows example: `D:\tools\memory-compiler`
- Unix-like example: `/home/you/tools/memory-compiler`

Per-project opt-out:
- Create `.codex-memory-disable` in the target project root.

## One-line Commands via Codex

Windows (PowerShell):
```powershell
codex exec --cd "D:\tools\memory-compiler" "uv run python scripts/compile.py"
codex exec --cd "D:\tools\memory-compiler" "uv run python scripts/lint.py --structural-only"
codex exec --cd "D:\tools\memory-compiler" "uv run python scripts/query.py `"What auth patterns do I use?`""
```

Unix-like (bash/zsh):
```bash
codex exec --cd "/home/you/tools/memory-compiler" "uv run python scripts/compile.py"
codex exec --cd "/home/you/tools/memory-compiler" "uv run python scripts/lint.py --structural-only"
codex exec --cd "/home/you/tools/memory-compiler" "uv run python scripts/query.py \"What auth patterns do I use?\""
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

## Manual Ingest Fallback

If hooks are unavailable in your environment:

```bash
uv run python scripts/ingest_codex_transcript.py
```

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
