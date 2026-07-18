from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformEvent(Base):
    """
    Timestamped milestone log for a platform instance: manufacture date,
    QC/verification date, initial test date, final test date, ship date,
    and so on.

    Deliberately NOT modeled as fixed columns on Platform
    (manufacture_date, qc_date, initial_test_date, final_test_date,
    ship_date...) — same reasoning as platform_model_slots vs hardcoded
    board-type columns: a new milestone type must not require a schema
    migration, and a stage can legitimately happen more than once (e.g.
    re-tested after an RMA repair) — a single date column cannot represent
    that, a log naturally does.

    This is meant to be recorded interactively: the UI exposes one action
    per milestone (e.g. a "Mark as manufactured" button) that stamps
    occurred_at = now() and the acting user, rather than a free-text date
    field the engineer has to type by hand.

    event_type is a free string, not a DB-level enum, so new milestone
    types can be added without a migration — but every event_type used in
    the UI must have a Russian label registered in app/i18n.py
    (PLATFORM_EVENT_TYPES). Current set: manufactured, qc_verified,
    initial_test, final_test, shipped.

    platforms.status stays as a coarse "current stage" field for fast
    filtering/listing (see Platform model) — the service layer that
    records a PlatformEvent is responsible for keeping platforms.status in
    sync (e.g. recording a "shipped" event also sets status="shipped").
    platform_events is the source of truth for *when* each stage actually
    happened; platforms.status is a derived, denormalized convenience.
    """

    __tablename__ = "platform_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    platform: Mapped["Platform"] = relationship(back_populates="events")
