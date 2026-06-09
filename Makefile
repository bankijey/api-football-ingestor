.PHONY: help up down build migrate ingest shell test lint logs psql clean

# Default host port for the compose Postgres. Override on the command line if
# 5432 is busy: `make up POSTGRES_HOST_PORT=5434`.
POSTGRES_HOST_PORT ?= 5432
export POSTGRES_HOST_PORT

help:
	@echo "Targets:"
	@echo "  up         Start the postgres service (detached)."
	@echo "  down       Stop & remove the stack containers (keeps the volume)."
	@echo "  build      Build the ingestor image."
	@echo "  migrate    Apply migrations to the running postgres."
	@echo "  ingest     One-off ingestion. Pass args via ARGS=\"--leagues 39\"."
	@echo "  shell      Open a bash shell inside the ingestor container."
	@echo "  test       Run pytest (requires postgres up)."
	@echo "  lint       ruff + mypy."
	@echo "  logs       Tail postgres logs."
	@echo "  psql       Drop into psql against the compose db."
	@echo "  clean      DESTRUCTIVE: down + delete the db volume."

up:
	docker compose up -d postgres

down:
	docker compose down

build:
	docker compose --profile cli build ingestor

migrate: build up
	docker compose --profile cli run --rm \
		--entrypoint python ingestor \
		-c "from pathlib import Path; \
import psycopg2, os; \
from ingestor.db.migrations import apply_migrations; \
conn=psycopg2.connect(os.environ['DB_DSN']); \
print('applied:', apply_migrations(conn, Path('migrations'))); \
conn.close()"

ingest: build up
	docker compose --profile cli run --rm ingestor ingest $(ARGS)

shell: build up
	docker compose --profile cli run --rm --entrypoint bash ingestor

test:
	pytest -q

lint:
	ruff check .
	mypy src

logs:
	docker compose logs -f postgres

psql:
	docker exec -it ingestor-postgres psql -U $${POSTGRES_USER:?POSTGRES_USER not set} -d $${POSTGRES_DB:?POSTGRES_DB not set}

clean:
	docker compose down -v
