"""
Business logic for "детали без владельца" — part_units that exist in
the catalog but are not currently installed on any platform_item:
either explicitly removed (app/services/platform_items.remove_component)
or orphaned when their item was deleted (delete_item hard-deletes its
platform_components rows). This is the inverse of
app/services/search.py's "is this serial currently installed" check —
this module lists everything that currently is NOT, i.e. sitting on
the shelf.

Deletion here is a genuine, permanent purge (not a removed_at marker)
— explicitly requested as a declutter tool for junk/test entries, so
it also removes this part's own firmware history and installation
history rather than leaving orphaned rows behind. One audit_log entry
per deletion keeps a minimal "who/when" trace even though the detailed
sub-history is gone; see AGENTS.md "Устойчивость к изменениям" for why
this is called out explicitly rather than done silently elsewhere.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import FirmwareRecord, MacAddress, PartCategory, PartType, PartUnit, PlatformComponent, User
from app.services import audit


class PartUnitInstalledError(Exception):
    """Still actively installed somewhere — not actually unowned, can't be purged."""


def list_unowned(db: Session) -> list[PartUnit]:
    active_part_unit_ids = select(PlatformComponent.part_unit_id).where(PlatformComponent.removed_at.is_(None))
    return list(
        db.scalars(
            select(PartUnit)
            .join(PartUnit.part_type)
            .join(PartType.category)
            .options(selectinload(PartUnit.part_type).selectinload(PartType.category))
            .where(~PartUnit.id.in_(active_part_unit_ids))
            .order_by(PartCategory.name, PartType.model_name, PartUnit.serial_number)
        ).all()
    )


def last_installation(db: Session, part_unit_id: int) -> PlatformComponent | None:
    """
    Most recent installation record for a (now unowned) part_unit, if
    any is still on record — None if it was never installed, or if its
    only installation history died with a hard-deleted item (see
    platform_items.delete_item). Used to show "last seen in / slot" for
    identification, not for anything load-bearing.
    """
    return db.scalar(
        select(PlatformComponent)
        .options(selectinload(PlatformComponent.platform_item), selectinload(PlatformComponent.platform_variant_slot))
        .where(PlatformComponent.part_unit_id == part_unit_id)
        .order_by(PlatformComponent.removed_at.desc().nullslast(), PlatformComponent.installed_at.desc())
        .limit(1)
    )


def delete_part_unit(db: Session, *, actor: User, part_unit: PartUnit) -> None:
    is_active = (
        db.scalar(
            select(PlatformComponent.id).where(
                PlatformComponent.part_unit_id == part_unit.id, PlatformComponent.removed_at.is_(None)
            )
        )
        is not None
    )
    if is_active:
        raise PartUnitInstalledError(part_unit.id)

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="part_unit",
        entity_id=part_unit.id,
        action="delete",
        diff={
            "serial_number": part_unit.serial_number,
            "article": part_unit.part_type.model_name,
            "category": part_unit.part_type.category.name,
        },
    )

    db.query(FirmwareRecord).filter(FirmwareRecord.part_unit_id == part_unit.id).delete()
    db.query(MacAddress).filter(MacAddress.part_unit_id == part_unit.id).delete()
    db.query(PlatformComponent).filter(PlatformComponent.part_unit_id == part_unit.id).delete()
    db.delete(part_unit)
    db.commit()
