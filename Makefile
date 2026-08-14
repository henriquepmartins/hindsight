# Hindsight — one command from empty checkout to rendered site.
#
# Targets marked TODO below are stubs that fail loudly with the task that fills
# them. See .specs/features/m0-walking-skeleton/tasks.md.

# openFDA re-chunks quarters between exports, so this suffix has a shelf life.
# `resolve` fails loudly with the bucket's real contents when it goes stale.
PARTITION ?= 2025q1/0001-of-0028

.DEFAULT_GOAL := help
.PHONY: help install ingest test analyze site all clean

# A stub that names the task it is waiting on, and fails. It must fail: a target
# that cannot do its job has no business reporting success to `make all`.
define todo
@echo ""
@echo "  make $@ — not implemented yet, lands in $(1)"
@echo "  see .specs/features/m0-walking-skeleton/tasks.md"
@echo ""
@exit 1
endef

help: ## Show this list
	@echo "Hindsight — M0 walking skeleton"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## /{printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "  PARTITION defaults to $(PARTITION); override with PARTITION=<id>"

install: ## Sync the pinned environment from uv.lock
	uv sync --frozen

ingest: ## Fetch a partition and normalize it to Parquet
	uv run hindsight ingest $(PARTITION)

test: ## Run the round-trip integrity test  [TODO T11]
	$(call todo,T11)

analyze: ## Compute PRR over the drug-event contingency tables
	uv run hindsight analyze $(PARTITION)

# The CSV is regenerated first, because the page reads a committed file and a
# stale one is the way the site and the pipeline drift apart silently (T17).
site: ## Write the report's CSV and render the Quarto site to _site/
	uv run hindsight analyze $(PARTITION) --csv
	uv run --group viz quarto render

all: install ingest test analyze site ## Everything, in order

# Removes only what can be re-derived. data/manifest/ and schema/ survive on
# purpose — they are the pins, and losing them loses the reproducibility claim.
clean: ## Remove derived artifacts (keeps the pins)
	rm -rf data/raw data/parquet _site .quarto .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
