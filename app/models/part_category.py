from sqlalchemy import String, Boolean, ForeignKey
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

    platform_variant_id NULL = global (the seeded starter set, visible
    to every variant's constructor). Set = scoped to that one variant
    only — categories added inline from a variant's constructor page
    ("+ Добавить свою категорию") get scoped there, so a one-off
    category doesn't clutter every other variant's dropdown. Uniqueness
    of `name` is enforced by two partial DB indexes (see migration), not
    a plain unique column — NULL doesn't equal NULL in a normal unique
    index, so a plain unique(platform_variant_id, name) would silently
    allow duplicate global names.
    """

    __tablename__ = "part_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    group: Mapped[str] = mapped_column(String(16))  # "custom" | "purchased"
    platform_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_variants.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    platform_variant: Mapped["PlatformVariant | None"] = relationship()
