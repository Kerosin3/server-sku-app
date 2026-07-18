from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

ph = PasswordHasher()

ROLES_ORDER = ["viewer", "engineer", "admin"]  # ascending order of privilege


def hash_password(raw: str) -> str:
    return ph.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return ph.verify(hashed, raw)
    except VerifyMismatchError:
        return False


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_role(min_role: str):
    """Usage: Depends(require_role('engineer'))

    TODO(agent): add a custom exception handler in app/main.py that catches
    401/403 HTTPException and renders a Russian-language HTML error page
    (or redirects to /login) instead of returning raw JSON — the web UI
    must stay Russian end-to-end, this dependency layer stays English.
    """

    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLES_ORDER.index(user.role) < ROLES_ORDER.index(min_role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return dependency
