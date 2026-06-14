import logging
from datetime import datetime, timedelta, time, date
from app.models.database import get_db
from app.utils.datetime_utils import FORTALEZA_TZ, fortaleza_to_utc

logger = logging.getLogger(__name__)


def get_available_slots(barber_id: str, target_date: date, duration_minutes: int) -> list[str]:
    """
    Return list of available HH:MM slots for a barber on a given date.

    Steps:
    1. Check weekly schedule (schedules table) for that day_of_week
    2. Apply schedule_exceptions (block or extra shifts)
    3. Remove slots already occupied by existing appointments
    """
    db = get_db()
    day_of_week = target_date.weekday()  # Monday=0 … Sunday=6
    # Python weekday: Mon=0, Sun=6 → our schema: Sun=0, Sat=6
    schema_dow = (day_of_week + 1) % 7

    # 1. Base schedule
    schedules = (
        db.table("schedules")
        .select("start_time, end_time")
        .eq("barber_id", barber_id)
        .eq("day_of_week", schema_dow)
        .eq("is_active", True)
        .execute()
        .data or []
    )

    work_windows: list[tuple[time, time]] = []
    for s in schedules:
        start = _parse_time(s["start_time"])
        end = _parse_time(s["end_time"])
        if start and end:
            work_windows.append((start, end))

    # 2. Schedule exceptions for that date
    exceptions = (
        db.table("schedule_exceptions")
        .select("*")
        .eq("barber_id", barber_id)
        .eq("date", target_date.isoformat())
        .execute()
        .data or []
    )

    for exc in exceptions:
        if exc["type"] == "block":
            if exc["start_time"] and exc["end_time"]:
                # Block specific window
                block_start = _parse_time(exc["start_time"])
                block_end = _parse_time(exc["end_time"])
                work_windows = _subtract_window(work_windows, block_start, block_end)
            else:
                # Full-day block
                work_windows = []
        elif exc["type"] == "extra" and exc["start_time"] and exc["end_time"]:
            extra_start = _parse_time(exc["start_time"])
            extra_end = _parse_time(exc["end_time"])
            if extra_start and extra_end:
                work_windows.append((extra_start, extra_end))

    if not work_windows:
        return []

    # 3. Generate candidate slots
    delta = timedelta(minutes=duration_minutes)
    candidates: list[datetime] = []
    for win_start, win_end in work_windows:
        slot_dt = datetime.combine(target_date, win_start)
        end_dt = datetime.combine(target_date, win_end)
        while slot_dt + delta <= end_dt:
            candidates.append(slot_dt)
            slot_dt += timedelta(minutes=30)  # 30-min granularity

    # 4. Fetch existing appointments for that day
    day_start_utc = fortaleza_to_utc(
        FORTALEZA_TZ.localize(datetime.combine(target_date, time(0, 0)))
    )
    day_end_utc = fortaleza_to_utc(
        FORTALEZA_TZ.localize(datetime.combine(target_date, time(23, 59, 59)))
    )

    booked = (
        db.table("appointments")
        .select("start_datetime, end_datetime")
        .eq("barber_id", barber_id)
        .neq("status", "cancelled")
        .gte("start_datetime", day_start_utc.isoformat())
        .lte("start_datetime", day_end_utc.isoformat())
        .execute()
        .data or []
    )

    booked_ranges: list[tuple[datetime, datetime]] = []
    for appt in booked:
        s = datetime.fromisoformat(appt["start_datetime"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(appt["end_datetime"].replace("Z", "+00:00"))
        # Convert to local naive for comparison
        s_local = s.astimezone(FORTALEZA_TZ).replace(tzinfo=None)
        e_local = e.astimezone(FORTALEZA_TZ).replace(tzinfo=None)
        booked_ranges.append((s_local, e_local))

    # 5. Filter out overlapping slots
    free_slots = []
    for slot in candidates:
        slot_end = slot + delta
        if not any(slot < be and slot_end > bs for bs, be in booked_ranges):
            free_slots.append(slot.strftime("%H:%M"))

    return free_slots


def is_slot_available(barber_id: str, start_dt: datetime, duration_minutes: int) -> bool:
    """Check if a specific slot is still available."""
    target_date = start_dt.date()
    available = get_available_slots(barber_id, target_date, duration_minutes)
    return start_dt.strftime("%H:%M") in available


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_time(t) -> time | None:
    if t is None:
        return None
    if isinstance(t, time):
        return t
    try:
        parts = str(t).split(":")
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return None


def _subtract_window(
    windows: list[tuple[time, time]],
    block_start: time,
    block_end: time,
) -> list[tuple[time, time]]:
    result = []
    for ws, we in windows:
        if block_end <= ws or block_start >= we:
            result.append((ws, we))
        else:
            if ws < block_start:
                result.append((ws, block_start))
            if we > block_end:
                result.append((block_end, we))
    return result
