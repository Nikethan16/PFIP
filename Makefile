# PFIP — Personal Financial Intelligence Platform
# Root Makefile. Works on Unix, macOS, and WSL.
# Windows PowerShell users: see `scripts/*.ps1` for equivalents, or install GNU Make.
#
# Primary entry point for day-to-day operations. Run `make help` for the target list.

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

SHELL            := /bin/bash
.SHELLFLAGS      := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL    := help

# Project root (where this Makefile lives) — resolves to absolute path.
ROOT_DIR         := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

COMPOSE_FILE     := $(ROOT_DIR)/infra/docker-compose.yml
ENV_FILE         := $(ROOT_DIR)/.env
COMPOSE          := docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE)

BACKEND_CT       := pfip-backend
FRONTEND_CT      := pfip-frontend
DB_CT            := pfip-timescaledb
OLLAMA_CT        := pfip-ollama

POSTGRES_USER    ?= pfip
POSTGRES_DB      ?= pfip

PY               ?= python3
SCRIPTS_DIR      := $(ROOT_DIR)/scripts

# ----------------------------------------------------------------------------
# Help — default target. Parses `##` comments after target names.
# ----------------------------------------------------------------------------

.PHONY: help
help: ## Print this help message
	@printf "\nPFIP — Makefile targets\n"
	@printf "========================\n\n"
	@awk 'BEGIN {FS = ":.*## "; pad=20} \
	  /^[a-zA-Z0-9_.-]+:.*?## / { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@printf "\nTip: Windows users without GNU Make, run scripts/*.ps1 directly.\n\n"

# ----------------------------------------------------------------------------
# Pre-flight checks
# ----------------------------------------------------------------------------

.PHONY: _check-env
_check-env:
	@if [ ! -f "$(ENV_FILE)" ]; then \
	  printf "\033[33m[WARN]\033[0m .env not found. Copying from .env.example...\n"; \
	  cp "$(ROOT_DIR)/.env.example" "$(ENV_FILE)"; \
	  printf "\033[33m[WARN]\033[0m Edit $(ENV_FILE) and fill in secrets before running services.\n"; \
	fi

.PHONY: _check-docker
_check-docker:
	@docker info >/dev/null 2>&1 || { \
	  printf "\033[31m[FAIL]\033[0m Docker daemon is not running. Start Docker Desktop and retry.\n"; \
	  exit 1; \
	}

##@ Stack lifecycle

.PHONY: up
up: _check-env _check-docker ## Bring up all services (docker compose up -d)
	@$(COMPOSE) up -d
	@printf "\n\033[32m[OK]\033[0m Stack is up. URLs:\n"
	@printf "  Frontend      http://localhost:3000\n"
	@printf "  Backend API   http://localhost:8000/docs\n"
	@printf "  Prefect       http://localhost:4200\n"
	@printf "  MLflow        http://localhost:5000\n"
	@printf "  Qdrant        http://localhost:6333/dashboard\n"
	@printf "  Uptime Kuma   http://localhost:3001\n"
	@printf "  Ollama        http://localhost:11434\n"

.PHONY: down
down: ## Stop and remove all containers (keeps volumes)
	@$(COMPOSE) down

.PHONY: stop
stop: ## Stop all services without removing containers
	@$(COMPOSE) stop

.PHONY: restart
restart: stop up ## Restart the full stack

.PHONY: ps
ps: ## List service containers + status
	@$(COMPOSE) ps

##@ Logs

.PHONY: logs
logs: ## Tail logs for all services (follow)
	@$(COMPOSE) logs -f --tail=200

.PHONY: logs-backend
logs-backend: ## Tail backend logs
	@$(COMPOSE) logs -f --tail=200 backend

.PHONY: logs-frontend
logs-frontend: ## Tail frontend logs
	@$(COMPOSE) logs -f --tail=200 frontend

##@ Health

.PHONY: health
health: ## Hit every service health endpoint and report PASS/FAIL
	@bash "$(SCRIPTS_DIR)/health.sh"

