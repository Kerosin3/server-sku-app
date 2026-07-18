from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import ROLES_ORDER, require_role
from app.db import get_db
from app.models import User
from app.services import users as users_service
from app.templating import templates

router = APIRouter(prefix="/users", tags=["users"])


def _get_target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return target


@router.get("", response_class=HTMLResponse)
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    all_users = users_service.list_users(db)
    return templates.TemplateResponse(request, "users_list.html", {"users": all_users, "user": user})


@router.get("/new", response_class=HTMLResponse)
def new_user_form(
    request: Request,
    user: User = Depends(require_role("admin")),
):
    return templates.TemplateResponse(
        request, "user_form.html", {"user": user, "roles": ROLES_ORDER, "error": None}
    )


@router.post("", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    try:
        users_service.create_user(db, actor=user, username=username, password=password, role=role)
    except users_service.UsernameTakenError:
        return templates.TemplateResponse(
            request,
            "user_form.html",
            {"user": user, "roles": ROLES_ORDER, "error": "Пользователь с таким логином уже существует"},
            status_code=409,
        )
    except users_service.InvalidRoleError:
        return templates.TemplateResponse(
            request,
            "user_form.html",
            {"user": user, "roles": ROLES_ORDER, "error": "Недопустимая роль"},
            status_code=400,
        )
    return RedirectResponse(url="/users", status_code=303)


@router.get("/{user_id}", response_class=HTMLResponse)
def user_detail(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    target = _get_target(db, user_id)
    return templates.TemplateResponse(
        request,
        "user_detail.html",
        {"user": user, "target": target, "roles": ROLES_ORDER, "error": None},
    )


@router.post("/{user_id}/role", response_class=HTMLResponse)
def change_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    target = _get_target(db, user_id)
    try:
        users_service.update_role(db, actor=user, target=target, new_role=role)
    except users_service.LastAdminError:
        return templates.TemplateResponse(
            request,
            "user_detail.html",
            {
                "user": user,
                "target": target,
                "roles": ROLES_ORDER,
                "error": "Нельзя понизить роль последнего активного администратора",
            },
            status_code=409,
        )
    except users_service.InvalidRoleError:
        return templates.TemplateResponse(
            request,
            "user_detail.html",
            {"user": user, "target": target, "roles": ROLES_ORDER, "error": "Недопустимая роль"},
            status_code=400,
        )
    return RedirectResponse(url=f"/users/{user_id}", status_code=303)


@router.post("/{user_id}/deactivate", response_class=HTMLResponse)
def deactivate_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    target = _get_target(db, user_id)
    try:
        users_service.set_active(db, actor=user, target=target, is_active=False)
    except users_service.SelfLockoutError:
        return templates.TemplateResponse(
            request,
            "user_detail.html",
            {"user": user, "target": target, "roles": ROLES_ORDER, "error": "Нельзя деактивировать самого себя"},
            status_code=409,
        )
    except users_service.LastAdminError:
        return templates.TemplateResponse(
            request,
            "user_detail.html",
            {
                "user": user,
                "target": target,
                "roles": ROLES_ORDER,
                "error": "Нельзя деактивировать последнего активного администратора",
            },
            status_code=409,
        )
    return RedirectResponse(url=f"/users/{user_id}", status_code=303)


@router.post("/{user_id}/activate", response_class=HTMLResponse)
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    target = _get_target(db, user_id)
    users_service.set_active(db, actor=user, target=target, is_active=True)
    return RedirectResponse(url=f"/users/{user_id}", status_code=303)


@router.post("/{user_id}/reset-password", response_class=HTMLResponse)
def reset_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    target = _get_target(db, user_id)
    users_service.reset_password(db, actor=user, target=target, new_password=new_password)
    return RedirectResponse(url=f"/users/{user_id}", status_code=303)
