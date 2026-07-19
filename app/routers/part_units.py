from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import PartUnit, User
from app.services import part_units as part_units_service
from app.templating import templates

router = APIRouter(prefix="/part-units", tags=["part_units"])

# TODO(agent): implement per AGENTS.md roadmap, item 2:
# - GET  /part-units             list, filterable by part_type/status
# - POST /part-units             create (require_role("engineer")), check
#                                 serial_number uniqueness -> 409 on conflict
# - GET  /part-units/{id}        detail page + installation history (all
#                                 platform_components rows for this
#                                 part_unit_id, ordered by installed_at desc)
# - POST /part-units/import      bulk CSV import (roadmap item 6)
#
# /unowned below (parts not currently installed anywhere — "детали без
# владельца") is implemented ahead of the rest of this roadmap item,
# since it doesn't need part_type/part_unit creation UI to be useful.


def _get_part_unit_or_404(db: Session, part_unit_id: int) -> PartUnit:
    part_unit = db.get(PartUnit, part_unit_id)
    if part_unit is None:
        raise HTTPException(status_code=404, detail="Part unit not found")
    return part_unit


def _unowned_context(db: Session, user: User, error: str | None = None) -> dict:
    part_units = part_units_service.list_unowned(db)
    rows = [
        {"part_unit": p, "last_component": part_units_service.last_installation(db, p.id)} for p in part_units
    ]
    return {"user": user, "rows": rows, "error": error}


@router.get("/unowned", response_class=HTMLResponse)
def list_unowned(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    return templates.TemplateResponse(request, "part_units_unowned.html", _unowned_context(db, user))


@router.post("/{part_unit_id}/delete", response_class=HTMLResponse)
def delete_part_unit(
    request: Request,
    part_unit_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    part_unit = _get_part_unit_or_404(db, part_unit_id)
    try:
        part_units_service.delete_part_unit(db, actor=user, part_unit=part_unit)
    except part_units_service.PartUnitInstalledError:
        return templates.TemplateResponse(
            request,
            "part_units_unowned.html",
            _unowned_context(db, user, error="Деталь сейчас установлена в изделии — список обновлён"),
            status_code=409,
        )
    return RedirectResponse(url="/part-units/unowned", status_code=303)
