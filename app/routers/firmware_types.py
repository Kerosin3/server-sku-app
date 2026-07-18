from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import FirmwareType, User
from app.services import firmware_types as firmware_types_service
from app.templating import templates

router = APIRouter(prefix="/firmware-types", tags=["firmware_types"])


def _get_firmware_type_or_404(db: Session, firmware_type_id: int) -> FirmwareType:
    firmware_type = db.get(FirmwareType, firmware_type_id)
    if firmware_type is None:
        raise HTTPException(status_code=404, detail="Firmware type not found")
    return firmware_type


@router.get("", response_class=HTMLResponse)
def list_firmware_types(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    firmware_types = firmware_types_service.list_firmware_types(db)
    return templates.TemplateResponse(
        request, "firmware_types_list.html", {"user": user, "firmware_types": firmware_types, "error": None}
    )


@router.post("", response_class=HTMLResponse)
def create_firmware_type(
    request: Request,
    name: str = Form(...),
    platform_variant_id: str = Form(""),
    next_url: str = Form("/firmware-types", alias="next"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    try:
        firmware_types_service.create_firmware_type(
            db, name=name, platform_variant_id=int(platform_variant_id) if platform_variant_id else None
        )
    except firmware_types_service.FirmwareTypeNameTakenError:
        firmware_types = firmware_types_service.list_firmware_types(db)
        return templates.TemplateResponse(
            request,
            "firmware_types_list.html",
            {
                "user": user,
                "firmware_types": firmware_types,
                "error": "Тип прошивки с таким названием уже существует в этой области видимости",
            },
            status_code=409,
        )
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/{firmware_type_id}/delete", response_class=HTMLResponse)
def delete_firmware_type(
    request: Request,
    firmware_type_id: int,
    next_url: str = Form("/firmware-types", alias="next"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    firmware_type = _get_firmware_type_or_404(db, firmware_type_id)
    try:
        firmware_types_service.delete_firmware_type(db, firmware_type)
    except firmware_types_service.FirmwareTypeInUseError:
        firmware_types = firmware_types_service.list_firmware_types(db)
        return templates.TemplateResponse(
            request,
            "firmware_types_list.html",
            {"user": user, "firmware_types": firmware_types, "error": "Тип прошивки используется, удалить нельзя"},
            status_code=409,
        )
    return RedirectResponse(url=next_url, status_code=303)
