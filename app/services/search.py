"""
Business logic for the unified search bar on the dashboard — by
component serial number, item asset tag, or MAC address. This is the
system's core "where is this thing" workflow, see AGENTS.md.
"""
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import MacAddress, PartUnit, PlatformComponent, PlatformItem

MIN_QUERY_LENGTH = 2


def _current_item_for_part_unit(db: Session, part_unit_id: int) -> PlatformItem | None:
    component = db.scalar(
        select(PlatformComponent)
        .options(selectinload(PlatformComponent.platform_item))
        .where(PlatformComponent.part_unit_id == part_unit_id, PlatformComponent.removed_at.is_(None))
    )
    return component.platform_item if component else None


def search(db: Session, q: str) -> dict:
    q = q.strip()
    if len(q) < MIN_QUERY_LENGTH:
        return {"items": [], "parts": [], "macs": []}

    items = db.scalars(
        select(PlatformItem)
        .options(selectinload(PlatformItem.platform_variant))
        .where(PlatformItem.asset_tag.ilike(f"%{q}%"))
        .limit(20)
    ).all()

    part_units = db.scalars(
        select(PartUnit)
        .options(selectinload(PartUnit.part_type))
        .where(PartUnit.serial_number.ilike(f"%{q}%"))
        .limit(20)
    ).all()
    parts = [{"part_unit": p, "current_item": _current_item_for_part_unit(db, p.id)} for p in part_units]

    # MAC addresses are stored colon-separated (see normalize_mac); a plain
    # ILIKE on the raw query would miss "DEADBEEF0001" or "dead-beef-0001"
    # pasted from elsewhere, so also match against the separator-stripped
    # form on both sides when the query itself looks like hex.
    mac_filters = [MacAddress.mac_address.ilike(f"%{q}%")]
    stripped_q = re.sub(r"[^0-9A-Fa-f]", "", q)
    if stripped_q:
        mac_filters.append(func.replace(MacAddress.mac_address, ":", "").ilike(f"%{stripped_q}%"))

    macs = db.scalars(
        select(MacAddress)
        .options(
            selectinload(MacAddress.platform_item),
            selectinload(MacAddress.part_unit).selectinload(PartUnit.part_type),
        )
        .where(or_(*mac_filters))
        .limit(20)
    ).all()
    mac_hits = []
    for m in macs:
        owner_item = m.platform_item if m.platform_item_id else _current_item_for_part_unit(db, m.part_unit_id)
        mac_hits.append({"mac": m, "owner_item": owner_item})

    return {"items": items, "parts": parts, "macs": mac_hits}
