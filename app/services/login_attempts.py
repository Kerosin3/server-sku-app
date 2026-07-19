"""
Simple DB-backed login rate limiting. After MAX_ATTEMPTS failed logins
for one username within WINDOW_MINUTES, further attempts are rejected
by app/routers/auth.py without even checking the password — this stops
both brute-forcing a known username and (since attempts are tracked by
the raw submitted username, not a user_id FK) probing for which
usernames exist.

Deliberately a sliding window rather than a fixed lockout period: a
blocked request is never allowed to check the password, so no new row
is ever written while locked out — the count of recent failures can
only shrink as old rows age out of the window, so a lockout always
self-expires WINDOW_MINUTES after the last real attempt and can't be
extended indefinitely by the attacker just by keeping to hit the
endpoint.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import LoginAttempt

MAX_ATTEMPTS = 10
WINDOW_MINUTES = 15


def _window_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)


def is_locked_out(db: Session, username: str) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.username == username, LoginAttempt.created_at >= _window_start())
    )
    return (count or 0) >= MAX_ATTEMPTS


def record_failed_attempt(db: Session, username: str) -> None:
    # Opportunistic cleanup so this table doesn't grow forever — cheap
    # since it only ever touches rows already outside every window.
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < _window_start()))
    db.add(LoginAttempt(username=username))
    db.commit()


def clear_attempts(db: Session, username: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == username))
    db.commit()
