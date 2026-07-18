from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PartCategory(Base):
    """
    User-editable catalog of part categories (e.g. "CPU", "Мидплейн"),
    grouped into "purchased" (off-the-shelf components: PCIe/OCP cards,
    DDR, CPU, PSU, SSD/HDD, riser cards) or "custom" (proprietary boards
    that are part of the item's own design: motherboard, chassis,
    midplane, backplane, ...).

    Deliberately NOT a Python-hardcoded enum like other status/type codes
    in this project (see app/i18n.py) — new physical shapes show up
    during hardware design faster than code deploys, so engineers manage
    this list themselves through /part-categories. `name` is the Russian
    display text directly (like Platform.name), no separate code/label
    indirection needed.
    """

    __tablename__ = "part_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    group: Mapped[str] = mapped_column(String(16))  # "custom" | "purchased"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
