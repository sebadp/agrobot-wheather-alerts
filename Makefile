.PHONY: setup up up-logs down test evaluate logs seed dev lint format typecheck check

VENV := .venv/bin/

define check_venv
	@test -d .venv || (echo "Error: venv not found. Run 'make dev' first." && exit 1)
endef

# --- Docker ---

setup:
	docker compose up -d --build
	@echo "Waiting for app to be ready..."
	@until curl -sf http://localhost:8000/health > /dev/null 2>&1; do sleep 2; done
	@echo "App is ready!"

up:
	docker compose up -d --build

up-logs:
	docker compose up --build

down:
	docker compose down -v

evaluate:
	curl -s -X POST http://localhost:8000/api/v1/jobs/evaluate-alerts | python3 -m json.tool

logs:
	docker compose logs -f

seed:
	curl -s -X POST http://localhost:8000/api/v1/weather/seed | python3 -m json.tool

# --- Local dev (venv) ---

dev:
	python -m venv .venv
	$(VENV)pip install -e ".[dev]"
	$(VENV)pre-commit install
	@echo ""
	@echo "Done! Run: source .venv/bin/activate"

test:
	$(check_venv)
	$(VENV)pytest -v

lint:
	$(check_venv)
	$(VENV)ruff check app tests

format:
	$(check_venv)
	$(VENV)ruff format app tests

typecheck:
	$(check_venv)
	$(VENV)mypy app/

check: lint typecheck test
