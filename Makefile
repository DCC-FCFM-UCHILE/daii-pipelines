# Atajos del proyecto. `make` sin argumentos muestra la ayuda.
.DEFAULT_GOAL := help
.PHONY: help install env test lint format typecheck check run crawl spiders silver gold migration serve ui clean

SPIDERS ?=
SPIDER ?=
PERSONA ?=
CRON ?=

help: ## Muestra esta ayuda
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Instala dependencias y Chromium para Playwright
	uv sync
	uv run playwright install chromium

env: ## Crea .env desde .env.example (no pisa uno existente)
	@test -f .env && echo ".env ya existe" || cp .env.example .env

test: ## Corre los tests (fixtures, sin red)
	uv run pytest

lint: ## ruff check + verificación de formato
	uv run ruff check
	uv run ruff format --check

format: ## Corrige lint y formatea
	uv run ruff check --fix
	uv run ruff format

typecheck: ## ty sobre src
	uv run ty check src

check: lint typecheck test ## lint + tipos + tests (lo que se pide antes de un PR)

run: ## Pipeline completo; SPIDERS=a,b para solo algunos
	uv run daii run $(if $(SPIDERS),--spiders $(SPIDERS))

crawl: ## Un spider suelto: make crawl SPIDER=orcid [PERSONA=slug]
	@test -n "$(SPIDER)" || { echo "Uso: make crawl SPIDER=<spider> [PERSONA=<slug>]"; exit 1; }
	uv run scrapy crawl $(SPIDER) $(if $(PERSONA),-a persona=$(PERSONA))

spiders: ## Lista los spiders
	uv run daii spiders

silver: ## Prepara un candidato Silver desde bronze (imprime su build_id)
	uv run daii silver

gold: ## Publica el último candidato Silver en gold
	uv run daii gold

migration: ## Nueva migración de gold desde models.py: make migration MSG="..."
	@test -n "$(MSG)" || { echo 'Uso: make migration MSG="descripción"'; exit 1; }
	db=$$(mktemp -u --suffix=.sqlite); trap 'rm -f $$db' EXIT; uv run alembic -x db=$$db upgrade head \
		&& uv run alembic -x db=$$db revision --autogenerate -m "$(MSG)"

serve: ## Deployment programado en Prefect (CRON="..." opcional; default del CLI: lunes 06:00)
	uv run daii serve $(if $(CRON),--cron "$(CRON)")

ui: ## UI de Prefect en http://127.0.0.1:4200
	uv run prefect server start

clean: ## Borra cachés (no toca data/)
	rm -rf .pytest_cache .ruff_cache
	find . \( -path ./.venv -o -path ./data \) -prune -o -name __pycache__ -type d -exec rm -rf {} +
