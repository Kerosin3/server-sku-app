from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.auth import verify_password
from app.services import login_attempts as login_attempts_service
from app.services import password_recovery as recovery_service
from app.services import setup as setup_service
from app.templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    if setup_service.needs_setup(db):
        return RedirectResponse(url="/setup", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Session = Depends(get_db)):
    if not setup_service.needs_setup(db):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    security_question: str = Form(...),
    security_answer: str = Form(...),
    db: Session = Depends(get_db),
):
    if not setup_service.needs_setup(db):
        return RedirectResponse(url="/login", status_code=303)

    if password != password_confirm:
        return templates.TemplateResponse(
            request, "setup.html", {"error": "Пароли не совпадают"}, status_code=400
        )

    try:
        user = setup_service.create_first_admin(
            db,
            username=username,
            password=password,
            security_question=security_question,
            security_answer=security_answer,
        )
    except setup_service.SetupAlreadyDoneError:
        return RedirectResponse(url="/login", status_code=303)
    except setup_service.MissingSecurityQuestionError:
        return templates.TemplateResponse(
            request, "setup.html", {"error": "Укажите секретный вопрос и ответ на него"}, status_code=400
        )
    except setup_service.WeakPasswordError:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": f"Пароль слишком короткий — минимум {setup_service.MIN_PASSWORD_LENGTH} символов"},
            status_code=400,
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_form(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html", {"error": None})


@router.post("/forgot-password", response_class=HTMLResponse)
def forgot_password_lookup(
    request: Request,
    username: str = Form(...),
    db: Session = Depends(get_db),
):
    user = recovery_service.find_recoverable_user(db, username)
    if user is None:
        # Same message whether the account doesn't exist or just has no
        # security question set — don't reveal which, to avoid leaking
        # which usernames exist.
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "Для этого пользователя восстановление недоступно"},
        )
    return templates.TemplateResponse(
        request, "forgot_password_reset.html", {"username": username, "question": user.security_question, "error": None}
    )


@router.post("/forgot-password/reset", response_class=HTMLResponse)
def forgot_password_reset(
    request: Request,
    username: str = Form(...),
    answer: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    user = recovery_service.find_recoverable_user(db, username)
    if user is None:
        return RedirectResponse(url="/forgot-password", status_code=303)

    if new_password != new_password_confirm:
        return templates.TemplateResponse(
            request,
            "forgot_password_reset.html",
            {"username": username, "question": user.security_question, "error": "Пароли не совпадают"},
            status_code=400,
        )

    try:
        recovery_service.reset_with_answer(
            db, username=username, answer=answer, new_password=new_password
        )
    except recovery_service.LockedOutError:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Слишком много попыток. Попробуйте снова через 15 минут."},
            status_code=429,
        )
    except recovery_service.NoRecoveryConfiguredError:
        return RedirectResponse(url="/forgot-password", status_code=303)
    except recovery_service.WrongAnswerError:
        return templates.TemplateResponse(
            request,
            "forgot_password_reset.html",
            {"username": username, "question": user.security_question, "error": "Неверный ответ"},
            status_code=401,
        )
    except recovery_service.WeakPasswordError:
        return templates.TemplateResponse(
            request,
            "forgot_password_reset.html",
            {
                "username": username,
                "question": user.security_question,
                "error": "Пароль слишком короткий — минимум 8 символов",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        request, "login.html", {"error": None, "info": "Пароль обновлён, войдите с новым паролем"}
    )


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
