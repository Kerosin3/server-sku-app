from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import User
from app.services import part_categories as categories_service
from app.templating import templates

router = APIRouter(prefix="/part-categories", tags=["part_categories"])


@router.get("", response_class=HTMLResponse)
def list_categories(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer")),
):
    categories = categories_service.list_categories(db)
    return templates.TemplateResponse(
        request, "part_categories_list.html", {"user": user, "categories": categories, "error": None}
    )


@router.post("", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: str = Form(...),
    group: str = Form(...),
    next_url: str = Form("/part-categories", alias="next"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    try:
        categories_service.create_category(db, name=name, group=group)
    except (categories_service.CategoryNameTakenError, categories_service.InvalidGroupError) as exc:
        error = (
            "Категория с таким названием уже существует"
            if isinstance(exc, categories_service.CategoryNameTakenError)
            else "Недопустимая группа"
        )
        categories = categories_service.list_categories(db)
        return templates.TemplateResponse(
            request,
            "part_categories_list.html",
            {"user": user, "categories": categories, "error": error},
            status_code=409 if isinstance(exc, categories_service.CategoryNameTakenError) else 400,
        )
    return RedirectResponse(url=next_url, status_code=303)
