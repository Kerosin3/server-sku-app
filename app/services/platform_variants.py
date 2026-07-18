"""
Business logic for platform_variants / platform_variant_slots — the
"constructor" for one BOM/configuration within a Platform family. No
audit_log entries here: AGENTS.md requires auditing for part_units,
platform_items, platform_components (and users) because those track
physical inventory and access; the variant catalog itself is reference
data, not inventory state.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.i18n import PART_CATEGORIES
from app.models import Platform, PlatformVariant, PlatformVariantSlot


class VariantNameTakenError(Exception):
    pass


class SlotNameTakenError(Exception):
    pass


class InvalidCategoryError(Exception):
    pass


def get_variant(db: Session, variant_id: int) -> PlatformVariant | None:
    return db.scalar(
        select(PlatformVariant)
        .options(
            selectinload(PlatformVariant.slots).selectinload(PlatformVariantSlot.part_type),
            selectinload(PlatformVariant.platform),
            selectinload(PlatformVariant.items),
        )
        .where(PlatformVariant.id == variant_id)
    )


def create_variant(db: Session, *, platform: Platform, name: str, description: str | None) -> PlatformVariant:
    if db.scalar(
        select(PlatformVariant).where(PlatformVariant.platform_id == platform.id, PlatformVariant.name == name)
    ) is not None:
        raise VariantNameTakenError(name)

    variant = PlatformVariant(platform_id=platform.id, name=name, description=description or None)
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


def add_slot(
    db: Session,
    *,
    variant: PlatformVariant,
    slot_name: str,
    category: str,
    part_type_id: int | None,
    quantity: int,
    required: bool,
) -> PlatformVariantSlot:
    if category not in PART_CATEGORIES:
        raise InvalidCategoryError(category)
    if db.scalar(
        select(PlatformVariantSlot).where(
            PlatformVariantSlot.platform_variant_id == variant.id, PlatformVariantSlot.slot_name == slot_name
        )
    ) is not None:
        raise SlotNameTakenError(slot_name)

    slot = PlatformVariantSlot(
        platform_variant_id=variant.id,
        slot_name=slot_name,
        category=category,
        part_type_id=part_type_id,
        quantity=quantity,
        required=required,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot
