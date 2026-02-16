# --- Base stage: shared dependencies ---
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .
RUN pip install --no-cache-dir --no-deps -e .

# --- Production stage: no dev dependencies ---
FROM base AS production

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Test stage: includes dev dependencies ---
FROM base AS test

RUN pip install --no-cache-dir ".[dev]"
CMD ["pytest", "-v"]
