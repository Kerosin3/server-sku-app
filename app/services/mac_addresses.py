"""
Business logic for mac_addresses — MAC assignment for an item or one of
its currently-installed part_units, matched against the owning item's
platform_variant MAC requirements (see
app/models/platform_variant_mac_requirement.py).

Unlike PlatformEvent/FirmwareRecord, a MacAddress row carries no
user_id/actor of its own and (by design, see the model) isn't an
append-only log — removing one is a real delete, not a removed_at
marker. So mutations here go through audit_log, same as
platform_items/platform_components.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MacAddress, PlatformItem, User
from app.services import audit


class InvalidMacFormatError(Exception):
    pass


class MacAddressTakenError(Exception):
    pass


class PartUnitNotInstalledError(Exception):
    """part_unit_id isn't an actively-installed component of this item."""


class MacNotFoundError(Exception):
    pass


def normalize_mac(raw: str) -> str:
    hex_digits = re.sub(r"[^0-9A-Fa-f]", "", raw)
    if len(hex_digits) != 12:
        raise InvalidMacFormatError(raw)
    hex_digits = hex_digits.upper()
    return ":".join(hex_digits[i : i + 2] for i in range(0, 12, 2))


def _active_part_unit_ids(item: PlatformItem) -> set[int]:
    return {c.part_unit_id for c in item.components if c.removed_at is None}


def add_mac(
    db: Session,
    *,
    actor: User,
    item: PlatformItem,
    mac_address: str,
    label: str | None,
    part_unit_id: int | None,
) -> MacAddress:
    normalized = normalize_mac(mac_address)

    if part_unit_id is not None and part_unit_id not in _active_part_unit_ids(item):
        raise PartUnitNotInstalledError(part_unit_id)
    if db.scalar(select(MacAddress).where(MacAddress.mac_address == normalized)) is not None:
        raise MacAddressTakenError(normalized)

    mac = MacAddress(
        mac_address=normalized,
        label=label or None,
        platform_item_id=item.id if part_unit_id is None else None,
        part_unit_id=part_unit_id,
    )
    db.add(mac)
    db.flush()

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="mac_address",
        entity_id=mac.id,
        action="create",
        diff={"mac_address": normalized, "label": label, "part_unit_id": part_unit_id},
    )
    db.commit()
    db.refresh(mac)
    return mac


def remove_mac(db: Session, *, actor: User, item: PlatformItem, mac_id: int) -> None:
    active_part_unit_ids = _active_part_unit_ids(item)
    mac = db.get(MacAddress, mac_id)
    owned_by_item = mac is not None and (
        mac.platform_item_id == item.id or mac.part_unit_id in active_part_unit_ids
    )
    if not owned_by_item:
        raise MacNotFoundError(mac_id)

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="mac_address",
        entity_id=mac.id,
        action="delete",
        diff={"mac_address": mac.mac_address, "label": mac.label},
    )
    db.delete(mac)
    db.commit()


def mac_checklist(db: Session, item: PlatformItem) -> list[dict]:
    part_unit_ids = _active_part_unit_ids(item)
    owner_filter = MacAddress.platform_item_id == item.id
    if part_unit_ids:
        owner_filter = owner_filter | MacAddress.part_unit_id.in_(part_unit_ids)
    macs = list(db.scalars(select(MacAddress).where(owner_filter)).all())

    rows = []
    for requirement in item.platform_variant.mac_requirements:
        matches = [m for m in macs if (m.label or "").strip().lower() == requirement.label.strip().lower()]
        rows.append({"requirement": requirement, "macs": matches})
    return rows
