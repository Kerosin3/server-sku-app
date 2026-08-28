"""
Business logic for firmware_types — user-editable catalog, same
global-vs-variant-scoped pattern as part_categories (see
app/services/part_categories.py), including auditing both creation and
deletion, for the same reasons.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FirmwareRecord, FirmwareType, PlatformVariantFirmwareRequirement, User
from app.services import audit


class FirmwareTypeNameTakenError(Exception):
    pass


class FirmwareTypeInUseError(Exception):
    pass


def list_firmware_types(db: Session) -> list[FirmwareType]:
    return list(db.scalars(select(FirmwareType).order_by(FirmwareType.name)).all())


def list_available_for_variant(db: Session, platform_variant_id: int) -> list[FirmwareType]:
    return list(
        db.scalars(
            select(FirmwareType)
            .where(
                (FirmwareType.platform_variant_id.is_(None))
                | (FirmwareType.platform_variant_id == platform_variant_id)
            )
            .order_by(FirmwareType.name)
        ).all()
    )


def create_firmware_type(
    db: Session, *, actor: User, name: str, platform_variant_id: int | None = None
) -> FirmwareType:
    scope_filter = (
        FirmwareType.platform_variant_id.is_(None)
        if platform_variant_id is None
        else FirmwareType.platform_variant_id == platform_variant_id
    )
    if db.scalar(select(FirmwareType).where(FirmwareType.name == name, scope_filter)) is not None:
        raise FirmwareTypeNameTakenError(name)

    firmware_type = FirmwareType(name=name, platform_variant_id=platform_variant_id)
    db.add(firmware_type)
    db.flush()

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="firmware_type",
        entity_id=firmware_type.id,
        action="create",
        diff={"name": name, "platform_variant_id": platform_variant_id},
    )
    db.commit()
    db.refresh(firmware_type)
    return firmware_type


def delete_firmware_type(db: Session, *, actor: User, firmware_type: FirmwareType) -> None:
    in_use = db.scalar(
        select(FirmwareRecord.id).where(FirmwareRecord.firmware_type_id == firmware_type.id)
    ) is not None or (
        db.scalar(
            select(PlatformVariantFirmwareRequirement.id).where(
                PlatformVariantFirmwareRequirement.firmware_type_id == firmware_type.id
            )
        )
        is not None
    )
    if in_use:
        raise FirmwareTypeInUseError(firmware_type.id)

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="firmware_type",
        entity_id=firmware_type.id,
        action="delete",
        diff={"name": firmware_type.name},
    )
    db.delete(firmware_type)
    db.commit()
