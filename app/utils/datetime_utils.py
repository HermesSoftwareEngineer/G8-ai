from datetime import datetime, timezone
import pytz

FORTALEZA_TZ = pytz.timezone("America/Fortaleza")


def now_fortaleza() -> datetime:
    return datetime.now(FORTALEZA_TZ)


def utc_to_fortaleza(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(FORTALEZA_TZ)


def fortaleza_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = FORTALEZA_TZ.localize(dt)
    return dt.astimezone(timezone.utc)


def format_datetime_br(dt: datetime) -> str:
    local = utc_to_fortaleza(dt) if dt.tzinfo else FORTALEZA_TZ.localize(dt)
    return local.strftime("%d/%m/%Y às %Hh%M")


def format_date_br(dt: datetime) -> str:
    local = utc_to_fortaleza(dt) if dt.tzinfo else FORTALEZA_TZ.localize(dt)
    return local.strftime("%d/%m/%Y")


def format_time_br(dt: datetime) -> str:
    local = utc_to_fortaleza(dt) if dt.tzinfo else FORTALEZA_TZ.localize(dt)
    return local.strftime("%Hh%M")


def parse_iso(iso_str: str) -> datetime:
    """Parse ISO 8601 string to UTC-aware datetime."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
