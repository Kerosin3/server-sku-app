from sqlalchemy import Boolean, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformVariantFirmwareRequirement(Base):
    """
    As-planned firmware requirement for a variant, e.g. "this variant's
    motherboard needs BIOS tracked" — the constructor equivalent of
    PlatformVariantSlot, but for firmware instead of physical parts.

    track_backup marks a dual-image firmware type (BIOS/BMC) where a
    backup/secondary image is also expected to be tracked. The primary
    image is always implicitly required by the mere existence of this
    row; the backup is never itself required for completeness (see
    app/services/firmware_records.py) — only shown/trackable when
    track_backup is set. Single-image firmware (CPLD, backplane) leaves
    track_backup false.
    """

    __tablename__ = "platform_variant_firmware_requirements"
    __table_args__ = (
        UniqueConstraint(
            "platform_variant_id", "firmware_type_id", name="uq_platform_variant_firmware_requirement"
        ),
        # Spelled out rather than index=True on the column: the index
        # created by migration 0001 is named ..._variant_id, which is not
        # what index=True would generate (..._platform_variant_id), and
        # the model has to match the real schema for `alembic check`.
        Index("ix_platform_variant_firmware_requirements_variant_id", "platform_variant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_variant_id: Mapped[int] = mapped_column(ForeignKey("platform_variants.id"))
    firmware_type_id: Mapped[int] = mapped_column(ForeignKey("firmware_types.id"))
    track_backup: Mapped[bool] = mapped_column(Boolean, default=False)

    platform_variant: Mapped["PlatformVariant"] = relationship(back_populates="firmware_requirements")
    firmware_type: Mapped["FirmwareType"] = relationship()
