# Agrobot Weather Alerts

Alertas meteorologicas para el sector agropecuario.

## Requisitos

- Python >= 3.11

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## CI

El pipeline de GitHub Actions ejecuta tres jobs en paralelo:

- **Lint** — `ruff check` + `ruff format --check`
- **Type check** — `mypy app/`
- **Test** — `pytest` (corre despues de lint y typecheck)

Ademas, en PRs a `main`:

- **AI Review** — Gemini 2.0 Flash analiza el diff y postea un code review
- **AI Description** — Genera titulo y descripcion del PR automaticamente (solo en PR `opened`)

## Pre-commit

Los mismos checks corren localmente antes de cada commit:

```bash
pre-commit run --all-files  # correr manualmente
```

Hooks configurados: ruff (lint + format), mypy, pytest.
