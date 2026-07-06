"""Application settings, loaded from environment / .env file.

All knobs the ingestor needs live here. No module outside this file should
read os.environ directly — pass a Settings instance instead.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API-Football ---
    apifootball_key: SecretStr = Field(..., description="x-rapidapi-key header value")
    apifootball_base_url: str = Field(
        default="https://v3.football.api-sports.io",
        description="Base URL for API-Football v3.",
    )
    apifootball_host: str = Field(
        default="v3.football.api-sports.io",
        description="x-rapidapi-host header value.",
    )

    # --- Rate limits / quota ---
    rate_limit_per_min: int = Field(default=300, ge=1)
    rate_limit_window_sec: int = Field(default=65, ge=1)
    daily_quota: int = Field(default=100_000, ge=1)

    # --- Concurrency ---
    thread_pool_size: int = Field(default=8, ge=1, le=64)

    # --- Phase B selection ---
    lookback_days: int = Field(default=2, ge=0)
    season: int = Field(default=2025, ge=1900, le=2100)
    league_subset: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        description="If non-empty, restrict Phase A to these league ids.",
    )
    fixture_statuses: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "FT", "AET", "PEN",
            "1H", "2H", "HT", "ET", "INT", "LIVE", "P", "BT", "SUSP",
        ],
        description="API-Football short status codes eligible for Phase B.",
    )

    # --- HTTP retry ---
    http_retry_max_attempts: int = Field(default=7, ge=1)
    http_retry_backoff_base_sec: float = Field(default=1.0, gt=0)
    http_retry_backoff_max_sec: float = Field(default=30.0, gt=0)
    http_timeout_sec: float = Field(default=30.0, gt=0)

    # --- Database ---
    db_dsn: str = Field(
        default="postgresql://ingestor:ingestor@postgres:5432/ingestor",
        description="psycopg2 connection string.",
    )
    # Sources (matcher) DB the `apifootball_events` projection is written INTO
    # (D5). Mirrors db_dsn's type + env-only loading, but carries NO DSN literal
    # default (AC2): a real DSN must come from MATCHER_DB_DSN. Empty means the
    # projection is unconfigured and the run's projection step is skipped.
    matcher_db_dsn: str = Field(
        default="",
        description="Sources-DB psycopg2 connection string (env MATCHER_DB_DSN).",
    )

    # --- Logging ---
    log_level: str = Field(default="INFO")

    # ------- validators -------

    @field_validator("league_subset", mode="before")
    @classmethod
    def _parse_league_subset(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("fixture_statuses", mode="before")
    @classmethod
    def _parse_statuses(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [x.strip().upper() for x in v.split(",") if x.strip()]
        return v

    @field_validator("matcher_db_dsn", mode="before")
    @classmethod
    def _normalize_matcher_dsn(cls, v: object) -> object:
        """Strip a SQLAlchemy ``+<driver>`` suffix from the URL scheme so the
        matcher's native ``postgresql+psycopg2://…`` POSTGRES_URL (D5) works with
        raw psycopg2. Only the scheme token before ``://`` is touched; everything
        after ``://`` is byte-identical. Empty/unset stays empty (projection off).
        """
        if not isinstance(v, str) or "://" not in v:
            return v
        scheme, rest = v.split("://", 1)
        base = scheme.split("+", 1)[0]
        return f"{base}://{rest}"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        out = v.upper()
        if out not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid LOG_LEVEL: {v!r}")
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide singleton Settings. Cached for cheap repeated access."""
    return Settings()  # type: ignore[call-arg]