##@ Shells / exec

.PHONY: shell-backend
shell-backend: ## Exec into backend container (bash)
	@docker exec -it $(BACKEND_CT) bash || docker exec -it $(BACKEND_CT) sh

.PHONY: shell-db
shell-db: ## psql into TimescaleDB
	@docker exec -it $(DB_CT) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

##@ Database

.PHONY: migrate
migrate: ## Apply pending alembic migrations (upgrade head)
	@docker exec -i $(BACKEND_CT) alembic upgrade head

.PHONY: migrate-new
migrate-new: ## Create a new autogen alembic revision. Usage: make migrate-new MSG="add table"
	@test -n "$(MSG)" || { printf "\033[31m[ERR]\033[0m MSG is required. Usage: make migrate-new MSG=\"add table\"\n"; exit 1; }
	@docker exec -i $(BACKEND_CT) alembic revision --autogenerate -m "$(MSG)"

##@ Data + models

.PHONY: ingest-btc
ingest-btc: ## Trigger the BTC daily Prefect flow on-demand
	@bash "$(SCRIPTS_DIR)/ingest_btc.sh"

.PHONY: pull-models
pull-models: ## Pull Ollama models (mistral:7b-instruct + nomic-embed-text)
	@bash "$(SCRIPTS_DIR)/pull_models.sh"

##@ Quality

.PHONY: test
test: test-backend test-frontend ## Run all tests

.PHONY: test-backend
test-backend: ## Run backend pytest
	@docker exec -i $(BACKEND_CT) pytest -q

.PHONY: test-frontend
test-frontend: ## Run frontend tests
	@docker exec -i $(FRONTEND_CT) pnpm test -- --run

.PHONY: lint
lint: ## Run ruff + prettier
	@docker exec -i $(BACKEND_CT) ruff check .
	@docker exec -i $(FRONTEND_CT) pnpm exec prettier --check .

.PHONY: format
format: ## Auto-fix lint issues
	@docker exec -i $(BACKEND_CT) ruff check --fix .
	@docker exec -i $(FRONTEND_CT) pnpm exec prettier --write .

##@ Backup + restore

.PHONY: backup
backup: ## Run the nightly backup script (DB + Qdrant + MLflow)
	@bash "$(SCRIPTS_DIR)/backup.sh"

.PHONY: restore-drill
restore-drill: ## Run the quarterly restore drill (spins up a test stack)
	@bash "$(SCRIPTS_DIR)/restore_drill.sh"

##@ Cleanup

.PHONY: clean
clean: ## Remove build artifacts (keeps data volumes)
	@printf "Removing build caches, __pycache__, .next, node_modules caches...\n"
	@find "$(ROOT_DIR)" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	@find "$(ROOT_DIR)" -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@find "$(ROOT_DIR)" -type d -name ".ruff_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf "$(ROOT_DIR)/frontend/.next" 2>/dev/null || true
	@rm -rf "$(ROOT_DIR)/backend/.mypy_cache" 2>/dev/null || true
	@printf "\033[32m[OK]\033[0m Build artifacts cleaned. Data volumes preserved.\n"

.PHONY: clean-all
clean-all: ## DESTRUCTIVE: also removes all Docker volumes (prompts y/N)
	@printf "\033[31m[DANGER]\033[0m This will DELETE all PFIP Docker volumes:\n"
	@printf "  timescale_data, redis_data, qdrant_data, prefect_data, mlflow_data, ollama_data, uptime_kuma_data\n"
	@printf "All data will be permanently lost. Continue? [y/N] "
	@read -r REPLY; \
	if [ "$$REPLY" = "y" ] || [ "$$REPLY" = "Y" ]; then \
	  $(COMPOSE) down -v; \
	  $(MAKE) clean; \
	  printf "\033[32m[OK]\033[0m All volumes removed.\n"; \
	else \
	  printf "Aborted.\n"; \
	fi
