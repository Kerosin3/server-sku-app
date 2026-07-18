from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.db import get_db
from app.models import PlatformItem, PlatformVariant, User
from app.services import platform_items as items_service
from app.services import platform_variants as variants_service
from app.templating import templates

router = APIRouter(tags=["platform_items"])


def _get_variant_or_404(db: Session, variant_id: int) -> PlatformVariant:
    variant = variants_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Platform variant not found")
    return variant


def _get_item_or_404(db: Session, item_id: int) -> PlatformItem:
    item = items_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Platform item not found")
    return item


def _detail_context(item: PlatformItem, user: User, error: str | None = None) -> dict:
    return {
        "user": user,
        "item": item,
        "checklist": items_service.slot_checklist(item),
        "removed": items_service.removed_components(item),
        "error": error,
    }


@router.get("/variants/{variant_id}/items/new", response_class=HTMLResponse)
def new_item_form(
    request: Request,
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    return templates.TemplateResponse(
        request, "item_form.html", {"user": user, "variant": variant, "error": None}
    )


@router.post("/variants/{variant_id}/items", response_class=HTMLResponse)
def create_item(
    request: Request,
    variant_id: int,
    asset_tag: str = Form(...),
    customer: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    try:
        item = items_service.create_item(
            db,
            actor=user,
            platform_variant_id=variant_id,
            asset_tag=asset_tag,
            customer=customer,
            location=location,
            notes=notes,
        )
    except items_service.AssetTagTakenError:
        return templates.TemplateResponse(
            request,
            "item_form.html",
            {"user": user, "variant": variant, "error": "Изделие с таким asset tag уже существует"},
            status_code=409,
        )
    return RedirectResponse(url=f"/items/{item.id}", status_code=303)


@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(request, "item_detail.html", _detail_context(item, user))


@router.post("/items/{item_id}/details", response_class=HTMLResponse)
def update_item_details(
    request: Request,
    item_id: int,
    customer: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    items_service.update_details(db, actor=user, item=item, customer=customer, location=location, notes=notes)
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/components", response_class=HTMLResponse)
def install_component(
    request: Request,
    item_id: int,
    serial_number: str = Form(...),
    platform_variant_slot_id: str = Form(""),
    slot_position: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        items_service.install_component(
            db,
            actor=user,
            item=item,
            serial_number=serial_number,
            platform_variant_slot_id=int(platform_variant_slot_id) if platform_variant_slot_id else None,
            slot_position=slot_position,
        )
    except items_service.PartUnitNotFoundError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(item, user, error=f"Деталь с серийным номером «{serial_number}» не найдена"),
            status_code=404,
        )
    except items_service.PartUnitAlreadyInstalledError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(item, user, error="Эта деталь уже установлена в другом изделии"),
            status_code=409,
        )
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/components/{component_id}/remove", response_class=HTMLResponse)
def remove_component(
    request: Request,
    item_id: int,
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        items_service.remove_component(db, actor=user, item=item, component_id=component_id)
    except items_service.ComponentNotActiveError:
        raise HTTPException(status_code=409, detail="Component not active on this item")
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)
