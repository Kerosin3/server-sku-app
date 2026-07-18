"""
Business logic for platforms — the top-level product family ("Платформа"),
e.g. "2U Storage". No audit_log entries here, same reasoning as
platform_variants: this is reference/catalog data, not inventory state.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Platform


class PlatformNameTakenError(Exception):
    pass


def list_platforms(db: Session) -> list[Platform]:
    return list(db.scalars(select(Platform).order_by(Platform.name)).all())


def get_platform(db: Session, platform_id: int) -> Platform | None:
    return db.scalar(
        select(Platform).options(selectinload(Platform.variants)).where(Platform.id == platform_id)
    )


def create_platform(db: Session, *, name: str, description: str | None) -> Platform:
    if db.scalar(select(Platform).where(Platform.name == name)) is not None:
        raise PlatformNameTakenError(name)

    platform = Platform(name=name, description=description or None)
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform
