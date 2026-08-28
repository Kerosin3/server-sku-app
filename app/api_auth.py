"""
Authentication for the JSON API (app/routers/api_v1.py). Separate from
app/auth.py, which is cookie-session auth for the web interface —
machines can't run a login form, and a browser session can't be handed
to a script.

A request presents a bearer token, which is looked up in the api_tokens
table (app/models/api_token.py). Two things come out of that row:

- **rights** — the token's own role, capped by the role of the user it
  acts as, so demoting or deactivating that user constrains every token
  issued to them without anyone having to hunt down token rows;
- **identity** — a real User, so audit_log rows carry a user_id and "who
  installed this component" stays answerable after an agent did it.

Issuing and revoking happen at /api-tokens (admin only) or with
`python -m app.create_api_token`. With no live tokens the API is closed,
so a deployment that doesn't want one is safe by default rather than by
configuration.

Everything funnels through require_api_role(), so this file is the only
one that knows how a caller is identified — routers never see a token.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import ROLES_ORDER
from app.db import get_db
from app.models import ApiToken, User
from app.services import api_tokens as tokens_service


class ApiError(HTTPException):
    """
    HTTPException carrying the API's structured error shape. The handler
    in app/main.py renders these as JSON (see schemas.api.ErrorResponse)
    rather than as the HTML error page the web interface gets.
    """

    def __init__(self, status_code: int, code: str, message: str, hint: str | None = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class ApiPrincipal:
    """
    Who is making this API call, as far as the routers are concerned.

    `role` is the effective one and may be lower than `user.role` — the
    routers must branch on this field and never on `user.role`, or a
    read-only token belonging to an engineer would see everything that
    engineer can.
    """

    token: ApiToken
    user: User
    role: str


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _no_live_tokens(db: Session) -> bool:
    count = db.scalar(
        select(func.count()).select_from(ApiToken).where(ApiToken.revoked_at.is_(None))
    )
    return not count


def _rejected(db: Session) -> ApiError:
    """
    Distinguishes "this deployment has no API" from "your token is wrong".
    Only reached once a request has already failed, so the extra count
    query never touches the successful path.
    """
    if _no_live_tokens(db):
        return ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "api_disabled",
            "The JSON API is disabled: no tokens have been issued on this deployment.",
            "Issue one at /api-tokens, or run: python -m app.create_api_token",
        )
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "unauthenticated",
        "Missing or invalid API token.",
        "Send the token as an 'Authorization: Bearer <token>' header.",
    )


def _authenticate(request: Request, db: Session) -> ApiPrincipal:
    raw_token = _bearer_token(request)
    if raw_token is None:
        raise _rejected(db)

    token = tokens_service.authenticate(db, raw_token)
    if token is None:
        raise _rejected(db)

    if not token.user.is_active:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "service_account_disabled",
            f"The user this token acts as ('{token.user.username}') is deactivated.",
            "Reactivate that user at /users, or issue a token for a different one.",
        )

    return ApiPrincipal(
        token=token,
        user=token.user,
        role=tokens_service.effective_role(token),
    )


def require_api_role(min_role: str):
    """
    Usage: Depends(require_api_role("engineer"))

    Same role ladder as the web interface (app/auth.ROLES_ORDER): a
    viewer token can read but not write, and commercial fields are
    omitted from its responses (see app/routers/api_v1.py).
    """

    def dependency(request: Request, db: Session = Depends(get_db)) -> ApiPrincipal:
        principal = _authenticate(request, db)
        if ROLES_ORDER.index(principal.role) < ROLES_ORDER.index(min_role):
            capped = principal.role != principal.token.role
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "insufficient_role",
                f"This endpoint requires the '{min_role}' role; this token has '{principal.role}'.",
                (
                    f"The token is set to '{principal.token.role}' but the user it acts as "
                    f"('{principal.user.username}') is only '{principal.user.role}', which caps it. "
                    "Raise that user's role at /users."
                    if capped
                    else "Issue a token with a higher role at /api-tokens, or use a read-only endpoint."
                ),
            )
        return principal

    return dependency
