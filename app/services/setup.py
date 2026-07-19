"""
First-run setup: on a brand new install (zero users), the web UI lets
whoever gets there first create the initial admin account directly —
no shell/CLI access to the container needed. This path closes itself
the moment any user exists (see needs_setup), same as the CLI script
app/create_admin.py which remains for scripted/headless provisioning.

A security question is mandatory here specifically because the first
admin has no one else who could reset their password if they forget it
(app/services/password_recovery.py) — every other user created
afterward can have their password reset by an admin instead.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import User
from app.services.demo_seed import seed_demo_data
from app.services.users import MIN_PASSWORD_LENGTH, WeakPasswordError
from app.services.security_answers import normalize_answer


class SetupAlreadyDoneError(Exception):
    pass


class MissingSecurityQuestionError(Exception):
    pass


def needs_setup(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) == 0


def create_first_admin(
    db: Session, *, username: str, password: str, security_question: str, security_answer: str
) -> User:
    if not needs_setup(db):
        raise SetupAlreadyDoneError()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError()
    if not security_question.strip() or not security_answer.strip():
        raise MissingSecurityQuestionError()

    user = User(
        username=username,
        password_hash=hash_password(password),
        role="admin",
        security_question=security_question.strip(),
        security_answer_hash=hash_password(normalize_answer(security_answer)),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    seed_demo_data(db, actor=user)

    return user
