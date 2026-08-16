"""
Authentication for the JSON API (app/routers/api_v1.py). Separate from
app/auth.py, which is cookie-session auth for the web interface —
machines can't run a login form, and a browser session can't be handed
to a script.

INTERIM MECHANISM. A single shared bearer token from the environment
(`API_TOKEN`), which the user deferred deciding on. Its limits are worth
being explicit about: one token for every consumer, so an individual
consumer can't be revoked without cutting off all of them, and rotation
means editing .env and restarting. The intended replacement is an
`api_tokens` table (hashed token, per-consumer row, revoke from /users),
which is a schema change and therefore migration 0002.

What is *not* interim is the seam. Everything below funnels through
require_api_role(), so swapping the mechanism means rewriting
_authenticate() and nothing else — no router changes.

The token authenticates; a real User row provides identity. The API acts
as the user named by `API_SERVICE_USERNAME` (created like any other user
at /users), which means:

- audit_log rows carry a real user_id, so "who installed this component"
  stays answerable after an agent did it;
- that user's role decides what the API may do — the same RBAC ladder as
  the web, no second permission model to keep in sync;
- deactivating that user in the UI switches the API off immediately,
  without touching .env or restarting.

The API is disabled entirely while API_TOKEN is empty, so a deployment
that doesn't want one is safe by default rather than by configuration.
"""
import secrets

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import ROLES_ORDER
from app.config import settings
from app.db import get_db
from app.models import User


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


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _authenticate(request: Request, db: Session) -> User:
    if not settings.api_token:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "api_disabled",
            "The JSON API is disabled on this deployment.",
            "Set API_TOKEN in .env and restart to enable it.",
        )

    token = _bearer_token(request)
    # compare_digest, not ==, so a wrong token can't be recovered one
    # character at a time from response timing.
    if token is None or not secrets.compare_digest(token, settings.api_token):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "unauthenticated",
            "Missing or invalid API token.",
            "Send the token as an 'Authorization: Bearer <token>' header.",
        )

    user = db.scalar(select(User).where(User.username == settings.api_service_username))
    if user is None:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "service_account_missing",
            f"The API service account '{settings.api_service_username}' does not exist.",
            "Create a user with that name at /users and give it the role the API should have.",
        )
    if not user.is_active:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "service_account_disabled",
            f"The API service account '{settings.api_service_username}' is deactivated.",
            "Reactivate it at /users to re-enable API access.",
        )
    return user


def require_api_role(min_role: str):
    """
    Usage: Depends(require_api_role("engineer"))

    Same role ladder as the web interface (app/auth.ROLES_ORDER): a
    viewer-role service account can read but not write, and commercial
    fields are omitted from its responses (see app/routers/api_v1.py).
    """

    def dependency(request: Request, db: Session = Depends(get_db)) -> User:
        user = _authenticate(request, db)
        if ROLES_ORDER.index(user.role) < ROLES_ORDER.index(min_role):
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "insufficient_role",
                f"This endpoint requires the '{min_role}' role; the API service account has '{user.role}'.",
                f"Raise the role of '{settings.api_service_username}' at /users, or use a read-only endpoint.",
            )
        return user

    return dependency
