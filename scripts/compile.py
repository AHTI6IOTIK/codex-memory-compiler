"""
Compile daily logs into knowledge base markdown articles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import CONCEPTS_DIR, DAILY_DIR, KNOWLEDGE_DIR, LOG_FILE, now_iso
from llm import generate_json
from utils import file_hash, list_raw_files, list_wiki_articles, load_state, read_wiki_index, save_state

ROOT_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = KNOWLEDGE_DIR / "index.md"


def ensure_knowledge_base_files() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        INDEX_PATH.write_text(
            "# Knowledge Base Index\n\n| Article | Summary | Compiled From | Updated |\n|---------|---------|---------------|---------|\n",
            encoding="utf-8",
        )
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# Build Log\n\n", encoding="utf-8")


def _as_slug(text: str) -> str:
    text = text.lower().strip().replace(" ", "-")
    return "".join(ch for ch in text if ch.isalnum() or ch == "-").strip("-")


def build_compile_prompt(log_path: Path, log_content: str, index_content: str) -> str:
    return f"""You are compiling a personal coding knowledge base.

Return STRICT JSON with this shape:
{{
  "concepts": [
    {{
      "slug": "kebab-case",
      "title": "Article Title",
      "summary": "One-line index summary",
      "key_points": ["...", "..."],
      "details": ["paragraph 1", "paragraph 2"],
      "related_concepts": ["concepts/other-slug"],
      "source_claims": ["fact from the daily log"]
    }}
  ]
}}

Requirements:
- 1-5 concepts only.
- Slugs must be stable and kebab-case.
- Keep claims factual and specific.
- If there is no meaningful knowledge, return {{"concepts":[]}}.

## Current Index
{index_content}

## Daily Log ({log_path.name})
{log_content}
"""


def render_article(concept: dict, source_file: str, timestamp: str) -> str:
    slug = concept["slug"]
    title = concept["title"]
    key_points = concept.get("key_points", [])
    details = concept.get("details", [])
    related = concept.get("related_concepts", [])
    claims = concept.get("source_claims", [])

    kp = "\n".join(f"- {p}" for p in key_points) if key_points else "- (none)"
    detail_text = "\n\n".join(details) if details else "(no details)"
    related_text = "\n".join(f"- [[{r}]]" for r in related) if related else "- (none)"
    claim_text = "\n".join(f"- {c}" for c in claims) if claims else "- (none)"

    return f"""---
title: {title}
sources:
  - daily/{source_file}
created: {timestamp}
updated: {timestamp}
---

# {title}

## Key Points
{kp}

## Details
{detail_text}

## Related Concepts
{related_text}

## Sources
- [[daily/{source_file}]]
### Claims Extracted
{claim_text}
"""


def upsert_index_rows(rows: list[tuple[str, str, str, str]]) -> None:
    content = INDEX_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()
    existing = [ln for ln in lines if ln.startswith("| [[")]

    # Keep latest row per article.
    by_article: dict[str, str] = {}
    for line in existing:
        key = line.split("|")[1].strip()
        by_article[key] = line
    for article, summary, source, updated in rows:
        by_article[f"[[{article}]]"] = f"| [[{article}]] | {summary} | {source} | {updated} |"

    header = [
        "# Knowledge Base Index",
        "",
        "| Article | Summary | Compiled From | Updated |",
        "|---------|---------|---------------|---------|",
    ]
    merged = header + sorted(by_article.values())
    INDEX_PATH.write_text("\n".join(merged) + "\n", encoding="utf-8")


def append_build_log(log_name: str, created: list[str], updated: list[str], timestamp: str) -> None:
    lines = [
        f"## [{timestamp}] compile | {log_name}",
        f"- Source: daily/{log_name}",
        f"- Articles created: {', '.join(created) if created else '(none)'}",
        f"- Articles updated: {', '.join(updated) if updated else '(none)'}",
        "",
    ]
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def compile_daily_log(log_path: Path, state: dict) -> None:
    ensure_knowledge_base_files()
    log_content = log_path.read_text(encoding="utf-8")
    index_content = read_wiki_index()
    prompt = build_compile_prompt(log_path, log_content, index_content)
    try:
        payload = generate_json(prompt, reasoning_effort="medium")
    except Exception as e:
        print(f"  Error during compilation: {e}")
        return

    concepts = payload.get("concepts", [])
    created: list[str] = []
    updated: list[str] = []
    index_rows: list[tuple[str, str, str, str]] = []
    timestamp = now_iso()
    short_date = timestamp[:10]

    for concept in concepts:
        raw_slug = str(concept.get("slug", "")).strip()
        raw_title = str(concept.get("title", "")).strip()
        raw_summary = str(concept.get("summary", "")).strip()
        if not raw_slug or not raw_title or not raw_summary:
            continue

        slug = _as_slug(raw_slug)
        concept["slug"] = slug
        article_rel = f"concepts/{slug}"
        article_path = CONCEPTS_DIR / f"{slug}.md"
        was_existing = article_path.exists()
        article_path.write_text(render_article(concept, log_path.name, timestamp), encoding="utf-8")
        if was_existing:
            updated.append(f"[[{article_rel}]]")
        else:
            created.append(f"[[{article_rel}]]")
        index_rows.append((article_rel, raw_summary, f"daily/{log_path.name}", short_date))

    if index_rows:
        upsert_index_rows(index_rows)
    append_build_log(log_path.name, created, updated, timestamp)

    state.setdefault("ingested", {})[log_path.name] = {
        "hash": file_hash(log_path),
        "compiled_at": timestamp,
        "cost_usd": 0.0,
    }
    save_state(state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile daily logs into knowledge articles")
    parser.add_argument("--all", action="store_true", help="Force recompile all logs")
    parser.add_argument("--file", type=str, help="Compile a specific daily log file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be compiled")
    args = parser.parse_args()

    state = load_state()
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = DAILY_DIR / target.name
        if not target.exists():
            target = ROOT_DIR / args.file
        if not target.exists():
            print(f"Error: {args.file} not found")
            sys.exit(1)
        to_compile = [target]
    else:
        all_logs = list_raw_files()
        if args.all:
            to_compile = all_logs
        else:
            to_compile = []
            for log_path in all_logs:
                prev = state.get("ingested", {}).get(log_path.name, {})
                if not prev or prev.get("hash") != file_hash(log_path):
                    to_compile.append(log_path)

    if not to_compile:
        print("Nothing to compile - all daily logs are up to date.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Files to compile ({len(to_compile)}):")
    for f in to_compile:
        print(f"  - {f.name}")
    if args.dry_run:
        return

    for i, log_path in enumerate(to_compile, 1):
        print(f"\n[{i}/{len(to_compile)}] Compiling {log_path.name}...")
        compile_daily_log(log_path, state)
        print("  Done.")

    print(f"\nCompilation complete. Knowledge base: {len(list_wiki_articles())} articles")


if __name__ == "__main__":
    main()
