from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PartUnit(Base):
    """
    serial_number is unique per part_type (article/partnumber/decimal
    number), not globally — two different articles can legitimately
    reuse the same serial (e.g. each manufacturer's own counter), so
    uniqueness is scoped to (part_type_id, serial_number) rather than a
    single-column constraint.
    """

    __tablename__ = "part_units"
    __table_args__ = (
        UniqueConstraint("part_type_id", "serial_number", name="uq_part_unit_type_serial"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    part_type_id: Mapped[int] = mapped_column(ForeignKey("part_types.id"), index=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="in_stock")  # in_stock|installed|rma|scrapped|retired
    manufacture_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supplier_lot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    part_type: Mapped["PartType"] = relationship(back_populates="part_units")
    installations: Mapped[list["PlatformComponent"]] = relationship(back_populates="part_unit")
    mac_addresses: Mapped[list["MacAddress"]] = relationship(back_populates="part_unit")
    firmware_records: Mapped[list["FirmwareRecord"]] = relationship(back_populates="part_unit")
