from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FirmwareType(Base):
    """
    User-editable catalog of firmware types (e.g. "BIOS", "BMC"), same
    pattern as PartCategory (see app/models/part_category.py) — global
    (platform_variant_id NULL, the seeded starter set: BIOS/BMC/CPLD/
    backplane firmware) or scoped to one variant for anything more
    specific an engineer adds. Deliberately not a Python-hardcoded enum,
    unlike other status/type codes in this project (see app/i18n.py) —
    new firmware-carrying boards show up faster than code deploys.
    """

    __tablename__ = "firmware_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    platform_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_variants.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    platform_variant: Mapped["PlatformVariant | None"] = relationship()
