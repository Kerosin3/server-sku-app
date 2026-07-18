from fastapi import APIRouter, Depends
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PartUnit, Platform

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(q: str, db: Session = Depends(get_db)):
    """
    Unified search by component serial number OR platform asset tag.
    This is the system's core user workflow — keep it fast.
    """
    part_units = db.scalars(
        select(PartUnit).where(PartUnit.serial_number.ilike(f"%{q}%")).limit(20)
    ).all()
    platforms = db.scalars(
        select(Platform).where(Platform.asset_tag.ilike(f"%{q}%")).limit(20)
    ).all()

    # TODO(agent): for part_units, also fetch the current platform (join
    # platform_components where removed_at IS NULL) — that's the answer to
    # "where is this part right now".
    return {
        "part_units": [{"id": p.id, "serial_number": p.serial_number} for p in part_units],
        "platforms": [{"id": p.id, "asset_tag": p.asset_tag} for p in platforms],
    }
