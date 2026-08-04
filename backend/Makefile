CONDA_RUN := conda run -n memory

.PHONY: install format format-check lint type-check test check serve demo up-infra up-container-api down

install:
	$(CONDA_RUN) python -m pip install -e ".[dev]"

format:
	$(CONDA_RUN) ruff format src/service tests scripts migrations
	$(CONDA_RUN) ruff check --fix src/service tests scripts migrations

format-check:
	$(CONDA_RUN) ruff format --check src/service tests scripts migrations

lint:
	$(CONDA_RUN) ruff check src/service tests scripts migrations

type-check:
	$(CONDA_RUN) mypy src/service

test:
	$(CONDA_RUN) python -m pytest

check: format-check lint type-check test

serve:
	$(CONDA_RUN) uvicorn service.main:app --app-dir src --reload --host 0.0.0.0 --port 8000

demo:
	$(CONDA_RUN) python scripts/run_demo.py

up-infra:
	docker compose -f ../docker-compose.yml --project-directory .. up -d postgres redis

up-container-api:
	docker compose -f ../docker-compose.yml --project-directory .. --profile container-api up --build

down:
	docker compose -f ../docker-compose.yml --project-directory .. down
