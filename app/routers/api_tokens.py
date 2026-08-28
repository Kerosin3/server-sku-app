from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import ROLES_ORDER, require_role
from app.db import get_db
from app.i18n import USER_ROLES
from app.models import ApiToken, User
from app.services import api_tokens as tokens_service
from app.services import users as users_service
from app.templating import templates

router = APIRouter(prefix="/api-tokens", tags=["api-tokens"])


def _page(db: Session, user: User, *, error: str | None = None, new_token: str | None = None):
    """
    Every response on this page is the full list. new_token is the one
    moment the plaintext exists outside the caller's hands — rendered
    once, right after creation, and never recoverable afterwards.
    """
    return {
        "user": user,
        "tokens": tokens_service.list_tokens(db),
        "users": [u for u in users_service.list_users(db) if u.is_active],
        "roles": ROLES_ORDER,
        "error": error,
        "new_token": new_token,
    }


def _get_token(db: Session, token_id: int) -> ApiToken:
    token = db.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return token


@router.get("", response_class=HTMLResponse)
def list_tokens(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    return templates.TemplateResponse(request, "api_tokens_list.html", _page(db, user))


@router.post("", response_class=HTMLResponse)
def create_token(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    target = db.query(User).filter_by(username=username).first()
    if target is None:
        return templates.TemplateResponse(
            request,
            "api_tokens_list.html",
            _page(db, user, error="Пользователь не найден"),
            status_code=404,
        )

    try:
        _, raw_token = tokens_service.create_token(
            db, actor=user, name=name, user=target, role=role
        )
    except tokens_service.NameRequiredError:
        return templates.TemplateResponse(
            request,
            "api_tokens_list.html",
            _page(db, user, error="Укажите название токена"),
            status_code=400,
        )
    except tokens_service.InvalidRoleError:
        return templates.TemplateResponse(
            request,
            "api_tokens_list.html",
            _page(db, user, error="Недопустимая роль"),
            status_code=400,
        )
    except tokens_service.InactiveUserError:
        return templates.TemplateResponse(
            request,
            "api_tokens_list.html",
            _page(db, user, error=f"Пользователь «{username}» деактивирован"),
            status_code=409,
        )
    except tokens_service.RoleExceedsUserError:
        return templates.TemplateResponse(
            request,
            "api_tokens_list.html",
            _page(
                db,
                user,
                error=(
                    f"Токену нельзя дать роль выше, чем у пользователя: у «{username}» "
                    f"роль «{USER_ROLES.get(target.role, target.role)}»"
                ),
            ),
            status_code=400,
        )
    except tokens_service.NameTakenError:
        return templates.TemplateResponse(
            request,
            "api_tokens_list.html",
            _page(db, user, error=f"Действующий токен с названием «{name}» уже есть — отзовите его"),
            status_code=409,
        )

    # Not a redirect: the plaintext token has to reach the browser, and
    # putting it in a URL would leave it in history and access logs.
    return templates.TemplateResponse(
        request, "api_tokens_list.html", _page(db, user, new_token=raw_token)
    )


@router.post("/{token_id}/revoke", response_class=HTMLResponse)
def revoke_token(
    token_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    tokens_service.revoke_token(db, actor=user, token=_get_token(db, token_id))
    return RedirectResponse(url="/api-tokens", status_code=303)
