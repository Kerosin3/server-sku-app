"""
Business logic for the "constructor" — platform_models / platform_model_slots.
No audit_log entries here: AGENTS.md requires auditing for part_units,
platforms, platform_components (and users) because those track physical
inventory and access; the model catalog itself is reference data, not
inventory state.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.i18n import PART_CATEGORIES
from app.models import PlatformModel, PlatformModelSlot


class ModelNameTakenError(Exception):
    pass


class SlotNameTakenError(Exception):
    pass


class InvalidCategoryError(Exception):
    pass


def list_models(db: Session) -> list[PlatformModel]:
    return list(
        db.scalars(
            select(PlatformModel).options(selectinload(PlatformModel.slots)).order_by(PlatformModel.name)
        ).all()
    )


def get_model(db: Session, model_id: int) -> PlatformModel | None:
    return db.scalar(
        select(PlatformModel)
        .options(selectinload(PlatformModel.slots).selectinload(PlatformModelSlot.part_type))
        .where(PlatformModel.id == model_id)
    )


def create_model(db: Session, *, name: str, description: str | None) -> PlatformModel:
    if db.scalar(select(PlatformModel).where(PlatformModel.name == name)) is not None:
        raise ModelNameTakenError(name)

    model = PlatformModel(name=name, description=description or None)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def add_slot(
    db: Session,
    *,
    model: PlatformModel,
    slot_name: str,
    category: str,
    part_type_id: int | None,
    quantity: int,
    required: bool,
) -> PlatformModelSlot:
    if category not in PART_CATEGORIES:
        raise InvalidCategoryError(category)
    if db.scalar(
        select(PlatformModelSlot).where(
            PlatformModelSlot.platform_model_id == model.id, PlatformModelSlot.slot_name == slot_name
        )
    ) is not None:
        raise SlotNameTakenError(slot_name)

    slot = PlatformModelSlot(
        platform_model_id=model.id,
        slot_name=slot_name,
        category=category,
        part_type_id=part_type_id,
        quantity=quantity,
        required=required,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot
