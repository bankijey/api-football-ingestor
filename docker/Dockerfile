# Bronze ingestor image. Python 3.12 per CLAUDE.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg2-binary ships wheels and python:3.12-slim already includes
# ca-certificates — no apt steps needed.

WORKDIR /app

# Copy the full source tree first (small project, layer caching not critical
# vs. needing src/ present for the editable install).
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations

RUN pip install .

ENTRYPOINT ["python", "-m", "ingestor.cli"]
CMD ["ingest"]
