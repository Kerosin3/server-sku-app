from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user, require_role
from app.db import get_db
from app.models import Platform, PlatformItem, User
from app.services import platforms as platforms_service
from app.templating import templates

router = APIRouter(tags=["platforms"])


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    variant_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(PlatformItem).options(selectinload(PlatformItem.platform_variant)).order_by(PlatformItem.id.desc())
    if variant_id is not None:
        stmt = stmt.where(PlatformItem.platform_variant_id == variant_id)
    items = db.scalars(stmt).all()
    platforms = platforms_service.list_platforms(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"items": items, "platforms": platforms, "selected_variant_id": variant_id, "user": user},
    )


def _get_platform_or_404(db: Session, platform_id: int) -> Platform:
    platform = platforms_service.get_platform(db, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform


@router.get("/platforms", response_class=HTMLResponse)
def list_platforms(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    platforms = platforms_service.list_platforms(db)
    return templates.TemplateResponse(
        request, "platforms_list.html", {"platforms": platforms, "user": user, "error": None}
    )


@router.get("/platforms/new", response_class=HTMLResponse)
def new_platform_form(
    request: Request,
    user: User = Depends(require_role("engineer")),
):
    return templates.TemplateResponse(request, "platform_form.html", {"user": user, "error": None})


@router.post("/platforms", response_class=HTMLResponse)
def create_platform(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    try:
        platform = platforms_service.create_platform(db, name=name, description=description)
    except platforms_service.PlatformNameTakenError:
        return templates.TemplateResponse(
            request,
            "platform_form.html",
            {"user": user, "error": "Платформа с таким названием уже существует"},
            status_code=409,
        )
    return RedirectResponse(url=f"/platforms/{platform.id}", status_code=303)


@router.get("/platforms/{platform_id}", response_class=HTMLResponse)
def platform_detail(
    request: Request,
    platform_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    platform = _get_platform_or_404(db, platform_id)
    return templates.TemplateResponse(
        request, "platform_detail.html", {"user": user, "platform": platform, "error": None}
    )


@router.post("/platforms/{platform_id}/delete", response_class=HTMLResponse)
def delete_platform(
    request: Request,
    platform_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    platform = _get_platform_or_404(db, platform_id)
    try:
        platforms_service.delete_platform(db, platform)
    except platforms_service.PlatformInUseError:
        platforms = platforms_service.list_platforms(db)
        return templates.TemplateResponse(
            request,
            "platforms_list.html",
            {
                "user": user,
                "platforms": platforms,
                "error": f"Нельзя удалить платформу «{platform.name}» — у неё есть исполнения, удалите их сначала",
            },
            status_code=409,
        )
    return RedirectResponse(url="/platforms", status_code=303)
