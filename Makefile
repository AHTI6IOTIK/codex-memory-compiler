.PHONY: help compile lint lint-structural query query-file-back

PYTHON ?= python
UV ?= uv run
KB_WIKI_PATH ?= $(CURDIR)
QUERY ?= What auth patterns do I use?

help:
	@echo "Targets:"
	@echo "  make compile                 # Compile new/changed daily logs"
	@echo "  make lint                    # Run full lint (including contradictions)"
	@echo "  make lint-structural         # Run structural-only lint checks"
	@echo "  make query QUERY='...'       # Ask the knowledge base"
	@echo "  make query-file-back QUERY='...'  # Ask KB and file answer back"

compile:
	KB_WIKI_PATH="$(KB_WIKI_PATH)" $(UV) $(PYTHON) scripts/compile.py

lint:
	KB_WIKI_PATH="$(KB_WIKI_PATH)" $(UV) $(PYTHON) scripts/lint.py

lint-structural:
	KB_WIKI_PATH="$(KB_WIKI_PATH)" $(UV) $(PYTHON) scripts/lint.py --structural-only

query:
	KB_WIKI_PATH="$(KB_WIKI_PATH)" $(UV) $(PYTHON) scripts/query.py "$(QUERY)"

query-file-back:
	KB_WIKI_PATH="$(KB_WIKI_PATH)" $(UV) $(PYTHON) scripts/query.py "$(QUERY)" --file-back
