"""
Business logic for firmware_records — append-only version history per
part_unit, matched against the owning item's platform_variant firmware
requirements (see app/models/platform_variant_firmware_requirement.py).
No audit_log entry here, same reasoning as platform_events: a
FirmwareRecord already carries user_id + recorded_at intrinsically.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FirmwareRecord, PartUnit, PlatformItem, User


class PartUnitNotInstalledError(Exception):
    """part_unit_id isn't an actively-installed component of this item."""


class FirmwareTypeNotRequiredError(Exception):
    """This item's variant doesn't declare a requirement for this firmware type."""


class BackupNotTrackedError(Exception):
    """image_slot=backup was given but the requirement doesn't track a backup image."""


class PurchasedPartCannotCarryFirmwareError(Exception):
    """Firmware lives on in-house boards, not on purchased commodity parts (CPU, RAM, PSU, ...)."""


def _active_part_unit_ids(item: PlatformItem) -> set[int]:
    return {c.part_unit_id for c in item.components if c.removed_at is None}


def record_firmware(
    db: Session,
    *,
    actor: User,
    item: PlatformItem,
    part_unit_id: int,
    firmware_type_id: int,
    image_slot: str,
    version: str,
    notes: str | None,
) -> FirmwareRecord:
    component = next(
        (c for c in item.components if c.removed_at is None and c.part_unit_id == part_unit_id), None
    )
    if component is None:
        raise PartUnitNotInstalledError(part_unit_id)
    if component.part_unit.part_type.category.group != "custom":
        raise PurchasedPartCannotCarryFirmwareError(part_unit_id)

    requirement = next(
        (r for r in item.platform_variant.firmware_requirements if r.firmware_type_id == firmware_type_id),
        None,
    )
    if requirement is None:
        raise FirmwareTypeNotRequiredError(firmware_type_id)
    if image_slot == "backup" and not requirement.track_backup:
        raise BackupNotTrackedError(firmware_type_id)

    record = FirmwareRecord(
        part_unit_id=part_unit_id,
        firmware_type_id=firmware_type_id,
        image_slot=image_slot,
        version=version,
        user_id=actor.id,
        notes=notes or None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def firmware_checklist(db: Session, item: PlatformItem) -> list[dict]:
    """
    For each firmware requirement of this item's variant, the latest
    recorded version (primary, and backup if tracked) among the item's
    currently-installed components — or None if nothing's been recorded
    yet.
    """
    part_unit_ids = _active_part_unit_ids(item)
    records: list[FirmwareRecord] = []
    if part_unit_ids:
        records = list(
            db.scalars(
                select(FirmwareRecord)
                .where(FirmwareRecord.part_unit_id.in_(part_unit_ids))
                .order_by(FirmwareRecord.recorded_at.desc())
            ).all()
        )

    def latest(firmware_type_id: int, image_slot: str) -> FirmwareRecord | None:
        return next(
            (r for r in records if r.firmware_type_id == firmware_type_id and r.image_slot == image_slot),
            None,
        )

    rows = []
    for requirement in item.platform_variant.firmware_requirements:
        rows.append(
            {
                "requirement": requirement,
                "primary": latest(requirement.firmware_type_id, "primary"),
                "backup": latest(requirement.firmware_type_id, "backup") if requirement.track_backup else None,
            }
        )
    return rows
