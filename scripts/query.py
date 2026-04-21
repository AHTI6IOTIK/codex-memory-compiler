"""Query the knowledge base using OpenAI/Codex models."""

from __future__ import annotations

import argparse
from pathlib import Path

from config import KNOWLEDGE_DIR, QA_DIR, now_iso
from llm import generate_text
from utils import load_state, read_all_wiki_content, save_state, slugify

ROOT_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = KNOWLEDGE_DIR / "index.md"
LOG_PATH = KNOWLEDGE_DIR / "log.md"


def run_query(question: str) -> str:
    wiki_content = read_all_wiki_content()
    prompt = f"""You are a knowledge base query engine.

Answer the question using only the knowledge base below.
If the KB has insufficient information, say that directly.
Use wikilink citations like [[concepts/example]].

## Knowledge Base
{wiki_content}

## Question
{question}
"""
    return generate_text(prompt, reasoning_effort="medium")


def file_back_answer(question: str, answer: str) -> Path:
    timestamp = now_iso()
    slug = slugify(question) or "question"
    qa_path = QA_DIR / f"{slug}.md"
    QA_DIR.mkdir(parents=True, exist_ok=True)

    qa_path.write_text(
        f"""---
title: Q&A - {question}
question: {question}
filed: {timestamp}
---

# Question
{question}

# Answer
{answer}
""",
        encoding="utf-8",
    )

    if INDEX_PATH.exists():
        index = INDEX_PATH.read_text(encoding="utf-8")
    else:
        index = "# Knowledge Base Index\n\n| Article | Summary | Compiled From | Updated |\n|---------|---------|---------------|---------|\n"
    row = f"| [[qa/{slug}]] | Filed Q&A | query | {timestamp[:10]} |"
    if row not in index:
        if not index.endswith("\n"):
            index += "\n"
        index += row + "\n"
        INDEX_PATH.write_text(index, encoding="utf-8")

    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("# Build Log\n\n", encoding="utf-8")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(
            f"## [{timestamp}] query (filed)\n"
            f"- Question: {question}\n"
            f"- Filed to: [[qa/{slug}]]\n\n"
        )
    return qa_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the personal knowledge base")
    parser.add_argument("question", help="The question to ask")
    parser.add_argument("--file-back", action="store_true", help="Save answer into knowledge/qa")
    args = parser.parse_args()

    print(f"Question: {args.question}")
    print(f"File back: {'yes' if args.file_back else 'no'}")
    print("-" * 60)

    try:
        answer = run_query(args.question)
    except Exception as e:
        answer = f"Error querying knowledge base: {e}"
    print(answer)

    state = load_state()
    state["query_count"] = state.get("query_count", 0) + 1
    save_state(state)

    if args.file_back:
        qa_path = file_back_answer(args.question, answer)
        print("\n" + "-" * 60)
        print(f"Answer filed to: {qa_path}")


if __name__ == "__main__":
    main()
