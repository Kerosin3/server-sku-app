"""
Business logic for part_categories — user-editable catalog of part
shapes, grouped "custom" (proprietary boards) vs "purchased"
(off-the-shelf components).

Creation is audited, for the same reason as platforms and variants: a
category is what a BOM slot points at, so it shapes what may be
installed. Now that the JSON API lets an agent add one, the log has to
carry an author. Deletion is audited too — it is the only action here
that destroys rather than adds.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartCategory, PartType, PlatformVariantSlot, User
from app.services import audit

GROUPS = ("custom", "purchased")


class CategoryNameTakenError(Exception):
    pass


class InvalidGroupError(Exception):
    pass


class CategoryInUseError(Exception):
    pass


def list_categories(db: Session) -> list[PartCategory]:
    """Every category regardless of scope — the /part-categories overview."""
    return list(db.scalars(select(PartCategory).order_by(PartCategory.group, PartCategory.name)).all())


def list_available_for_variant(db: Session, platform_variant_id: int) -> list[PartCategory]:
    """Global categories plus whatever this specific variant added — for a constructor dropdown."""
    return list(
        db.scalars(
            select(PartCategory)
            .where(
                (PartCategory.platform_variant_id.is_(None))
                | (PartCategory.platform_variant_id == platform_variant_id)
            )
            .order_by(PartCategory.group, PartCategory.name)
        ).all()
    )


def create_category(
    db: Session, *, actor: User, name: str, group: str, platform_variant_id: int | None = None
) -> PartCategory:
    if group not in GROUPS:
        raise InvalidGroupError(group)

    scope_filter = (
        PartCategory.platform_variant_id.is_(None)
        if platform_variant_id is None
        else PartCategory.platform_variant_id == platform_variant_id
    )
    if db.scalar(select(PartCategory).where(PartCategory.name == name, scope_filter)) is not None:
        raise CategoryNameTakenError(name)

    category = PartCategory(name=name, group=group, platform_variant_id=platform_variant_id)
    db.add(category)
    db.flush()

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="part_category",
        entity_id=category.id,
        action="create",
        diff={"name": name, "group": group, "platform_variant_id": platform_variant_id},
    )
    db.commit()
    db.refresh(category)
    return category


def delete_category(db: Session, *, actor: User, category: PartCategory) -> None:
    in_use = db.scalar(select(PartType.id).where(PartType.category_id == category.id)) is not None or (
        db.scalar(select(PlatformVariantSlot.id).where(PlatformVariantSlot.category_id == category.id))
        is not None
    )
    if in_use:
        raise CategoryInUseError(category.id)

    audit.record(
        db,
        actor_id=actor.id,
        entity_type="part_category",
        entity_id=category.id,
        action="delete",
        diff={"name": category.name, "group": category.group},
    )
    db.delete(category)
    db.commit()
