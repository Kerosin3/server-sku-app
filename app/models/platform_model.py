from sqlalchemy import String, Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformModel(Base):
    """
    A platform model/configuration, e.g. "2U Storage Rev C".
    For a given chassis in a given configuration, the set of slots
    (midplane, backplane front/rear, io board, usb board, psu, etc.)
    does not change — that set is described via PlatformModelSlot below.
    """

    __tablename__ = "platform_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    slots: Mapped[list["PlatformModelSlot"]] = relationship(
        back_populates="platform_model", order_by="PlatformModelSlot.slot_name"
    )
    platforms: Mapped[list["Platform"]] = relationship(back_populates="platform_model")


class PlatformModelSlot(Base):
    """
    The "constructor" — the as-planned reference configuration: which
    slots a platform of this model must have, and what fills them.

    The actual (as-built) configuration of a specific assembled unit lives
    in platform_components. Splitting as-planned / as-built is what makes
    it possible to check completeness in one query ("platform X is missing
    a usb board even though the model requires one") without re-entering
    the structure by hand for every assembled unit.

    slot_name is either one specific slot (MIDPLANE, BACKPLANE_FRONT,
    BACKPLANE_REAR, IO_BOARD, USB_BOARD, CHASSIS, MOTHERBOARD, ...) or the
    name of a pool of identical slots (PSU, CPU, DIMM, RISER_CARD) — in
    the pool case, quantity is how many instances of that category are
    expected.

    part_type_id is set only when the slot is hard-pinned to one specific
    part model (typical for midplane/backplane — they're usually not
    interchangeable across chassis revisions). If any part of the right
    category will do (e.g. any manufacturer's DIMM) — leave part_type_id
    empty and rely on category alone.
    """

    __tablename__ = "platform_model_slots"
    __table_args__ = (
        UniqueConstraint("platform_model_id", "slot_name", name="uq_platform_model_slot_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_model_id: Mapped[int] = mapped_column(ForeignKey("platform_models.id"), index=True)
    slot_name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))  # matches part_types.category
    part_type_id: Mapped[int | None] = mapped_column(ForeignKey("part_types.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    platform_model: Mapped["PlatformModel"] = relationship(back_populates="slots")
    part_type: Mapped["PartType | None"] = relationship()
