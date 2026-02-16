# --- Base stage: shared dependencies ---
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a non-root user
RUN useradd -m -u 1000 agrobot && \
    chown -R agrobot:agrobot /app

# Install dependencies (regular install, no editable)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY --chown=agrobot:agrobot . .
# Install the package itself (standard install)
RUN pip install --no-cache-dir --no-deps .

# --- Production stage: no dev dependencies ---
FROM base AS production

# Switch to non-root user
USER agrobot

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Test stage: includes dev dependencies ---
FROM base AS test

# Switch to root to install dev deps
USER root
RUN pip install --no-cache-dir ".[dev]"
# Switch back to non-root user
USER agrobot

CMD ["pytest", "-v"]
