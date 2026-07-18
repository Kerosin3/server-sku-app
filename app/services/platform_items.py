"""
Business logic for platform_items — a single assembled, asset-tagged
physical unit ("изделие") of one PlatformVariant, and its as-built
component list. Every mutation here writes an audit_log row per
AGENTS.md.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PartType,
    PartUnit,
    PlatformComponent,
    PlatformItem,
    PlatformVariant,
    PlatformVariantFirmwareRequirement,
    PlatformVariantSlot,
    User,
)
from app.services import audit


class VariantNotFoundError(Exception):
    pass


class AssetTagTakenError(Exception):
    pass


class SlotNotFoundError(Exception):
    pass


class ArticleRequiredError(Exception):
    """Serial number is unknown and no article was given to register a new part."""


class PartUnitAlreadyInstalledError(Exception):
    pass


class ComponentNotActiveError(Exception):
    pass


def get_item(db: Session, item_id: int) -> PlatformItem | None:
    return db.scalar(
        select(PlatformItem)
        .options(
            selectinload(PlatformItem.platform_variant)
            .selectinload(PlatformVariant.slots)
            .selectinload(PlatformVariantSlot.category),
            selectinload(PlatformItem.platform_variant).selectinload(PlatformVariant.platform),
            selectinload(PlatformItem.platform_variant)
            .selectinload(PlatformVariant.firmware_requirements)
            .selectinload(PlatformVariantFirmwareRequirement.firmware_type),
            selectinload(PlatformItem.platform_variant).selectinload(PlatformVariant.mac_requirements),
            selectinload(PlatformItem.components)
            .selectinload(PlatformComponent.part_unit)
            .selectinload(PartUnit.part_type)
            .selectinload(PartType.category),
            selectinload(PlatformItem.components)
            .selectinload(PlatformComponent.platform_variant_slot)
            .selectinload(PlatformVariantSlot.category),
        )
        .where(PlatformItem.id == item_id)
    )


def slot_checklist(item: PlatformItem) -> list[dict]:
    """Required (as-planned) slots vs currently-installed (as-built) count."""
    active = [c for c in item.components if c.removed_at is None]
    counts: dict[int, int] = {}
    for c in active:
        if c.platform_variant_slot_id is not None:
            counts[c.platform_variant_slot_id] = counts.get(c.platform_variant_slot_id, 0) + 1

    rows = []
    for slot in item.platform_variant.slots:
        installed = counts.get(slot.id, 0)
        rows.append(
            {
                "slot": slot,
                "installed": installed,
                "complete": installed >= slot.quantity if slot.required else True,
            }
        )
    return rows


def removed_components(item: PlatformItem) -> list[PlatformComponent]:
    return sorted(
        (c for c in item.components if c.removed_at is not None),
        key=lambda c: c.removed_at,
        reverse=True,
    )


def create_item(
    db: Session,
    *,
    actor: User,
    platform_variant_id: int,
    asset_tag: str,
    customer: str | None,
    location: str | None,
    notes: str | None,
) -> PlatformItem:
    if db.get(PlatformVariant, platform_variant_id) is None:
        raise VariantNotFoundError(platform_variant_id)
    if db.scalar(select(PlatformItem).where(PlatformItem.asset_tag == asset_tag)) is not None:
        raise AssetTagTakenError(asset_tag)

    item = PlatformItem(
        platform_variant_id=platform_variant_id,
        asset_tag=asset_tag,
        customer=customer or None,
        location=location or None,
        notes=notes or None,
    )
    db.add(item)
    db.flush()

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="platform_item",
        entity_id=item.id,
        action="create",
        diff={"asset_tag": asset_tag, "platform_variant_id": platform_variant_id},
    )
    db.commit()
    db.refresh(item)
    return item


def update_details(
    db: Session,
    *,
    actor: User,
    item: PlatformItem,
    customer: str | None,
    location: str | None,
    notes: str | None,
) -> PlatformItem:
    diff = {}
    for field, new_value in (("customer", customer or None), ("location", location or None), ("notes", notes or None)):
        old_value = getattr(item, field)
        if old_value != new_value:
            diff[field] = [old_value, new_value]
            setattr(item, field, new_value)

    if diff:
        audit.record(
            db, actor_id=actor.id, entity_type="platform_item", entity_id=item.id, action="update", diff=diff
        )
        db.commit()
        db.refresh(item)
    return item


def _find_or_create_part_unit(
    db: Session, *, slot: PlatformVariantSlot, serial_number: str, article: str | None, comment: str | None
) -> PartUnit:
    """
    part_types/part_units have no CRUD of their own yet (AGENTS.md roadmap
    item 2), so a never-before-seen serial number is registered here on
    the fly: find-or-create a PartType by (category, article) within the
    slot's category — article is always required for a new part.
    """
    if not article:
        raise ArticleRequiredError(serial_number)
    part_type = db.scalar(
        select(PartType).where(
            PartType.category_id == slot.category_id, func.lower(PartType.model_name) == article.lower()
        )
    )
    if part_type is None:
        part_type = PartType(category_id=slot.category_id, manufacturer="", model_name=article)
        db.add(part_type)
        db.flush()

    part_unit = PartUnit(part_type_id=part_type.id, serial_number=serial_number, notes=comment or None)
    db.add(part_unit)
    db.flush()
    return part_unit


def install_component(
    db: Session,
    *,
    actor: User,
    item: PlatformItem,
    serial_number: str,
    platform_variant_slot_id: int,
    article: str | None,
    comment: str | None,
) -> PlatformComponent:
    slot = db.scalar(
        select(PlatformVariantSlot).where(
            PlatformVariantSlot.id == platform_variant_slot_id,
            PlatformVariantSlot.platform_variant_id == item.platform_variant_id,
        )
    )
    if slot is None:
        raise SlotNotFoundError(platform_variant_slot_id)

    part_unit = db.scalar(select(PartUnit).where(PartUnit.serial_number == serial_number))
    if part_unit is None:
        part_unit = _find_or_create_part_unit(
            db, slot=slot, serial_number=serial_number, article=article, comment=comment
        )

    already_installed = db.scalar(
        select(PlatformComponent).where(
            PlatformComponent.part_unit_id == part_unit.id, PlatformComponent.removed_at.is_(None)
        )
    )
    if already_installed is not None:
        raise PartUnitAlreadyInstalledError(serial_number)

    now = datetime.now(timezone.utc)
    component = PlatformComponent(
        platform_item_id=item.id,
        part_unit_id=part_unit.id,
        platform_variant_slot_id=platform_variant_slot_id,
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
        diff={"platform_item_id": item.id, "part_unit_id": part_unit.id, "serial_number": serial_number},
    )
    db.commit()
    db.refresh(component)
    return component


def remove_component(db: Session, *, actor: User, item: PlatformItem, component_id: int) -> PlatformComponent:
    component = db.scalar(
        select(PlatformComponent).where(
            PlatformComponent.id == component_id, PlatformComponent.platform_item_id == item.id
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
