from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.i18n import PART_CATEGORIES
from app.models import PartType, Platform, PlatformVariant, User
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
    part_types = db.scalars(select(PartType).order_by(PartType.category, PartType.model_name)).all()
    return templates.TemplateResponse(
        request,
        "variant_detail.html",
        {
            "user": user,
            "variant": variant,
            "part_types": part_types,
            "categories": PART_CATEGORIES,
            "error": None,
        },
    )


@router.post("/variants/{variant_id}/slots", response_class=HTMLResponse)
def add_slot(
    request: Request,
    variant_id: int,
    slot_name: str = Form(...),
    category: str = Form(...),
    part_type_id: str = Form(""),
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
            category=category,
            part_type_id=int(part_type_id) if part_type_id else None,
            quantity=quantity,
            required=required,
        )
    except (variants_service.SlotNameTakenError, variants_service.InvalidCategoryError) as exc:
        error = (
            "Слот с таким именем уже есть в этом исполнении"
            if isinstance(exc, variants_service.SlotNameTakenError)
            else "Недопустимая категория"
        )
        part_types = db.scalars(select(PartType).order_by(PartType.category, PartType.model_name)).all()
        return templates.TemplateResponse(
            request,
            "variant_detail.html",
            {
                "user": user,
                "variant": variant,
                "part_types": part_types,
                "categories": PART_CATEGORIES,
                "error": error,
            },
            status_code=409 if isinstance(exc, variants_service.SlotNameTakenError) else 400,
        )
    return RedirectResponse(url=f"/variants/{variant_id}", status_code=303)
