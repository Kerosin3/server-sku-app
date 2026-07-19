"""
Business logic for exporting the full recorded history of one
platform_item to a single JSON document — as-built configuration,
firmware/MAC state, and the full event log, for handing off to a
customer or archiving outside the app. See AGENTS.md roadmap.
"""
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.i18n import label
from app.models import FirmwareRecord, MacAddress, PlatformComponent, PlatformItem


def _dt(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _component_dict(c: PlatformComponent) -> dict:
    part_unit = c.part_unit
    part_type = part_unit.part_type
    return {
        "detail": c.platform_variant_slot.slot_name if c.platform_variant_slot else None,
        "category": part_type.category.name,
        "article": part_type.model_name,
        "serial_number": part_unit.serial_number,
        "comment": part_unit.notes,
        "installed_at": _dt(c.installed_at),
        "removed_at": _dt(c.removed_at),
        "currently_installed": c.removed_at is None,
    }


def export_item(db: Session, item: PlatformItem, *, include_customer: bool) -> dict:
    all_part_unit_ids = {c.part_unit_id for c in item.components}

    firmware_records: list[FirmwareRecord] = []
    if all_part_unit_ids:
        firmware_records = list(
            db.scalars(
                select(FirmwareRecord)
                .where(FirmwareRecord.part_unit_id.in_(all_part_unit_ids))
                .order_by(FirmwareRecord.recorded_at.desc())
            ).all()
        )

    mac_filter = MacAddress.platform_item_id == item.id
    if all_part_unit_ids:
        mac_filter = mac_filter | MacAddress.part_unit_id.in_(all_part_unit_ids)
    macs = list(db.scalars(select(MacAddress).where(mac_filter)).all())

    data = {
        "asset_tag": item.asset_tag,
        "platform": item.platform_variant.platform.name,
        "variant": item.platform_variant.name,
        "status": label(item.status, "platform_status"),
        "location": item.location,
        "notes": item.notes,
        "created_at": _dt(item.created_at),
        "updated_at": _dt(item.updated_at),
        "components": {
            "installed": [_component_dict(c) for c in item.components if c.removed_at is None],
            "removed": [_component_dict(c) for c in item.components if c.removed_at is not None],
        },
        "firmware": [
            {
                "part_serial_number": r.part_unit.serial_number,
                "firmware_type": r.firmware_type.name,
                "image_slot": r.image_slot,
                "version": r.version,
                "recorded_at": _dt(r.recorded_at),
                "recorded_by": r.user.username if r.user else None,
                "notes": r.notes,
            }
            for r in firmware_records
        ],
        "mac_addresses": [
            {
                "mac_address": m.mac_address,
                "label": m.label,
                "owner": "item" if m.platform_item_id else "part_unit",
                "part_serial_number": m.part_unit.serial_number if m.part_unit_id else None,
            }
            for m in macs
        ],
        "events": [
            {
                "event_type": label(e.event_type, "platform_event_type"),
                "occurred_at": _dt(e.occurred_at),
                "user": e.user.username if e.user else None,
                "notes": e.notes,
            }
            for e in item.events
        ],
    }
    if include_customer:
        data["customer"] = item.customer
    return data
