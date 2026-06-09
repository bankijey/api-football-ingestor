"""bronze_writer.write_bronze: hash dedup, append-only, typed extras."""
from __future__ import annotations

import uuid

import pytest

from ingestor.db.bronze_writer import write_bronze


def _count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return int(cur.fetchone()[0])


def test_first_write_inserts_row(pg_conn) -> None:
    rid = uuid.uuid4()
    r = write_bronze(
        pg_conn,
        endpoint="leagues",
        request_params={},
        payload={"response": [{"id": 1}], "errors": []},
        run_id=rid,
    )
    assert r.changed is True
    assert r.bronze_row_id is not None
    assert _count(pg_conn, "bronze_leagues") == 1
    assert _count(pg_conn, "bronze_latest_hash") == 1


def test_identical_payload_is_skipped(pg_conn) -> None:
    rid = uuid.uuid4()
    p = {"response": [{"id": 1}], "errors": []}
    write_bronze(pg_conn, endpoint="leagues", request_params={}, payload=p, run_id=rid)
    r2 = write_bronze(pg_conn, endpoint="leagues", request_params={}, payload=p, run_id=rid)
    assert r2.changed is False
    assert r2.bronze_row_id is None
    assert _count(pg_conn, "bronze_leagues") == 1  # no second row
    # last_checked_at still bumped
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT last_checked_at >= last_changed_at FROM bronze_latest_hash"
        )
        assert cur.fetchone()[0] is True


def test_changed_payload_appends_new_row(pg_conn) -> None:
    rid = uuid.uuid4()
    write_bronze(
        pg_conn, endpoint="leagues", request_params={},
        payload={"response": [{"id": 1}], "errors": []}, run_id=rid,
    )
    write_bronze(
        pg_conn, endpoint="leagues", request_params={},
        payload={"response": [{"id": 1}, {"id": 2}], "errors": []}, run_id=rid,
    )
    assert _count(pg_conn, "bronze_leagues") == 2
    assert _count(pg_conn, "bronze_latest_hash") == 1  # still one params slot


def test_fixtures_by_league_writes_typed_columns(pg_conn) -> None:
    rid = uuid.uuid4()
    r = write_bronze(
        pg_conn,
        endpoint="fixtures_by_league",
        request_params={"league_id": 39, "season": 2025},
        payload={"response": [], "errors": []},
        run_id=rid,
    )
    assert r.changed
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT league_id, season FROM bronze_fixtures WHERE id = %s",
            (r.bronze_row_id,),
        )
        assert cur.fetchone() == (39, 2025)


def test_fixtures_by_league_requires_extras(pg_conn) -> None:
    with pytest.raises(KeyError):
        write_bronze(
            pg_conn,
            endpoint="fixtures_by_league",
            request_params={"league_id": 39},  # missing season
            payload={"response": [], "errors": []},
            run_id=uuid.uuid4(),
        )


def test_unknown_endpoint_rejected(pg_conn) -> None:
    with pytest.raises(ValueError):
        write_bronze(
            pg_conn,
            endpoint="nope",
            request_params={},
            payload={},
            run_id=uuid.uuid4(),
        )


def test_distinct_param_sets_have_independent_dedup(pg_conn) -> None:
    rid = uuid.uuid4()
    payload = {"response": [], "errors": []}
    write_bronze(
        pg_conn, endpoint="fixtures_by_league",
        request_params={"league_id": 39, "season": 2025},
        payload=payload, run_id=rid,
    )
    write_bronze(
        pg_conn, endpoint="fixtures_by_league",
        request_params={"league_id": 140, "season": 2025},
        payload=payload, run_id=rid,
    )
    # Same payload, different params → both rows persisted (different latest_hash keys)
    assert _count(pg_conn, "bronze_fixtures") == 2
    assert _count(pg_conn, "bronze_latest_hash") == 2
