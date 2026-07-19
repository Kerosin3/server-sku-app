"""
Self-service "forgot password" recovery via the security question a
user set for themselves (app/services/users.set_security_question,
app/services/setup.create_first_admin). Shares the same login_attempts
rate limiter as /login — a wrong security answer is just another way
to attack the account and should count against the same lockout, and
a lockout from repeated bad login attempts should also block recovery
attempts against that username.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.models import User
from app.services import login_attempts as login_attempts_service
from app.services.security_answers import normalize_answer
from app.services.users import MIN_PASSWORD_LENGTH, WeakPasswordError


class LockedOutError(Exception):
    pass


class NoRecoveryConfiguredError(Exception):
    """No such active user, or they never set a security question."""


class WrongAnswerError(Exception):
    pass


def find_recoverable_user(db: Session, username: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not user.security_question:
        return None
    return user


def reset_with_answer(db: Session, *, username: str, answer: str, new_password: str) -> None:
    if login_attempts_service.is_locked_out(db, username):
        raise LockedOutError()

    user = find_recoverable_user(db, username)
    if user is None:
        # Record the attempt too, so probing usernames without a
        # security question configured doesn't dodge the rate limit.
        login_attempts_service.record_failed_attempt(db, username)
        raise NoRecoveryConfiguredError()

    if not verify_password(normalize_answer(answer), user.security_answer_hash):
        login_attempts_service.record_failed_attempt(db, username)
        raise WrongAnswerError()

    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError()

    user.password_hash = hash_password(new_password)
    login_attempts_service.clear_attempts(db, username)
    db.commit()
