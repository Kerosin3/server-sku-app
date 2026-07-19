"""
Business logic for platform_events — the interactive milestone log for
a platform_item (see app/models/platform_event.py). No audit_log entry
here: unlike platform_components/platform_items mutations, a
PlatformEvent row already carries user_id + occurred_at intrinsically —
it *is* its own audit trail, a separate audit_log row would just
duplicate it.
"""
from sqlalchemy import select
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


def _has_event(db: Session, item: PlatformItem, event_types: set[str]) -> bool:
    return (
        db.scalar(
            select(PlatformEvent.id).where(
                PlatformEvent.platform_item_id == item.id,
                PlatformEvent.event_type.in_(event_types),
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
