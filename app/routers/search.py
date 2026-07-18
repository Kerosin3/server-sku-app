from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PartUnit, PlatformItem

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(q: str, db: Session = Depends(get_db)):
    """
    Unified search by component serial number OR platform_item asset tag.
    This is the system's core user workflow — keep it fast.
    """
    part_units = db.scalars(
        select(PartUnit).where(PartUnit.serial_number.ilike(f"%{q}%")).limit(20)
    ).all()
    items = db.scalars(
        select(PlatformItem).where(PlatformItem.asset_tag.ilike(f"%{q}%")).limit(20)
    ).all()

    # TODO(agent): for part_units, also fetch the current platform_item (join
    # platform_components where removed_at IS NULL) — that's the answer to
    # "where is this part right now". Also: this returns JSON, but
    # dashboard.html's hx-get targets an HTML swap — wire an HTML partial
    # response here before this search box actually renders anything.
    return {
        "part_units": [{"id": p.id, "serial_number": p.serial_number} for p in part_units],
        "items": [{"id": i.id, "asset_tag": i.asset_tag} for i in items],
    }
