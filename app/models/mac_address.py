from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class MacAddress(Base):
    """
    A MAC address belonging either to a platform_item (e.g. a
    chassis-level BMC/management port) or to a specific part_unit
    (typically a motherboard with several network interfaces:
    LAN1/LAN2/BMC, or a standalone NIC card in a riser).

    Exactly one of platform_item_id / part_unit_id must be set — this is
    an "exclusive arc", enforced by a DB-level CHECK constraint
    (num_nonnulls), not a soft convention in application code. A
    polymorphic association without real foreign keys is deliberately
    avoided here — it breaks integrity (the ORM/application could forget
    to check it).

    A separate many-to-one table (rather than mac_1/mac_2 columns on
    part_units) because the number of interfaces isn't fixed: 2 today, but
    a 3rd port tomorrow shouldn't require a schema migration.
    """

    __tablename__ = "mac_addresses"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(platform_item_id, part_unit_id) = 1",
            name="ck_mac_address_exactly_one_owner",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Normalized format AA:BB:CC:DD:EE:FF (uppercase, colon-separated) —
    # normalize in the service layer before writing, don't trust raw input.
    mac_address: Mapped[str] = mapped_column(String(17), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "LAN1", "LAN2", "BMC", ...
    platform_item_id: Mapped[int | None] = mapped_column(ForeignKey("platform_items.id"), nullable=True, index=True)
    part_unit_id: Mapped[int | None] = mapped_column(ForeignKey("part_units.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    platform_item: Mapped["PlatformItem | None"] = relationship(back_populates="mac_addresses")
    part_unit: Mapped["PartUnit | None"] = relationship(back_populates="mac_addresses")
