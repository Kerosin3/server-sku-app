"""widen audit_log.entity_type

audit_log.entity_type carries the singular of the table the row is
about ("platform_item", "part_unit", ...). String(32) fit every value
that existed when the log was introduced, but auditing the BOM added
"platform_variant_firmware_requirement", which is 37 characters and
fails the insert outright.

Shortening the name instead would have been cheaper and was rejected:
the log is read months later, by someone reconstructing what happened,
and "variant_firmware_req" is a name that matches no table in the
system. Widening the column keeps entity_type mechanically resolvable
back to the schema.

In PostgreSQL, widening a varchar is a catalog-only change — no table
rewrite, no lock worth worrying about, regardless of how large
audit_log has grown.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_log",
        "entity_type",
        existing_type=sa.String(32),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing fails outright if any row already holds a longer value,
    # so truncate first. This loses the tail of entity_type on rows
    # written after the upgrade — unavoidable when going back to a column
    # that cannot hold them — but touches nothing that existed before it,
    # since every value back then was 32 characters or fewer.
    op.execute("UPDATE audit_log SET entity_type = left(entity_type, 32)")
    op.alter_column(
        "audit_log",
        "entity_type",
        existing_type=sa.String(64),
        type_=sa.String(32),
        existing_nullable=False,
    )
