"""
User management business logic. Deletion is intentionally NOT a hard
DELETE: users.id is referenced by firmware_records.user_id,
platform_events.user_id and audit_log.user_id (nullable FKs, no
ON DELETE CASCADE) — removing a row would either violate those
foreign keys or silently null out "who did this" on historical
records. "Delete" here means deactivate (is_active=False): the user
can no longer log in, but every past record they authored stays
attached to a real row. See AGENTS.md "Устойчивость к изменениям".
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import ROLES_ORDER, hash_password
from app.models import User
from app.services import audit
from app.services.security_answers import normalize_answer


MIN_PASSWORD_LENGTH = 8


class UsernameTakenError(Exception):
    pass


class InvalidRoleError(Exception):
    pass


class WeakPasswordError(Exception):
    pass


class MissingSecurityQuestionError(Exception):
    pass


class SelfLockoutError(Exception):
    """Actor tried to deactivate or demote their own account."""


class LastAdminError(Exception):
    """Action would leave the system with zero active admins."""


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)).all())


def _check_role(role: str) -> None:
    if role not in ROLES_ORDER:
        raise InvalidRoleError(role)


def _active_admin_count(db: Session, *, exclude_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) or 0


def create_user(db: Session, *, actor: User, username: str, password: str, role: str) -> User:
    _check_role(role)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError()
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise UsernameTakenError(username)

    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()  # assign user.id before writing the audit row

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="user",
        entity_id=user.id,
        action="create",
        diff={"username": username, "role": role},
    )
    db.commit()
    db.refresh(user)
    return user


def update_role(db: Session, *, actor: User, target: User, new_role: str) -> User:
    _check_role(new_role)
    if target.id == actor.id and new_role != actor.role and actor.role == "admin":
        if _active_admin_count(db, exclude_id=target.id) == 0:
            raise LastAdminError()

    old_role = target.role
    target.role = new_role
    audit.record(
        db,
        actor_id=actor.id,
        entity_type="user",
        entity_id=target.id,
        action="update",
        diff={"role": [old_role, new_role]},
    )
    db.commit()
    db.refresh(target)
    return target


def set_active(db: Session, *, actor: User, target: User, is_active: bool) -> User:
    if not is_active:
        if target.id == actor.id:
            raise SelfLockoutError()
        if target.role == "admin" and _active_admin_count(db, exclude_id=target.id) == 0:
            raise LastAdminError()

    old_value = target.is_active
    target.is_active = is_active
    audit.record(
        db,
        actor_id=actor.id,
        entity_type="user",
        entity_id=target.id,
        action="update",
        diff={"is_active": [old_value, is_active]},
    )
    db.commit()
    db.refresh(target)
    return target


def reset_password(db: Session, *, actor: User, target: User, new_password: str) -> None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError()
    target.password_hash = hash_password(new_password)
    audit.record(
        db,
        actor_id=actor.id,
        entity_type="user",
        entity_id=target.id,
        action="update",
        diff={"password_reset": True},
    )
    db.commit()


def set_security_question(db: Session, *, user: User, question: str, answer: str) -> User:
    """Self-service only — enforced by the caller (actor must be the target)."""
    if not question.strip() or not answer.strip():
        raise MissingSecurityQuestionError()

    user.security_question = question.strip()
    user.security_answer_hash = hash_password(normalize_answer(answer))
    audit.record(
        db,
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="update",
        diff={"security_question_set": True},
    )
    db.commit()
    db.refresh(user)
    return user
