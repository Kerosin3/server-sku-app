from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Attachment(Base):
    """
    A file attached either to a platform_variant (test-run archives,
    datasheets, assembly instructions — reference docs for the whole
    BOM) or to one specific platform_item (a photo, a signed test
    report, an RMA form — specific to that physical unit). Reference/
    documentation data, not inventory, so no audit_log entry (same
    reasoning as platform_variants themselves).

    Exactly one of platform_variant_id / platform_item_id must be set —
    an "exclusive arc" enforced by a DB-level CHECK constraint, same
    pattern as MacAddress (see app/models/mac_address.py) rather than a
    polymorphic association without real foreign keys.

    The file itself lives on disk under settings.upload_dir, named
    stored_filename (a uuid4, not the original name — avoids path
    traversal and collisions between two uploads sharing a filename).
    original_filename is what the user uploaded and sees/downloads as.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(platform_variant_id, platform_item_id) = 1",
            name="ck_attachment_exactly_one_owner",
        ),
        # A unique *index*, not unique=True on the column (which would be
        # a unique constraint) — that's what migration 0001 creates, and
        # the model must match the real schema for `alembic check`.
        Index("ix_attachments_stored_filename", "stored_filename", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_variants.id"), nullable=True, index=True
    )
    platform_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_items.id"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    platform_variant: Mapped["PlatformVariant | None"] = relationship(back_populates="files")
    platform_item: Mapped["PlatformItem | None"] = relationship(back_populates="files")
    uploaded_by: Mapped["User | None"] = relationship()
