from sqlalchemy import String, Boolean, ForeignKey, Index, text
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

    Name uniqueness uses the same two partial indexes as PartCategory
    (global names unique among themselves, scoped names unique within
    their variant) — see that model for why a plain unique constraint
    doesn't work here, and why the indexes are declared on the model and
    not only in the migration.
    """

    __tablename__ = "firmware_types"
    __table_args__ = (
        Index(
            "ix_firmware_types_name_global",
            "name",
            unique=True,
            postgresql_where=text("platform_variant_id IS NULL"),
        ),
        Index(
            "ix_firmware_types_name_scoped",
            "platform_variant_id",
            "name",
            unique=True,
            postgresql_where=text("platform_variant_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    platform_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_variants.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    platform_variant: Mapped["PlatformVariant | None"] = relationship()
