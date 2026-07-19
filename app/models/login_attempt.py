from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginAttempt(Base):
    """
    One row per failed login attempt — purely a rate-limiting counter
    (see app/services/login_attempts.py), not part of the audit trail.
    Deliberately not an FK to users.id: the submitted username may not
    exist, and a failed login against a nonexistent account must be
    rate-limited too (otherwise username enumeration bypasses the limit
    entirely).
    """

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_username_created_at", "username", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
