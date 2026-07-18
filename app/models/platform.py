from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Platform(Base):
    """
    A product family/design under development, e.g. "2U Storage". This is
    the top of the three-level hierarchy:

        Platform (this)  ->  PlatformVariant  ->  PlatformItem

    A Platform itself carries no BOM/slot detail — it is purely a grouping
    of PlatformVariant rows. Several variants of one platform can differ
    in bay count, CPU/riser configuration, etc.; the as-planned BOM for
    each variant lives in PlatformVariantSlot (see platform_variant.py).
    """

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    variants: Mapped[list["PlatformVariant"]] = relationship(
        back_populates="platform", order_by="PlatformVariant.name"
    )
