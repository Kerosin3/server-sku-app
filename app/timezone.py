"""
All timestamps are stored in the DB as UTC (Postgres TIMESTAMPTZ) —
that part stays UTC, it's the only sane way to store instants. Display
is Moscow time everywhere in the UI and in the JSON export, since
that's the timezone the people reading these dates actually work in;
showing raw UTC (or worse, `+00:00` with microseconds) makes "when did
this actually happen" needlessly hard to work out.

Jinja filters `msk_date` / `msk_datetime` are registered in
app/templating.py; app/services/export.py uses format_msk_datetime
directly for the same reason.
"""
from datetime import date, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))


def to_msk(value: datetime) -> datetime:
    return value.astimezone(MSK)


def format_msk_date(value: datetime | date | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_msk(value)
    return value.strftime("%d.%m.%Y")


def format_msk_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return to_msk(value).strftime("%d.%m.%Y %H:%M МСК")
