from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FirmwareRecord(Base):
    """
    Append-only firmware version history for a part_unit (motherboard,
    backplane, or any other board that carries firmware).

    Same pattern as PlatformEvent: a timestamped log, not a handful of
    fixed columns (bios_version, bmc_version, cpld_version...) on
    part_units. Reasons:
    1. a new firmware_type (or a board type that didn't carry firmware
       before) must not require a schema migration;
    2. full history matters as much as the current value — for RMA/failure
       investigation you need to know what version was on the board at
       any point in time, not just now.

    firmware_type_id references firmware_types (app/models/firmware_type.py)
    — a user-editable catalog, not a Python-hardcoded enum, so a new
    firmware-carrying board's firmware type doesn't need a code change.

    image_slot handles redundant firmware images that can independently be
    at different versions — BIOS and BMC are typically dual-image
    (primary/backup, aka A/B). Firmware types with only a single image
    (e.g. CPLD, or a backplane's firmware) still use image_slot="primary"
    — keeping the column NOT NULL with a default keeps the "current
    version" lookup uniform, no NULL-handling special case.

    Current version per (part_unit_id, firmware_type_id, image_slot) is
    the latest row by recorded_at — query with PostgreSQL's DISTINCT ON:
        SELECT DISTINCT ON (part_unit_id, firmware_type_id, image_slot) *
        FROM firmware_records
        WHERE part_unit_id = :id
        ORDER BY part_unit_id, firmware_type_id, image_slot, recorded_at DESC
    """

    __tablename__ = "firmware_records"
    __table_args__ = (
        Index(
            "ix_firmware_records_current_lookup",
            "part_unit_id", "firmware_type_id", "image_slot", "recorded_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    part_unit_id: Mapped[int] = mapped_column(ForeignKey("part_units.id"), index=True)
    firmware_type_id: Mapped[int] = mapped_column(ForeignKey("firmware_types.id"))
    image_slot: Mapped[str] = mapped_column(String(16), default="primary", server_default="primary")
    version: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    part_unit: Mapped["PartUnit"] = relationship(back_populates="firmware_records")
    firmware_type: Mapped["FirmwareType"] = relationship()
    user: Mapped["User | None"] = relationship()
