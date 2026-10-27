"""Application configuration.

Every value is read from the environment so that the decision-cutoff policy and
the upstream source can be changed without touching code.  See ``.env.example``
in the repository root for the documented variable names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_DIR = BACKEND_ROOT / "data" / "snapshots"
DEFAULT_CACHE_DIR = BACKEND_ROOT / "data" / "cache"

BUSINESS_TIMEZONE = "Europe/London"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings."""

    # --- upstream source -------------------------------------------------
    elexon_base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    elexon_timeout_seconds: float = 60.0
    elexon_max_retries: int = 3
    elexon_backoff_seconds: float = 1.5
    # Maximum number of days requested from the upstream stream in one call.
    elexon_window_days: int = 15

    # --- evaluation period ----------------------------------------------
    eval_start: date = date(2026, 1, 1)
    eval_end: date = date(2026, 1, 31)
    # How many extra days of forecast publication history to request before the
    # evaluation period so that early-January delivery days have eligible
    # forecasts published well before their decision cutoff.
    forecast_history_days: int = 30

    # --- decision cutoff policy (ANALYTICAL ASSUMPTION) -------------------
    # cutoff = delivery_date + cutoff_day_offset days, at cutoff_time,
    # evaluated in Europe/London.
    cutoff_day_offset: int = -1
    cutoff_time: time = time(12, 0)
    business_timezone: str = BUSINESS_TIMEZONE

    # --- caching ---------------------------------------------------------
    cache_dir: Path = DEFAULT_CACHE_DIR
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
    # Freshness window for a cached upstream fetch.  Records for a completed
    # historical period are immutable in practice, so the default is long.
    cache_ttl_seconds: int = 24 * 3600
    # Whether a committed snapshot may be used when the upstream API fails.
    allow_snapshot_fallback: bool = True
    # Whether the service may call the live upstream API at all.
    enable_live_fetch: bool = True

    # --- API -------------------------------------------------------------
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://localhost:3000")
    auth_enabled: bool = False

    # --- durable storage --------------------------------------------------
    # Empty means "not configured": the SQLite default is applied for local
    # development, but a production deployment must provide a real URL.
    database_url: str = ""
    # Deployment flavour: "development" (default) or "production".
    deployment_env: str = "development"
    # Shared secret protecting POST /api/refresh.  Empty disables the endpoint.
    admin_token: str = ""
    # Seed durable storage from the committed snapshot when the DB is empty.
    seed_on_startup: bool = True

    # --- runtime ---------------------------------------------------------
    data_dir: Path = field(default=BACKEND_ROOT / "data")

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            o.strip()
            for o in os.environ.get(
                "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
            ).split(",")
            if o.strip()
        )
        eval_start = date.fromisoformat(
            os.environ.get("EVAL_START", "2026-01-01").strip()
        )
        eval_end = date.fromisoformat(os.environ.get("EVAL_END", "2026-01-31").strip())
        cutoff_hour = _env_int("DECISION_CUTOFF_HOUR", 12)
        cutoff_minute = _env_int("DECISION_CUTOFF_MINUTE", 0)
        if not (0 <= cutoff_hour <= 23 and 0 <= cutoff_minute <= 59):
            raise ValueError("Decision cutoff must be a valid time of day")

        return cls(
            elexon_base_url=os.environ.get(
                "ELEXON_BASE_URL", "https://data.elexon.co.uk/bmrs/api/v1"
            ).rstrip("/"),
            elexon_timeout_seconds=float(
                os.environ.get("ELEXON_TIMEOUT_SECONDS", "60")
            ),
            elexon_max_retries=_env_int("ELEXON_MAX_RETRIES", 3),
            elexon_backoff_seconds=float(os.environ.get("ELEXON_BACKOFF_SECONDS", "1.5")),
            elexon_window_days=_env_int("ELEXON_WINDOW_DAYS", 15),
            eval_start=eval_start,
            eval_end=eval_end,
            forecast_history_days=_env_int("FORECAST_HISTORY_DAYS", 30),
            cutoff_day_offset=_env_int("DECISION_CUTOFF_DAY_OFFSET", -1),
            cutoff_time=time(cutoff_hour, cutoff_minute),
            cache_dir=Path(
                os.environ.get("CACHE_DIR", str(DEFAULT_CACHE_DIR))
            ).expanduser(),
            snapshot_dir=Path(
                os.environ.get("SNAPSHOT_DIR", str(DEFAULT_SNAPSHOT_DIR))
            ).expanduser(),
            cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 24 * 3600),
            allow_snapshot_fallback=_env_bool("ALLOW_SNAPSHOT_FALLBACK", True),
            enable_live_fetch=_env_bool("ENABLE_LIVE_FETCH", True),
            cors_origins=origins,
            auth_enabled=_env_bool("AUTH_ENABLED", False),
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            deployment_env=os.environ.get("ENVIRONMENT", "development").strip().lower(),
            admin_token=os.environ.get("ADMIN_TOKEN", "").strip(),
            seed_on_startup=_env_bool("SEED_ON_STARTUP", True),
        )

    def with_database_url(self, url: str) -> "Settings":
        """Return a copy pointing at another database (used by the CLI)."""
        return replace(self, database_url=url)

    # ------------------------------------------------------------------ #
    # Decision cutoff helpers
    # ------------------------------------------------------------------ #
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.business_timezone)

    def decision_cutoff_utc(self, delivery_date: date) -> datetime:
        """Return the decision cutoff (UTC) for a given delivery date."""
        local_day = datetime.combine(delivery_date + timedelta(days=self.cutoff_day_offset), self.cutoff_time, tzinfo=self.tz)
        return local_day.astimezone(timezone.utc)

    @property
    def cutoff_policy_label(self) -> str:
        sign = "-" if self.cutoff_day_offset < 0 else "+"
        days = abs(self.cutoff_day_offset)
        day_part = ""
        if days:
            day_part = f"{sign}{days}d "
        return (
            f"{self.cutoff_time.strftime('%H:%M')} {self.business_timezone} on "
            f"D{day_part}(delivery date {day_part}applied first)"
        )

    @property
    def cutoff_policy_description(self) -> str:
        offset = self.cutoff_day_offset
        if offset == -1:
            relation = "the calendar day before the delivery date"
        elif offset == 0:
            relation = "the delivery date itself"
        else:
            relation = f"{abs(offset)} calendar days before the delivery date"
        return (
            f"Day-ahead decision cutoff: {self.cutoff_time.strftime('%H:%M')} "
            f"{self.business_timezone} on {relation}. "
            "Only forecasts with publishTime at or before this instant are eligible. "
            "This is a configurable analytical assumption, not a verified market deadline."
        )

