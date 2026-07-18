"""
Business logic for platforms and their as-built component list.
Every mutation here writes an audit_log row per AGENTS.md.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import PartUnit, Platform, PlatformComponent, PlatformModel, User
from app.services import audit


class ModelNotFoundError(Exception):
    pass


class AssetTagTakenError(Exception):
    pass


class PartUnitNotFoundError(Exception):
    pass


class PartUnitAlreadyInstalledError(Exception):
    pass


class ComponentNotActiveError(Exception):
    pass


def get_platform(db: Session, platform_id: int) -> Platform | None:
    return db.scalar(
        select(Platform)
        .options(
            selectinload(Platform.platform_model).selectinload(PlatformModel.slots),
            selectinload(Platform.components).selectinload(PlatformComponent.part_unit),
            selectinload(Platform.components).selectinload(PlatformComponent.platform_model_slot),
        )
        .where(Platform.id == platform_id)
    )


def slot_checklist(platform: Platform) -> list[dict]:
    """Required (as-planned) slots vs currently-installed (as-built) count."""
    active = [c for c in platform.components if c.removed_at is None]
    counts: dict[int, int] = {}
    for c in active:
        if c.platform_model_slot_id is not None:
            counts[c.platform_model_slot_id] = counts.get(c.platform_model_slot_id, 0) + 1

    rows = []
    for slot in platform.platform_model.slots:
        installed = counts.get(slot.id, 0)
        rows.append(
            {
                "slot": slot,
                "installed": installed,
                "complete": installed >= slot.quantity if slot.required else True,
            }
        )
    return rows


def removed_components(platform: Platform) -> list[PlatformComponent]:
    return sorted(
        (c for c in platform.components if c.removed_at is not None),
        key=lambda c: c.removed_at,
        reverse=True,
    )


def create_platform(
    db: Session,
    *,
    actor: User,
    platform_model_id: int,
    asset_tag: str,
    customer: str | None,
    location: str | None,
    notes: str | None,
) -> Platform:
    if db.get(PlatformModel, platform_model_id) is None:
        raise ModelNotFoundError(platform_model_id)
    if db.scalar(select(Platform).where(Platform.asset_tag == asset_tag)) is not None:
        raise AssetTagTakenError(asset_tag)

    platform = Platform(
        platform_model_id=platform_model_id,
        asset_tag=asset_tag,
        customer=customer or None,
        location=location or None,
        notes=notes or None,
    )
    db.add(platform)
    db.flush()

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="platform",
        entity_id=platform.id,
        action="create",
        diff={"asset_tag": asset_tag, "platform_model_id": platform_model_id},
    )
    db.commit()
    db.refresh(platform)
    return platform


def update_details(
    db: Session,
    *,
    actor: User,
    platform: Platform,
    customer: str | None,
    location: str | None,
    notes: str | None,
) -> Platform:
    diff = {}
    for field, new_value in (("customer", customer or None), ("location", location or None), ("notes", notes or None)):
        old_value = getattr(platform, field)
        if old_value != new_value:
            diff[field] = [old_value, new_value]
            setattr(platform, field, new_value)

    if diff:
        audit.record(
            db, actor_id=actor.id, entity_type="platform", entity_id=platform.id, action="update", diff=diff
        )
        db.commit()
        db.refresh(platform)
    return platform


def install_component(
    db: Session,
    *,
    actor: User,
    platform: Platform,
    serial_number: str,
    platform_model_slot_id: int | None,
    slot_position: str | None,
) -> PlatformComponent:
    part_unit = db.scalar(select(PartUnit).where(PartUnit.serial_number == serial_number))
    if part_unit is None:
        raise PartUnitNotFoundError(serial_number)

    already_installed = db.scalar(
        select(PlatformComponent).where(
            PlatformComponent.part_unit_id == part_unit.id, PlatformComponent.removed_at.is_(None)
        )
    )
    if already_installed is not None:
        raise PartUnitAlreadyInstalledError(serial_number)

    now = datetime.now(timezone.utc)
    component = PlatformComponent(
        platform_id=platform.id,
        part_unit_id=part_unit.id,
        platform_model_slot_id=platform_model_slot_id,
        slot_position=slot_position or None,
        installed_at=now,
    )
    db.add(component)
    part_unit.status = "installed"
    db.flush()

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="platform_component",
        entity_id=component.id,
        action="create",
        diff={"platform_id": platform.id, "part_unit_id": part_unit.id, "serial_number": serial_number},
    )
    db.commit()
    db.refresh(component)
    return component


def remove_component(db: Session, *, actor: User, platform: Platform, component_id: int) -> PlatformComponent:
    component = db.scalar(
        select(PlatformComponent).where(
            PlatformComponent.id == component_id, PlatformComponent.platform_id == platform.id
        )
    )
    if component is None or component.removed_at is not None:
        raise ComponentNotActiveError(component_id)

    component.removed_at = datetime.now(timezone.utc)
    component.part_unit.status = "in_stock"

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="platform_component",
        entity_id=component.id,
        action="update",
        diff={"removed_at": component.removed_at.isoformat()},
    )
    db.commit()
    db.refresh(component)
    return component
