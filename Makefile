# FareRadar — convenience targets for local development.
#
# Quick start:
#   make setup        # create venv, install python + node deps
#   make seed         # populate DB with demo data
#   make dev          # start scanner+API+dashboard in parallel (foreground)
#
# Production:
#   make docker-up    # full stack via docker compose

PY       ?= python3
VENV     ?= .venv
VENV_BIN := $(VENV)/bin
PIP      := $(VENV_BIN)/pip
PYTHON   := $(VENV_BIN)/python
UVICORN  := $(VENV_BIN)/uvicorn

.PHONY: help setup venv pydeps jsdeps seed api scanner dashboard dev \
        stop clean docker-up docker-down test

help:
	@echo "FareRadar targets:"
	@awk '/^[a-zA-Z_-]+:/ { sub(":.*", "", $$1); printf "  \033[36m%-14s\033[0m %s\n", $$1, (NR==1?"":"") }' $(MAKEFILE_LIST) | grep -v help

# ── setup ────────────────────────────────────────────────────

setup: venv pydeps jsdeps ## Install all dependencies

venv:
	@test -d $(VENV) || $(PY) -m venv $(VENV)

pydeps: venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt

jsdeps:
	cd dashboard && npm install --silent

# ── data ─────────────────────────────────────────────────────

seed: venv ## Seed the DB with demo data
	$(PYTHON) src/seed_demo.py

# ── run (foreground, one service each) ──────────────────────

api: venv ## Start the FastAPI backend on :8000
	$(UVICORN) src.api:app --reload --port 8000

scanner: venv ## Run a single scanner pass
	$(PYTHON) src/scanner.py --once

dashboard: ## Start the Vite dev server on :5173
	cd dashboard && npm run dev

# ── run everything at once ──────────────────────────────────

dev: ## Start API + dashboard in parallel (logs to ./logs/)
	@mkdir -p logs
	@echo "Starting API → logs/api.log"
	@sh -c '$(UVICORN) src.api:app --reload --port 8000 > logs/api.log 2>&1 & echo $$! > logs/api.pid'
	@echo "Starting dashboard → logs/dashboard.log"
	@sh -c '(cd dashboard && npm run dev > ../logs/dashboard.log 2>&1) & echo $$! > logs/dashboard.pid'
	@sleep 3
	@echo ""
	@echo "✓ API        http://localhost:8000"
	@echo "✓ Dashboard  http://localhost:5173"
	@echo ""
	@echo "  make stop      to kill both processes"
	@echo "  tail -f logs/{api,dashboard}.log   to watch logs"

stop: ## Stop API + dashboard started with 'make dev'
	@for p in logs/api.pid logs/dashboard.pid; do \
	    if [ -f $$p ]; then kill $$(cat $$p) 2>/dev/null; rm $$p; fi; \
	done
	@echo "stopped"

# ── docker ──────────────────────────────────────────────────

docker-up: ## Build and start the full stack via docker compose
	docker compose up -d --build
	@echo ""
	@echo "✓ Dashboard  http://localhost:8080"
	@echo "✓ API        http://localhost:8000"

docker-down: ## Stop the docker stack
	docker compose down

# ── misc ────────────────────────────────────────────────────

test: venv ## Smoke-test: seed DB, start API, hit each endpoint
	@echo "1/4 seeding…"
	@$(PYTHON) src/seed_demo.py > /dev/null
	@echo "2/4 starting API…"
	@$(UVICORN) src.api:app --port 18432 > /tmp/fr-test-api.log 2>&1 & echo $$! > /tmp/fr-test.pid
	@sleep 2
	@echo "3/4 hitting endpoints…"
	@curl -sf http://localhost:18432/api/stats  > /dev/null && echo "  ✓ /api/stats"
	@curl -sf http://localhost:18432/api/deals  > /dev/null && echo "  ✓ /api/deals"
	@curl -sf "http://localhost:18432/api/history?origin=LHR&destination=NRT" > /dev/null && echo "  ✓ /api/history"
	@curl -sf -X POST http://localhost:18432/api/deals/1/approve > /dev/null && echo "  ✓ /api/deals/:id/approve"
	@curl -sf -X POST http://localhost:18432/api/deals/2/reject  > /dev/null && echo "  ✓ /api/deals/:id/reject"
	@echo "4/4 cleaning up…"
	@kill $$(cat /tmp/fr-test.pid) 2>/dev/null; rm /tmp/fr-test.pid
	@echo "✓ all endpoints OK"

clean: ## Remove venv, node_modules, DBs, logs
	rm -rf $(VENV) dashboard/node_modules dashboard/dist *.db *.db-journal logs data
