"""
Business logic for platform_events — the interactive milestone log for
a platform_item (see app/models/platform_event.py). No audit_log entry
here: unlike platform_components/platform_items mutations, a
PlatformEvent row already carries user_id + occurred_at intrinsically —
it *is* its own audit trail, a separate audit_log row would just
duplicate it.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.i18n import PLATFORM_EVENT_TYPES
from app.models import PlatformEvent, PlatformItem, User

# Which platform_items.status a milestone advances the item to. Stages
# not listed here (test_passed/test_failed/test_passed_with_remarks,
# service) are logged without moving platform_items.status — the coarse
# status only tracks "being kitted" vs "kitted" vs "being tested" vs
# "shipped", the event log is the source of truth for exactly when each
# finer-grained milestone happened (e.g. which test attempt passed).
_STATUS_ON_EVENT = {
    "assembled": "assembled",
    "disassembled": "disassembled",
    "test_started": "testing",
    "shipped": "shipped",
}

# Taking a unit apart ends one cycle and starts another: everything
# recorded before it describes a machine that no longer exists in that
# form, so no earlier stage can satisfy a prerequisite afterwards. See
# _has_event.
#
# Only `disassembled` resets. `shipped` deliberately does not: a unit
# coming back from the field is disassembled *after* it shipped, and
# treating shipping as a reset would invalidate the `assembled` that
# `disassembled` itself requires — leaving a returned unit with no legal
# next stage at all.
CYCLE_RESET_EVENT = "disassembled"

# event_type -> (any one of these prior event_types must already exist
# for this item, error message if none does). Enforces the real process
# order (can't test what was never assembled, can't ship what was never
# tested) instead of letting the log record stages out of order.
_PREREQUISITES: dict[str, tuple[set[str], str]] = {
    "test_started": ({"assembled"}, "Нельзя начать тестирование до укомплектования"),
    "test_passed": ({"test_started"}, "Нельзя завершить тест, который не был начат"),
    "test_passed_with_remarks": ({"test_started"}, "Нельзя завершить тест, который не был начат"),
    "test_failed": ({"test_started"}, "Нельзя завершить тест, который не был начат"),
    "shipped": ({"test_passed", "test_passed_with_remarks"}, "Нельзя отгрузить изделие без пройденного теста"),
    "service": ({"shipped"}, "Нельзя провести сервисное обслуживание неотгруженного изделия"),
    "disassembled": ({"assembled"}, "Нельзя разукомплектовать то, что не было укомплектовано"),
}


class InvalidEventTypeError(Exception):
    pass


class PrerequisiteNotMetError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RemarksRequiredError(Exception):
    pass


def list_events(db: Session, item: PlatformItem) -> list[PlatformEvent]:
    return list(
        db.scalars(
            select(PlatformEvent)
            .options(selectinload(PlatformEvent.user))
            .where(PlatformEvent.platform_item_id == item.id)
            .order_by(PlatformEvent.occurred_at.desc())
        ).all()
    )


def _cycle_start_id(db: Session, item: PlatformItem) -> int:
    """
    Id of the most recent teardown, or 0 if the unit has never been
    taken apart.

    Ordering is by id, not occurred_at. occurred_at defaults to the
    database's now(), which in PostgreSQL is transaction time — several
    events written in one transaction share a timestamp exactly (the demo
    seed produces a whole history that way). Ids are monotonic, so they
    are the only reliable order here.
    """
    return (
        db.scalar(
            select(func.max(PlatformEvent.id)).where(
                PlatformEvent.platform_item_id == item.id,
                PlatformEvent.event_type == CYCLE_RESET_EVENT,
            )
        )
        or 0
    )


def _has_event(db: Session, item: PlatformItem, event_types: set[str]) -> bool:
    """
    Has one of these stages happened **in the current cycle** — that is,
    since the unit was last taken apart.

    The distinction is the whole point. Asking "did this ever happen"
    made prerequisites permanently satisfied: a unit that came back from
    the field, was disassembled and rebuilt still had its original
    test_passed on record, so it could be shipped again without anyone
    testing the repaired machine. The log said it passed a test; the test
    was for a different physical configuration.
    """
    return (
        db.scalar(
            select(PlatformEvent.id).where(
                PlatformEvent.platform_item_id == item.id,
                PlatformEvent.event_type.in_(event_types),
                PlatformEvent.id > _cycle_start_id(db, item),
            )
        )
        is not None
    )


def record_event(
    db: Session, *, actor: User, item: PlatformItem, event_type: str, notes: str | None
) -> PlatformEvent:
    if event_type not in PLATFORM_EVENT_TYPES:
        raise InvalidEventTypeError(event_type)

    if event_type == "test_passed_with_remarks" and not notes:
        raise RemarksRequiredError()

    prerequisite = _PREREQUISITES.get(event_type)
    if prerequisite is not None:
        required_types, message = prerequisite
        if not _has_event(db, item, required_types):
            raise PrerequisiteNotMetError(message)

    event = PlatformEvent(
        platform_item_id=item.id,
        event_type=event_type,
        user_id=actor.id,
        notes=notes or None,
    )
    db.add(event)

    new_status = _STATUS_ON_EVENT.get(event_type)
    if new_status is not None:
        item.status = new_status

    db.commit()
    db.refresh(event)
    return event
