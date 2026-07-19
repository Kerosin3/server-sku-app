from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.auth import verify_password
from app.services import login_attempts as login_attempts_service
from app.templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if login_attempts_service.is_locked_out(db, username):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Слишком много неудачных попыток входа. Попробуйте снова через 15 минут."},
            status_code=429,
        )

    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        login_attempts_service.record_failed_attempt(db, username)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )
    login_attempts_service.clear_attempts(db, username)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
