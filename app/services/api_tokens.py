"""
Issuing, listing and revoking API tokens (app/models/api_token.py).

The plaintext token exists in exactly one place in this module's public
surface: the return value of create_token(). It is never stored, never
logged and never rendered a second time — everything downstream works
from the SHA-256 hash. That is what makes "the token cannot be recovered,
only replaced" true rather than merely intended.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import ROLES_ORDER
from app.models import ApiToken, User
from app.services import audit

# Marks the string as one of ours: recognisable in a log or a config
# file, and greppable if one is ever pasted somewhere it should not be.
TOKEN_PREFIX = "stk_"
# Enough characters to tell rows apart in the list, far too few to guess
# the rest from (the token carries 256 bits; this shows ~40 of them).
DISPLAY_PREFIX_LENGTH = 12
# last_used_at exists to spot tokens nobody uses any more, so minute
# resolution is plenty — and writing a row on every single API request
# would turn every read into a write.
LAST_USED_THROTTLE = timedelta(seconds=60)


class InvalidRoleError(Exception):
    pass


class NameRequiredError(Exception):
    pass


class NameTakenError(Exception):
    """Another live token already carries this name."""


class InactiveUserError(Exception):
    """Tokens cannot be issued to a deactivated user."""


class RoleExceedsUserError(Exception):
    """The requested role is above the role of the user the token acts as."""


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def list_tokens(db: Session) -> list[ApiToken]:
    """Live tokens first, then revoked ones — newest first within each group."""
    stmt = (
        select(ApiToken)
        .options(selectinload(ApiToken.user), selectinload(ApiToken.created_by))
        .order_by(ApiToken.revoked_at.is_(None).desc(), ApiToken.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def create_token(
    db: Session,
    *,
    actor: User | None,
    name: str,
    user: User,
    role: str,
) -> tuple[ApiToken, str]:
    """
    Returns the row and the plaintext token. The caller must show the
    plaintext to a human once and then drop it — there is no second
    chance to read it.

    `actor` is None when issued from the command line, where there is no
    logged-in user to attribute it to.
    """
    name = name.strip()
    if not name:
        raise NameRequiredError()
    if role not in ROLES_ORDER:
        raise InvalidRoleError(role)
    if not user.is_active:
        raise InactiveUserError(user.username)
    # A token must never be a way to hold rights its owner does not have.
    # app/api_auth.py enforces the same bound again at request time, which
    # covers the user being demoted after the token was issued; this check
    # is here so the mistake is caught at the point it is made, with a
    # message saying what is wrong.
    if ROLES_ORDER.index(role) > ROLES_ORDER.index(user.role):
        raise RoleExceedsUserError(role)

    live_with_name = db.scalar(
        select(ApiToken).where(ApiToken.name == name, ApiToken.revoked_at.is_(None))
    )
    if live_with_name is not None:
        raise NameTakenError(name)

    raw_token = generate_token()
    token = ApiToken(
        name=name,
        token_prefix=raw_token[:DISPLAY_PREFIX_LENGTH],
        token_hash=hash_token(raw_token),
        role=role,
        user_id=user.id,
        created_by_id=actor.id if actor else None,
    )
    db.add(token)
    db.flush()  # assign token.id before writing the audit row

    audit.record(
        db,
        actor_id=actor.id if actor else None,
        entity_type="api_token",
        entity_id=token.id,
        action="create",
        # The hash is as good as the token for authenticating, so neither
        # it nor the plaintext goes anywhere near the audit log.
        diff={"name": name, "role": role, "acts_as": user.username},
    )
    db.commit()
    db.refresh(token)
    return token, raw_token


def revoke_token(db: Session, *, actor: User | None, token: ApiToken) -> ApiToken:
    """Idempotent: revoking an already-revoked token keeps the first timestamp."""
    if token.revoked_at is not None:
        return token

    token.revoked_at = func.now()
    audit.record(
        db,
        actor_id=actor.id if actor else None,
        entity_type="api_token",
        entity_id=token.id,
        action="update",
        diff={"revoked": True, "name": token.name},
    )
    db.commit()
    db.refresh(token)
    return token


def authenticate(db: Session, raw_token: str) -> ApiToken | None:
    """
    Resolve a presented token to its row, or None if it does not match a
    live one. Lookup is by hash on a unique index, so a wrong token costs
    one indexed miss and leaks nothing through timing.
    """
    token = db.scalar(
        select(ApiToken)
        .options(selectinload(ApiToken.user))
        .where(ApiToken.token_hash == hash_token(raw_token), ApiToken.revoked_at.is_(None))
    )
    if token is None:
        return None
    _touch(db, token)
    return token


def _touch(db: Session, token: ApiToken) -> None:
    now = datetime.now(timezone.utc)
    if token.last_used_at is not None and now - token.last_used_at < LAST_USED_THROTTLE:
        return
    token.last_used_at = func.now()
    db.commit()


def effective_role(token: ApiToken) -> str:
    """
    The lower of the token's role and its user's — so demoting the user
    demotes every token issued to them, without having to find and edit
    the token rows.
    """
    return min(token.role, token.user.role, key=ROLES_ORDER.index)
