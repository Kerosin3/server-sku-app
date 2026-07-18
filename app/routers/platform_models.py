from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.i18n import PART_CATEGORIES
from app.models import PartType, PlatformModel, User
from app.services import platform_models as platform_models_service
from app.templating import templates

router = APIRouter(prefix="/platform-models", tags=["platform_models"])


def _get_model(db: Session, model_id: int) -> PlatformModel:
    model = platform_models_service.get_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Platform model not found")
    return model


@router.get("", response_class=HTMLResponse)
def list_models(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    models = platform_models_service.list_models(db)
    return templates.TemplateResponse(request, "platform_models_list.html", {"models": models, "user": user})


@router.get("/new", response_class=HTMLResponse)
def new_model_form(
    request: Request,
    user: User = Depends(require_role("engineer")),
):
    return templates.TemplateResponse(request, "platform_model_form.html", {"user": user, "error": None})


@router.post("", response_class=HTMLResponse)
def create_model(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    try:
        model = platform_models_service.create_model(db, name=name, description=description)
    except platform_models_service.ModelNameTakenError:
        return templates.TemplateResponse(
            request,
            "platform_model_form.html",
            {"user": user, "error": "Модель с таким названием уже существует"},
            status_code=409,
        )
    return RedirectResponse(url=f"/platform-models/{model.id}", status_code=303)


@router.get("/{model_id}", response_class=HTMLResponse)
def model_detail(
    request: Request,
    model_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    model = _get_model(db, model_id)
    part_types = db.scalars(select(PartType).order_by(PartType.category, PartType.model_name)).all()
    return templates.TemplateResponse(
        request,
        "platform_model_detail.html",
        {
            "user": user,
            "model": model,
            "part_types": part_types,
            "categories": PART_CATEGORIES,
            "error": None,
        },
    )


@router.post("/{model_id}/slots", response_class=HTMLResponse)
def add_slot(
    request: Request,
    model_id: int,
    slot_name: str = Form(...),
    category: str = Form(...),
    part_type_id: str = Form(""),
    quantity: int = Form(1),
    required: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    model = _get_model(db, model_id)
    try:
        platform_models_service.add_slot(
            db,
            model=model,
            slot_name=slot_name,
            category=category,
            part_type_id=int(part_type_id) if part_type_id else None,
            quantity=quantity,
            required=required,
        )
    except platform_models_service.SlotNameTakenError:
        part_types = db.scalars(select(PartType).order_by(PartType.category, PartType.model_name)).all()
        return templates.TemplateResponse(
            request,
            "platform_model_detail.html",
            {
                "user": user,
                "model": model,
                "part_types": part_types,
                "categories": PART_CATEGORIES,
                "error": "Слот с таким именем уже есть в этой модели",
            },
            status_code=409,
        )
    except platform_models_service.InvalidCategoryError:
        part_types = db.scalars(select(PartType).order_by(PartType.category, PartType.model_name)).all()
        return templates.TemplateResponse(
            request,
            "platform_model_detail.html",
            {
                "user": user,
                "model": model,
                "part_types": part_types,
                "categories": PART_CATEGORIES,
                "error": "Недопустимая категория",
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/platform-models/{model_id}", status_code=303)
