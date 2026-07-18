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

from app.models import (
    FirmwareType,
    PartCategory,
    Platform,
    PlatformVariant,
    PlatformVariantFirmwareRequirement,
    PlatformVariantMacRequirement,
    PlatformVariantSlot,
)


class VariantNameTakenError(Exception):
    pass


class SlotNameTakenError(Exception):
    pass


class CategoryNotFoundError(Exception):
    pass


class FirmwareTypeNotFoundError(Exception):
    pass


class FirmwareRequirementTakenError(Exception):
    pass


class MacLabelTakenError(Exception):
    pass


def get_variant(db: Session, variant_id: int) -> PlatformVariant | None:
    return db.scalar(
        select(PlatformVariant)
        .options(
            selectinload(PlatformVariant.slots).selectinload(PlatformVariantSlot.category),
            selectinload(PlatformVariant.platform),
            selectinload(PlatformVariant.items),
            selectinload(PlatformVariant.firmware_requirements).selectinload(
                PlatformVariantFirmwareRequirement.firmware_type
            ),
            selectinload(PlatformVariant.mac_requirements),
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
    category_id: int,
    quantity: int,
    required: bool,
) -> PlatformVariantSlot:
    if db.get(PartCategory, category_id) is None:
        raise CategoryNotFoundError(category_id)
    if db.scalar(
        select(PlatformVariantSlot).where(
            PlatformVariantSlot.platform_variant_id == variant.id, PlatformVariantSlot.slot_name == slot_name
        )
    ) is not None:
        raise SlotNameTakenError(slot_name)

    slot = PlatformVariantSlot(
        platform_variant_id=variant.id,
        slot_name=slot_name,
        category_id=category_id,
        quantity=quantity,
        required=required,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def add_firmware_requirement(
    db: Session, *, variant: PlatformVariant, firmware_type_id: int, track_backup: bool
) -> PlatformVariantFirmwareRequirement:
    if db.get(FirmwareType, firmware_type_id) is None:
        raise FirmwareTypeNotFoundError(firmware_type_id)
    if db.scalar(
        select(PlatformVariantFirmwareRequirement).where(
            PlatformVariantFirmwareRequirement.platform_variant_id == variant.id,
            PlatformVariantFirmwareRequirement.firmware_type_id == firmware_type_id,
        )
    ) is not None:
        raise FirmwareRequirementTakenError(firmware_type_id)

    requirement = PlatformVariantFirmwareRequirement(
        platform_variant_id=variant.id, firmware_type_id=firmware_type_id, track_backup=track_backup
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement


def add_mac_requirement(
    db: Session, *, variant: PlatformVariant, label: str, required: bool
) -> PlatformVariantMacRequirement:
    if db.scalar(
        select(PlatformVariantMacRequirement).where(
            PlatformVariantMacRequirement.platform_variant_id == variant.id,
            PlatformVariantMacRequirement.label == label,
        )
    ) is not None:
        raise MacLabelTakenError(label)

    requirement = PlatformVariantMacRequirement(
        platform_variant_id=variant.id, label=label, required=required
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement
