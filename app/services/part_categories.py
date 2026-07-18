"""
Business logic for part_categories — user-editable catalog of part
shapes, grouped "custom" (proprietary boards) vs "purchased"
(off-the-shelf components). No audit_log entries here, same reasoning as
platforms/platform_variants: reference/catalog data, not inventory state.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartCategory

GROUPS = ("custom", "purchased")


class CategoryNameTakenError(Exception):
    pass


class InvalidGroupError(Exception):
    pass


def list_categories(db: Session) -> list[PartCategory]:
    return list(db.scalars(select(PartCategory).order_by(PartCategory.group, PartCategory.name)).all())


def create_category(db: Session, *, name: str, group: str) -> PartCategory:
    if group not in GROUPS:
        raise InvalidGroupError(group)
    if db.scalar(select(PartCategory).where(PartCategory.name == name)) is not None:
        raise CategoryNameTakenError(name)

    category = PartCategory(name=name, group=group)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category
