PARTITION ?= 2025q1/0001-of-0028

.DEFAULT_GOAL := help
.PHONY: help install ingest test analyze site all clean

help: ## Mostra esta lista
	@echo "Hindsight — M0 esqueleto ambulante"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## /{printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "  PARTITION assume $(PARTITION); troque com PARTITION=<id>"

install: ## Sincroniza o ambiente fixado no uv.lock
	uv sync --frozen

ingest: ## Baixa uma partição e normaliza para Parquet
	uv run hindsight ingest $(PARTITION)

test: ## Roda a suíte rápida, round trip sobre o fixture incluído
	uv run pytest -q

analyze: ## Calcula o PRR sobre as tabelas de contingência
	uv run hindsight analyze $(PARTITION)

site: ## Escreve o CSV do relatório e renderiza o site em _site/
	uv run hindsight analyze $(PARTITION) --csv
	uv run --group viz quarto render

all: install ingest analyze site ## Tudo, em ordem — os testes fecham, sobre o que a cadeia acabou de produzir
	uv run pytest -q -m "slow or not slow"

clean: ## Remove artefatos derivados (mantém os pins)
	rm -rf data/raw data/parquet _site .quarto .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
