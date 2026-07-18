from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user, require_role
from app.db import get_db
from app.models import Platform, PlatformModel, User
from app.services import platforms as platforms_service
from app.templating import templates

router = APIRouter(tags=["platforms"])


@router.get("/", response_class=HTMLResponse)
def list_platforms(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    platforms = db.scalars(
        select(Platform).options(selectinload(Platform.platform_model)).order_by(Platform.id.desc())
    ).all()
    return templates.TemplateResponse(
        request, "dashboard.html", {"platforms": platforms, "user": user}
    )


def _get_platform_or_404(db: Session, platform_id: int) -> Platform:
    platform = platforms_service.get_platform(db, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform


def _detail_context(db: Session, platform: Platform, user: User, error: str | None = None) -> dict:
    return {
        "user": user,
        "platform": platform,
        "checklist": platforms_service.slot_checklist(platform),
        "removed": platforms_service.removed_components(platform),
        "error": error,
    }


@router.get("/platforms/new", response_class=HTMLResponse)
def new_platform_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    models = db.scalars(select(PlatformModel).where(PlatformModel.is_active.is_(True)).order_by(PlatformModel.name)).all()
    return templates.TemplateResponse(
        request, "platform_form.html", {"user": user, "models": models, "error": None}
    )


@router.post("/platforms", response_class=HTMLResponse)
def create_platform(
    request: Request,
    platform_model_id: int = Form(...),
    asset_tag: str = Form(...),
    customer: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    try:
        platform = platforms_service.create_platform(
            db,
            actor=user,
            platform_model_id=platform_model_id,
            asset_tag=asset_tag,
            customer=customer,
            location=location,
            notes=notes,
        )
    except platforms_service.AssetTagTakenError:
        models = db.scalars(
            select(PlatformModel).where(PlatformModel.is_active.is_(True)).order_by(PlatformModel.name)
        ).all()
        return templates.TemplateResponse(
            request,
            "platform_form.html",
            {"user": user, "models": models, "error": "Платформа с таким asset tag уже существует"},
            status_code=409,
        )
    except platforms_service.ModelNotFoundError:
        raise HTTPException(status_code=400, detail="Unknown platform_model_id")
    return RedirectResponse(url=f"/platforms/{platform.id}", status_code=303)


@router.get("/platforms/{platform_id}", response_class=HTMLResponse)
def platform_detail(
    request: Request,
    platform_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    platform = _get_platform_or_404(db, platform_id)
    return templates.TemplateResponse(request, "platform_detail.html", _detail_context(db, platform, user))


@router.post("/platforms/{platform_id}/details", response_class=HTMLResponse)
def update_platform_details(
    request: Request,
    platform_id: int,
    customer: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    platform = _get_platform_or_404(db, platform_id)
    platforms_service.update_details(db, actor=user, platform=platform, customer=customer, location=location, notes=notes)
    return RedirectResponse(url=f"/platforms/{platform_id}", status_code=303)


@router.post("/platforms/{platform_id}/components", response_class=HTMLResponse)
def install_component(
    request: Request,
    platform_id: int,
    serial_number: str = Form(...),
    platform_model_slot_id: str = Form(""),
    slot_position: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    platform = _get_platform_or_404(db, platform_id)
    try:
        platforms_service.install_component(
            db,
            actor=user,
            platform=platform,
            serial_number=serial_number,
            platform_model_slot_id=int(platform_model_slot_id) if platform_model_slot_id else None,
            slot_position=slot_position,
        )
    except platforms_service.PartUnitNotFoundError:
        platform = _get_platform_or_404(db, platform_id)
        return templates.TemplateResponse(
            request,
            "platform_detail.html",
            _detail_context(db, platform, user, error=f"Деталь с серийным номером «{serial_number}» не найдена"),
            status_code=404,
        )
    except platforms_service.PartUnitAlreadyInstalledError:
        platform = _get_platform_or_404(db, platform_id)
        return templates.TemplateResponse(
            request,
            "platform_detail.html",
            _detail_context(db, platform, user, error="Эта деталь уже установлена в другой платформе"),
            status_code=409,
        )
    return RedirectResponse(url=f"/platforms/{platform_id}", status_code=303)


@router.post("/platforms/{platform_id}/components/{component_id}/remove", response_class=HTMLResponse)
def remove_component(
    request: Request,
    platform_id: int,
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    platform = _get_platform_or_404(db, platform_id)
    try:
        platforms_service.remove_component(db, actor=user, platform=platform, component_id=component_id)
    except platforms_service.ComponentNotActiveError:
        raise HTTPException(status_code=409, detail="Component not active on this platform")
    return RedirectResponse(url=f"/platforms/{platform_id}", status_code=303)
