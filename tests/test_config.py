"""Settings: env parsing, defaults, validators, secret handling."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from ingestor.config import Settings, get_settings


def _env(monkeypatch: pytest.MonkeyPatch, **kv: str) -> None:
    # Block ambient .env from leaking in via cwd
    monkeypatch.chdir("/")
    monkeypatch.setenv("APIFOOTBALL_KEY", "test-key")
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def test_minimum_env_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.apifootball_key.get_secret_value() == "test-key"
    assert s.rate_limit_per_min == 300
    assert s.thread_pool_size == 8
    assert "FT" in s.fixture_statuses


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    monkeypatch.delenv("APIFOOTBALL_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_league_subset_csv_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LEAGUE_SUBSET="39, 140 ,61")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.league_subset == [39, 140, 61]


def test_league_subset_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LEAGUE_SUBSET="")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.league_subset == []


def test_fixture_statuses_csv_upper(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, FIXTURE_STATUSES="ft,aet, 1h ")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.fixture_statuses == ["FT", "AET", "1H"]


def test_invalid_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LOG_LEVEL="LOUD")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_secret_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "test-key" not in repr(s)
    assert "test-key" not in str(s)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b


def test_matcher_dsn_dialect_normalized() -> None:
    def _dsn(v: str) -> str:
        return Settings(  # type: ignore[call-arg]
            _env_file=None, apifootball_key="k",         # type: ignore[arg-type]
            matcher_db_dsn=v,
        ).matcher_db_dsn

    # SQLAlchemy `+psycopg2` dialect suffix stripped for raw psycopg2 (F1/D5).
    assert _dsn("postgresql+psycopg2://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    # A bare psycopg2 DSN is unchanged (idempotent).
    assert _dsn("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    # Unconfigured stays empty — projection stays skipped (D5).
    assert _dsn("") == ""
