from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformComponent(Base):
    """
    Links a platform_item to a physical component with an installation
    time range. removed_at IS NULL  -> the component is currently
    installed. removed_at IS NOT NULL -> historical record (removed/
    replaced/RMA'd).

    This is the single source of truth for which component was ever
    installed in which platform_item. Never add direct FK columns like
    platform_items.motherboard_id — that breaks replacement history.

    platform_variant_slot_id (optional) links this installation to the
    reference slot from the variant's "constructor" (see
    platform_variant.py). This enables a completeness check: compare
    active (removed_at IS NULL) platform_components per
    platform_variant_slot_id against that slot's quantity/required.
    """

    __tablename__ = "platform_components"
    __table_args__ = (
        Index("ix_platform_components_active", "part_unit_id", "removed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_item_id: Mapped[int] = mapped_column(ForeignKey("platform_items.id"), index=True)
    part_unit_id: Mapped[int] = mapped_column(ForeignKey("part_units.id"), index=True)
    platform_variant_slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_variant_slots.id"), nullable=True, index=True
    )
    slot_position: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "DIMM_A1", "CPU0", "RISER1_SLOT2"
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    platform_item: Mapped["PlatformItem"] = relationship(back_populates="components")
    part_unit: Mapped["PartUnit"] = relationship(back_populates="installations")
    platform_variant_slot: Mapped["PlatformVariantSlot | None"] = relationship()
