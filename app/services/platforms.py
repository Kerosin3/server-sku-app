"""
Business logic for platforms — the top-level product family ("Платформа"),
e.g. "2U Storage".

Creation is audited. It did not use to be, on the reasoning that this is
reference data rather than inventory state — which held while the only
way to create a platform was a logged-in human at /platforms. It stopped
holding when the JSON API opened this up to agents: a platform defines
the shape every item under it is later checked against, so "who added
this and when" is exactly what you want when the check starts failing.

Deletion is audited too, and for a stronger reason: it is the one action
here that destroys rather than adds, so the log is the only place the
platform will still exist afterwards.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Platform, PlatformVariant, User
from app.services import audit


class PlatformNameTakenError(Exception):
    pass


class PlatformInUseError(Exception):
    pass


def list_platforms(db: Session) -> list[Platform]:
    return list(
        db.scalars(
            select(Platform).options(selectinload(Platform.variants)).order_by(Platform.name)
        ).all()
    )


def get_platform(db: Session, platform_id: int) -> Platform | None:
    return db.scalar(
        select(Platform).options(selectinload(Platform.variants)).where(Platform.id == platform_id)
    )


def create_platform(db: Session, *, actor: User, name: str, description: str | None) -> Platform:
    if db.scalar(select(Platform).where(Platform.name == name)) is not None:
        raise PlatformNameTakenError(name)

    platform = Platform(name=name, description=description or None)
    db.add(platform)
    db.flush()  # assign platform.id before writing the audit row

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="platform",
        entity_id=platform.id,
        action="create",
        diff={"name": name},
    )
    db.commit()
    db.refresh(platform)
    return platform


def delete_platform(db: Session, *, actor: User, platform: Platform) -> None:
    """Blocked if the platform still has any variants — delete those first."""
    if db.scalar(select(PlatformVariant.id).where(PlatformVariant.platform_id == platform.id)) is not None:
        raise PlatformInUseError(platform.id)

    # Recorded before the row goes: afterwards there is nothing left to
    # read the name off, and "which platform was this" is the whole value
    # of the entry.
    audit.record(
        db,
        actor_id=actor.id,
        entity_type="platform",
        entity_id=platform.id,
        action="delete",
        diff={"name": platform.name},
    )
    db.delete(platform)
    db.commit()
