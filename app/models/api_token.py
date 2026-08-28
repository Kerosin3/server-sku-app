from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.user import User


class ApiToken(Base):
    """
    Bearer tokens for the JSON API (app/routers/api_v1.py), one row per
    consumer. Replaces the single shared API_TOKEN that used to live in
    .env, where retiring one agent meant cutting off every other one and
    rotation meant editing a file and restarting the app.

    Why SHA-256 and not argon2, which every password in this project
    uses: the token is 256 bits straight from secrets.token_urlsafe, so
    there is no dictionary to run against it and nothing for a slow hash
    to protect. Argon2 would instead spend ~100 ms of CPU on every single
    API request. Human-chosen passwords are low-entropy and need the
    slowdown; generated tokens are not and do not.

    The token text is never stored. It is shown once, when created, and
    cannot be recovered afterwards — a lost token is replaced, not looked
    up. token_prefix keeps its first characters in the clear purely so a
    human can tell rows apart in the list at /api-tokens.

    Two roles are in play. The token carries its own `role`, and it is
    attached to a `user` who supplies the identity that audit_log
    records. The role that actually applies is the lower of the two (see
    app/api_auth.py), so demoting or deactivating the user immediately
    constrains every token issued to them — a token can never be a way to
    hold rights its owner has lost.

    Revocation is soft (revoked_at), never DELETE: "which token did this,
    and when did we cut it off" has to stay answerable afterwards. The
    same reasoning as users being deactivated rather than deleted —
    AGENTS.md "Устойчивость к изменениям".
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    token_prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # admin | engineer | viewer
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Two foreign keys to the same table, so the join condition has to be
    # spelled out — SQLAlchemy cannot guess which one each relationship means.
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])

    __table_args__ = (
        Index("ix_api_tokens_token_hash", "token_hash", unique=True),
        Index("ix_api_tokens_user_id", "user_id"),
        # Names are unique among *live* tokens only. Revoking "LangChain
        # agent" and issuing a fresh token under the same name is the
        # normal way to rotate one, and a plain unique index would block it.
        Index(
            "ix_api_tokens_name_active",
            "name",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
