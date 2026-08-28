"""api tokens

Replaces the single shared API_TOKEN environment variable with one row
per API consumer, each carrying its own role and revocable on its own.
See app/models/api_token.py for the design and app/api_auth.py for how a
request is resolved against it.

Purely additive: one new table, nothing existing is touched. Deployments
that were using API_TOKEN keep working until the variable is removed
from .env, but the variable no longer grants access — a token has to be
issued at /api-tokens or with `python -m app.create_api_token`.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index(
        "ix_api_tokens_name_active",
        "api_tokens",
        ["name"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    # Dropping the table discards every issued token. That is unavoidable
    # for a table this migration created, and it is not a loss of
    # production history the way dropping an append-only log would be:
    # tokens are credentials, and the recovery is to issue new ones after
    # upgrading again. Nothing else in the schema references this table.
    op.drop_index("ix_api_tokens_name_active", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_index("ix_api_tokens_token_hash", table_name="api_tokens")
    op.drop_table("api_tokens")
