from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import Platform, PlatformVariant, User
from app.services import firmware_types as firmware_types_service
from app.services import part_categories as categories_service
from app.services import platforms as platforms_service
from app.services import platform_variants as variants_service
from app.templating import templates

router = APIRouter(tags=["platform_variants"])


def _get_platform_or_404(db: Session, platform_id: int) -> Platform:
    platform = platforms_service.get_platform(db, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform


def _get_variant_or_404(db: Session, variant_id: int) -> PlatformVariant:
    variant = variants_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Platform variant not found")
    return variant


def _variant_detail_context(db: Session, variant: PlatformVariant, user: User, error: str | None = None) -> dict:
    return {
        "user": user,
        "variant": variant,
        "categories": categories_service.list_available_for_variant(db, variant.id),
        "firmware_types": firmware_types_service.list_available_for_variant(db, variant.id),
        "error": error,
    }


@router.get("/platforms/{platform_id}/variants/new", response_class=HTMLResponse)
def new_variant_form(
    request: Request,
    platform_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    platform = _get_platform_or_404(db, platform_id)
    return templates.TemplateResponse(
        request, "variant_form.html", {"user": user, "platform": platform, "error": None}
    )


@router.post("/platforms/{platform_id}/variants", response_class=HTMLResponse)
def create_variant(
    request: Request,
    platform_id: int,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    platform = _get_platform_or_404(db, platform_id)
    try:
        variant = variants_service.create_variant(db, platform=platform, name=name, description=description)
    except variants_service.VariantNameTakenError:
        return templates.TemplateResponse(
            request,
            "variant_form.html",
            {"user": user, "platform": platform, "error": "Исполнение с таким названием уже есть у этой платформы"},
            status_code=409,
        )
    return RedirectResponse(url=f"/variants/{variant.id}", status_code=303)


@router.get("/variants/{variant_id}", response_class=HTMLResponse)
def variant_detail(
    request: Request,
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    variant = _get_variant_or_404(db, variant_id)
    return templates.TemplateResponse(
        request, "variant_detail.html", _variant_detail_context(db, variant, user)
    )


@router.post("/variants/{variant_id}/slots", response_class=HTMLResponse)
def add_slot(
    request: Request,
    variant_id: int,
    slot_name: str = Form(...),
    category_id: int = Form(...),
    quantity: int = Form(1),
    required: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    try:
        variants_service.add_slot(
            db,
            variant=variant,
            slot_name=slot_name,
            category_id=category_id,
            quantity=quantity,
            required=required,
        )
    except (variants_service.SlotNameTakenError, variants_service.CategoryNotFoundError) as exc:
        error = (
            "Слот с таким именем уже есть в этом исполнении"
            if isinstance(exc, variants_service.SlotNameTakenError)
            else "Категория не найдена"
        )
        variant = _get_variant_or_404(db, variant_id)
        return templates.TemplateResponse(
            request,
            "variant_detail.html",
            _variant_detail_context(db, variant, user, error=error),
            status_code=409 if isinstance(exc, variants_service.SlotNameTakenError) else 400,
        )
    return RedirectResponse(url=f"/variants/{variant_id}", status_code=303)


@router.post("/variants/{variant_id}/firmware-requirements", response_class=HTMLResponse)
def add_firmware_requirement(
    request: Request,
    variant_id: int,
    firmware_type_id: int = Form(...),
    track_backup: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    try:
        variants_service.add_firmware_requirement(
            db, variant=variant, firmware_type_id=firmware_type_id, track_backup=track_backup
        )
    except (variants_service.FirmwareTypeNotFoundError, variants_service.FirmwareRequirementTakenError) as exc:
        error = (
            "Тип прошивки не найден"
            if isinstance(exc, variants_service.FirmwareTypeNotFoundError)
            else "Такой тип прошивки уже отслеживается в этом исполнении"
        )
        variant = _get_variant_or_404(db, variant_id)
        return templates.TemplateResponse(
            request,
            "variant_detail.html",
            _variant_detail_context(db, variant, user, error=error),
            status_code=400 if isinstance(exc, variants_service.FirmwareTypeNotFoundError) else 409,
        )
    return RedirectResponse(url=f"/variants/{variant_id}", status_code=303)


@router.post("/variants/{variant_id}/mac-requirements", response_class=HTMLResponse)
def add_mac_requirement(
    request: Request,
    variant_id: int,
    label: str = Form(...),
    required: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    try:
        variants_service.add_mac_requirement(db, variant=variant, label=label, required=required)
    except variants_service.MacLabelTakenError:
        variant = _get_variant_or_404(db, variant_id)
        return templates.TemplateResponse(
            request,
            "variant_detail.html",
            _variant_detail_context(db, variant, user, error="Такая метка MAC уже есть в этом исполнении"),
            status_code=409,
        )
    return RedirectResponse(url=f"/variants/{variant_id}", status_code=303)


@router.post("/variants/{variant_id}/delete", response_class=HTMLResponse)
def delete_variant(
    request: Request,
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    platform = variant.platform
    try:
        variants_service.delete_variant(db, variant)
    except variants_service.VariantInUseError:
        variant = _get_variant_or_404(db, variant_id)
        return templates.TemplateResponse(
            request,
            "variant_detail.html",
            _variant_detail_context(
                db,
                variant,
                user,
                error="Нельзя удалить исполнение — есть изделия или используемые где-то ещё элементы каталога",
            ),
            status_code=409,
        )
    return RedirectResponse(url=f"/platforms/{platform.id}", status_code=303)
