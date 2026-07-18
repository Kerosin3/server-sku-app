from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformEvent(Base):
    """
    Timestamped milestone log for a platform_item: completion (kitting)
    date, test start/end dates, ship date, and so on.

    Deliberately NOT modeled as fixed columns on PlatformItem
    (assembled_date, test_started_date, test_finished_date,
    shipped_date...) — same reasoning as platform_variant_slots vs
    hardcoded board-type columns: a new milestone type must not require a
    schema migration, and a stage can legitimately happen more than once
    (e.g. re-tested after an RMA repair) — a single date column cannot
    represent that, a log naturally does.

    This is meant to be recorded interactively: the UI exposes one action
    per milestone (e.g. a "Отметить как укомплектовано" button) that
    stamps occurred_at = now() and the acting user, rather than a
    free-text date field the engineer has to type by hand. Test *result*
    (pass/fail, details) is not a separate column — it goes in `notes` on
    the test_finished event, kept as free text rather than a formal
    status to avoid a schema change every time the possible outcomes
    change.

    event_type is a free string, not a DB-level enum, so new milestone
    types can be added without a migration — but every event_type used in
    the UI must have a Russian label registered in app/i18n.py
    (PLATFORM_EVENT_TYPES). Current set (process order): assembled,
    test_started, test_finished, shipped.

    platform_items.status stays as a coarse "current stage" field for
    fast filtering/listing (see PlatformItem model) — the service layer
    that records a PlatformEvent is responsible for keeping
    platform_items.status in sync (e.g. recording a "shipped" event also
    sets status="shipped"). platform_events is the source of truth for
    *when* each stage actually happened; platform_items.status is a
    derived, denormalized convenience.
    """

    __tablename__ = "platform_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_item_id: Mapped[int] = mapped_column(ForeignKey("platform_items.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    platform_item: Mapped["PlatformItem"] = relationship(back_populates="events")
    user: Mapped["User | None"] = relationship()
