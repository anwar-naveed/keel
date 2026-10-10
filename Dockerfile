FROM python:3.11-slim AS dev
WORKDIR /workspace
COPY pyproject.toml ./
COPY keel/ ./keel/
COPY tests/ ./tests/
COPY agents/ ./agents/
COPY eval/ ./eval/
COPY config/ ./config/
# Editable install: site-packages points at /workspace, so the bind-mounted
# source is always what imports resolve to (tests run against live source).
RUN pip install --no-cache-dir -e ".[dev]"
COPY . .
CMD ["sleep", "infinity"]

FROM python:3.11-slim AS prod
WORKDIR /app
COPY pyproject.toml ./
COPY keel/ ./keel/
COPY agents/ ./agents/
COPY eval/ ./eval/
COPY config/ ./config/
RUN pip install --no-cache-dir .
CMD ["keel", "--help"]
