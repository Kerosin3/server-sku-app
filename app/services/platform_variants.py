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
    Attachment,
    FirmwareRecord,
    FirmwareType,
    PartCategory,
    PartType,
    Platform,
    PlatformItem,
    PlatformVariant,
    PlatformVariantFirmwareRequirement,
    PlatformVariantMacRequirement,
    PlatformVariantSlot,
)
from app.services import attachments as attachments_service


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


class VariantInUseError(Exception):
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
            selectinload(PlatformVariant.files).selectinload(Attachment.uploaded_by),
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


def delete_variant(db: Session, variant: PlatformVariant) -> None:
    """
    Blocked if the variant has any assembled platform_items — those are
    physical inventory and must never be silently deleted. The variant's
    own BOM definition (slots, firmware/MAC requirements, and any
    part_categories/firmware_types scoped only to this variant) is
    reference data, not inventory, so it cascades — unless a scoped
    category/firmware_type is itself still in use elsewhere (part_types,
    firmware_records), in which case deletion is blocked too.
    """
    if db.scalar(select(PlatformItem.id).where(PlatformItem.platform_variant_id == variant.id)) is not None:
        raise VariantInUseError(variant.id)

    try:
        db.query(PlatformVariantSlot).filter(PlatformVariantSlot.platform_variant_id == variant.id).delete()
        db.query(PlatformVariantFirmwareRequirement).filter(
            PlatformVariantFirmwareRequirement.platform_variant_id == variant.id
        ).delete()
        db.query(PlatformVariantMacRequirement).filter(
            PlatformVariantMacRequirement.platform_variant_id == variant.id
        ).delete()
        db.flush()

        for category in list(
            db.scalars(select(PartCategory).where(PartCategory.platform_variant_id == variant.id))
        ):
            still_in_use = (
                db.scalar(select(PartType.id).where(PartType.category_id == category.id)) is not None
                or db.scalar(
                    select(PlatformVariantSlot.id).where(PlatformVariantSlot.category_id == category.id)
                )
                is not None
            )
            if still_in_use:
                raise VariantInUseError(variant.id)
            db.delete(category)

        for firmware_type in list(
            db.scalars(select(FirmwareType).where(FirmwareType.platform_variant_id == variant.id))
        ):
            still_in_use = (
                db.scalar(
                    select(FirmwareRecord.id).where(FirmwareRecord.firmware_type_id == firmware_type.id)
                )
                is not None
                or db.scalar(
                    select(PlatformVariantFirmwareRequirement.id).where(
                        PlatformVariantFirmwareRequirement.firmware_type_id == firmware_type.id
                    )
                )
                is not None
            )
            if still_in_use:
                raise VariantInUseError(variant.id)
            db.delete(firmware_type)

        # Collect disk paths before deleting the rows — unlinked only
        # after the transaction actually commits, so a rollback above
        # (VariantInUseError) never leaves an orphaned DB row pointing
        # at an already-deleted file.
        file_paths = [attachments_service.file_path(f) for f in variant.files]
        db.query(Attachment).filter(Attachment.platform_variant_id == variant.id).delete()

        db.delete(variant)
        db.commit()
    except VariantInUseError:
        db.rollback()
        raise

    for path in file_paths:
        path.unlink(missing_ok=True)
