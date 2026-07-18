from sqlalchemy import Boolean, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformVariantMacRequirement(Base):
    """
    As-planned MAC address requirement for a variant, e.g. "BMC" MAC is
    required, a second "LAN" MAC is optional. The constructor equivalent
    of PlatformVariantSlot, but for network interfaces instead of
    physical parts — actual assignment lives in MacAddress, matched to a
    requirement by `label` (see app/services/mac_addresses.py).
    """

    __tablename__ = "platform_variant_mac_requirements"
    __table_args__ = (
        UniqueConstraint("platform_variant_id", "label", name="uq_platform_variant_mac_requirement"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_variant_id: Mapped[int] = mapped_column(ForeignKey("platform_variants.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    platform_variant: Mapped["PlatformVariant"] = relationship(back_populates="mac_requirements")
