from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Platform(Base):
    """
    An assembled server instance. Lifecycle milestone dates (manufactured,
    QC-verified, initial/final test, shipped, ...) are NOT columns here —
    see PlatformEvent for why. `status` is a coarse denormalized "current
    stage" kept in sync by the service layer whenever a milestone event is
    recorded; PlatformEvent.occurred_at is the source of truth for exact
    timestamps and history.
    """

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_tag: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform_model_id: Mapped[int] = mapped_column(ForeignKey("platform_models.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="assembly")  # assembly|testing|shipped|deployed|rma|decommissioned
    customer: Mapped[str | None] = mapped_column(String(128), nullable=True)  # hide for role "viewer" in schemas/
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    components: Mapped[list["PlatformComponent"]] = relationship(back_populates="platform")
    platform_model: Mapped["PlatformModel"] = relationship(back_populates="platforms")
    mac_addresses: Mapped[list["MacAddress"]] = relationship(back_populates="platform")
    events: Mapped[list["PlatformEvent"]] = relationship(
        back_populates="platform", order_by="PlatformEvent.occurred_at"
    )
