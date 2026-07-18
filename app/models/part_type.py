from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PartType(Base):
    """
    Catalog of part models (not physical instances — see PartUnit for that).

    For off-the-shelf parts (CPU, RAM, NIC...) manufacturer + model_name is
    the natural identity, taken straight from the datasheet/order code.

    For in-house-designed boards (midplane, backplane_front, backplane_rear,
    io_board, usb_board, and similar chassis-internal boards) there is
    usually no external "manufacturer model number" — instead they have an
    internal name (model_name) and a PCB/design revision (revision) that
    changes over the product's life and directly affects compatibility
    across chassis builds. `revision` is nullable and free-form (e.g. "A",
    "Rev C", "2.1") since it applies mainly to these custom boards, but is
    available for any category.
    """

    __tablename__ = "part_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)  # chassis|motherboard|midplane|backplane_front|backplane_rear|io_board|usb_board|psu|cpu|ram|riser_card|nic|...
    manufacturer: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(128))
    revision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    specs: Mapped[dict] = mapped_column(JSONB, default=dict)

    part_units: Mapped[list["PartUnit"]] = relationship(back_populates="part_type")
