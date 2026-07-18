"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "part_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("manufacturer", sa.String(128), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("revision", sa.String(32), nullable=True),
        sa.Column("specs", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_part_types_category", "part_types", ["category"])

    op.create_table(
        "part_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_type_id", sa.Integer(), sa.ForeignKey("part_types.id"), nullable=False),
        sa.Column("serial_number", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_stock"),
        sa.Column("manufacture_date", sa.Date(), nullable=True),
        sa.Column("received_date", sa.Date(), nullable=True),
        sa.Column("supplier", sa.String(128), nullable=True),
        sa.Column("supplier_lot", sa.String(128), nullable=True),
        sa.Column("notes", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_part_units_part_type_id", "part_units", ["part_type_id"])
    op.create_index("ix_part_units_serial_number", "part_units", ["serial_number"], unique=True)

    op.create_table(
        "firmware_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_unit_id", sa.Integer(), sa.ForeignKey("part_units.id"), nullable=False),
        sa.Column("firmware_type", sa.String(32), nullable=False),
        sa.Column("image_slot", sa.String(16), nullable=False, server_default="primary"),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.String(512), nullable=True),
    )
    op.create_index("ix_firmware_records_part_unit_id", "firmware_records", ["part_unit_id"])
    op.create_index(
        "ix_firmware_records_current_lookup",
        "firmware_records",
        ["part_unit_id", "firmware_type", "image_slot", "recorded_at"],
    )

    # --- platform hierarchy: platforms (product family) -> platform_variants
    # (a BOM/configuration) -> platform_items (a physical, asset-tagged unit) ---

    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_platforms_name", "platforms", ["name"], unique=True)

    op.create_table(
        "platform_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platforms.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("platform_id", "name", name="uq_platform_variant_name"),
    )
    op.create_index("ix_platform_variants_platform_id", "platform_variants", ["platform_id"])

    op.create_table(
        "platform_variant_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=False),
        sa.Column("slot_name", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("part_type_id", sa.Integer(), sa.ForeignKey("part_types.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("platform_variant_id", "slot_name", name="uq_platform_variant_slot_name"),
    )
    op.create_index(
        "ix_platform_variant_slots_platform_variant_id", "platform_variant_slots", ["platform_variant_id"]
    )

    op.create_table(
        "platform_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_tag", sa.String(64), nullable=False),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="assembly"),
        sa.Column("customer", sa.String(128), nullable=True),
        sa.Column("location", sa.String(128), nullable=True),
        sa.Column("notes", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_platform_items_asset_tag", "platform_items", ["asset_tag"], unique=True)
    op.create_index("ix_platform_items_platform_variant_id", "platform_items", ["platform_variant_id"])

    op.create_table(
        "platform_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_item_id", sa.Integer(), sa.ForeignKey("platform_items.id"), nullable=False),
        sa.Column("part_unit_id", sa.Integer(), sa.ForeignKey("part_units.id"), nullable=False),
        sa.Column(
            "platform_variant_slot_id", sa.Integer(), sa.ForeignKey("platform_variant_slots.id"), nullable=True
        ),
        sa.Column("slot_position", sa.String(64), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_platform_components_platform_item_id", "platform_components", ["platform_item_id"])
    op.create_index("ix_platform_components_part_unit_id", "platform_components", ["part_unit_id"])
    op.create_index(
        "ix_platform_components_platform_variant_slot_id", "platform_components", ["platform_variant_slot_id"]
    )
    op.create_index(
        "ix_platform_components_active", "platform_components", ["part_unit_id", "removed_at"]
    )

    op.create_table(
        "platform_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_item_id", sa.Integer(), sa.ForeignKey("platform_items.id"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_platform_events_platform_item_id", "platform_events", ["platform_item_id"])
    op.create_index("ix_platform_events_event_type", "platform_events", ["event_type"])

    op.create_table(
        "mac_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mac_address", sa.String(17), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("platform_item_id", sa.Integer(), sa.ForeignKey("platform_items.id"), nullable=True),
        sa.Column("part_unit_id", sa.Integer(), sa.ForeignKey("part_units.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "num_nonnulls(platform_item_id, part_unit_id) = 1",
            name="ck_mac_address_exactly_one_owner",
        ),
    )
    op.create_index("ix_mac_addresses_mac_address", "mac_addresses", ["mac_address"], unique=True)
    op.create_index("ix_mac_addresses_platform_item_id", "mac_addresses", ["platform_item_id"])
    op.create_index("ix_mac_addresses_part_unit_id", "mac_addresses", ["part_unit_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("diff", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_index("ix_mac_addresses_part_unit_id", table_name="mac_addresses")
    op.drop_index("ix_mac_addresses_platform_item_id", table_name="mac_addresses")
    op.drop_index("ix_mac_addresses_mac_address", table_name="mac_addresses")
    op.drop_table("mac_addresses")
    op.drop_index("ix_platform_events_event_type", table_name="platform_events")
    op.drop_index("ix_platform_events_platform_item_id", table_name="platform_events")
    op.drop_table("platform_events")
    op.drop_index("ix_platform_components_active", table_name="platform_components")
    op.drop_index("ix_platform_components_platform_variant_slot_id", table_name="platform_components")
    op.drop_index("ix_platform_components_part_unit_id", table_name="platform_components")
    op.drop_index("ix_platform_components_platform_item_id", table_name="platform_components")
    op.drop_table("platform_components")
    op.drop_index("ix_platform_items_platform_variant_id", table_name="platform_items")
    op.drop_index("ix_platform_items_asset_tag", table_name="platform_items")
    op.drop_table("platform_items")
    op.drop_index("ix_platform_variant_slots_platform_variant_id", table_name="platform_variant_slots")
    op.drop_table("platform_variant_slots")
    op.drop_index("ix_platform_variants_platform_id", table_name="platform_variants")
    op.drop_table("platform_variants")
    op.drop_index("ix_platforms_name", table_name="platforms")
    op.drop_table("platforms")
    op.drop_index("ix_part_units_serial_number", table_name="part_units")
    op.drop_index("ix_part_units_part_type_id", table_name="part_units")
    op.drop_index("ix_firmware_records_current_lookup", table_name="firmware_records")
    op.drop_index("ix_firmware_records_part_unit_id", table_name="firmware_records")
    op.drop_table("firmware_records")
    op.drop_table("part_units")
    op.drop_index("ix_part_types_category", table_name="part_types")
    op.drop_table("part_types")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
