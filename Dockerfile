FROM python:3.11-slim AS dev
WORKDIR /workspace
COPY pyproject.toml ./
COPY keel/ ./keel/
COPY tests/ ./tests/
COPY agents/ ./agents/
COPY eval/ ./eval/
COPY config/ ./config/
RUN pip install --no-cache-dir ".[dev]"
COPY . .
CMD ["sleep", "infinity"]

FROM python:3.11-slim AS prod
WORKDIR /app
COPY --from=dev /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .
RUN pip install --no-cache-dir .
CMD ["keel", "--help"]
