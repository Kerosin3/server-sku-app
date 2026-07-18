from sqlalchemy import String, Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformVariant(Base):
    """
    A specific BOM/configuration of a Platform, e.g. "24-bay all-flash" vs
    "12-bay hybrid" under the "2U Storage" platform. This is the
    "constructor" — the as-planned reference configuration: which slots a
    platform_item of this variant must have, and what fills them (see
    PlatformVariantSlot below).

    The actual (as-built) configuration of a specific assembled unit lives
    in platform_components, hung off PlatformItem. Splitting as-planned /
    as-built is what makes it possible to check completeness in one query
    without re-entering the structure by hand for every assembled unit.
    """

    __tablename__ = "platform_variants"
    __table_args__ = (UniqueConstraint("platform_id", "name", name="uq_platform_variant_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    platform: Mapped["Platform"] = relationship(back_populates="variants")
    slots: Mapped[list["PlatformVariantSlot"]] = relationship(
        back_populates="platform_variant", order_by="PlatformVariantSlot.slot_name"
    )
    items: Mapped[list["PlatformItem"]] = relationship(back_populates="platform_variant")
    firmware_requirements: Mapped[list["PlatformVariantFirmwareRequirement"]] = relationship(
        back_populates="platform_variant"
    )
    mac_requirements: Mapped[list["PlatformVariantMacRequirement"]] = relationship(
        back_populates="platform_variant", order_by="PlatformVariantMacRequirement.label"
    )


class PlatformVariantSlot(Base):
    """
    One line of a variant's BOM: either one specific slot (MIDPLANE,
    BACKPLANE_FRONT, BACKPLANE_REAR, IO_BOARD, USB_BOARD, CHASSIS,
    MOTHERBOARD, ...) or the name of a pool of identical slots (PSU, CPU,
    DIMM, RISER_CARD, DISK) — in the pool case, quantity is how many
    instances of that category are expected.

    part_type_id is set only when the slot is hard-pinned to one specific
    part model (typical for midplane/backplane — they're usually not
    interchangeable across chassis revisions). If any part of the right
    category will do (e.g. any manufacturer's DIMM) — leave part_type_id
    empty and rely on category_id alone.
    """

    __tablename__ = "platform_variant_slots"
    __table_args__ = (
        UniqueConstraint("platform_variant_id", "slot_name", name="uq_platform_variant_slot_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_variant_id: Mapped[int] = mapped_column(ForeignKey("platform_variants.id"), index=True)
    slot_name: Mapped[str] = mapped_column(String(64))
    category_id: Mapped[int] = mapped_column(ForeignKey("part_categories.id"))  # matches part_types.category_id
    part_type_id: Mapped[int | None] = mapped_column(ForeignKey("part_types.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    platform_variant: Mapped["PlatformVariant"] = relationship(back_populates="slots")
    category: Mapped["PartCategory"] = relationship()
    part_type: Mapped["PartType | None"] = relationship()
