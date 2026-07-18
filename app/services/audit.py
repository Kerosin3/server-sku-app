"""
Single entry point for writing audit_log rows. Called explicitly from
service functions that mutate part_units, platforms, platform_components
(and, per this change, users) — never from ORM events — so the full
effect of a mutation is visible in one place in the service function.

Does not commit; the caller's transaction (same db session) owns that,
so the audit row lands atomically with the mutation it describes.
"""
from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    *,
    actor_id: int | None,
    entity_type: str,
    entity_id: int,
    action: str,
    diff: dict,
) -> None:
    db.add(
        AuditLog(
            user_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            diff=diff,
        )
    )
