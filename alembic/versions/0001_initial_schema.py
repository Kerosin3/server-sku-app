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

    # --- platform hierarchy: platforms (product family) -> platform_variants
    # (a BOM/configuration) -> platform_items (a physical, asset-tagged unit).
    # Created early because part_categories/firmware_types below scope
    # themselves to a platform_variant. ---

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

    # part_categories is user-editable catalog data (see AGENTS.md
    # "Категории деталей"), not a Python-hardcoded enum like other
    # status/type codes — engineers add new categories through the UI
    # (/part-categories, or inline from a variant's constructor page) as
    # new part shapes show up, no code change or deploy needed. group is
    # "custom" (proprietary board, part of the item's own design) or
    # "purchased" (off-the-shelf component).
    #
    # platform_variant_id: NULL = global (visible to every variant's
    # constructor — the seeded starter set below). Set = scoped to that
    # one variant only, so a hyper-specific category one engineer adds
    # for their chassis doesn't clutter every other variant's dropdown.
    # Uniqueness of `name` is enforced by the two partial indexes below
    # rather than a plain unique column, since NULL != NULL in a normal
    # unique index — a plain unique(platform_variant_id, name) would let
    # two different global categories share a name by accident.
    op.create_table(
        "part_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("group", sa.String(16), nullable=False),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_part_categories_platform_variant_id", "part_categories", ["platform_variant_id"])
    op.create_index(
        "ix_part_categories_name_global", "part_categories", ["name"],
        unique=True, postgresql_where=sa.text("platform_variant_id IS NULL"),
    )
    op.create_index(
        "ix_part_categories_name_scoped", "part_categories", ["platform_variant_id", "name"],
        unique=True, postgresql_where=sa.text("platform_variant_id IS NOT NULL"),
    )

    # Same user-editable-catalog / global-vs-variant-scoped pattern as
    # part_categories, for firmware types (BIOS, BMC, CPLD, ...) instead
    # of physical part categories.
    op.create_table(
        "firmware_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_firmware_types_platform_variant_id", "firmware_types", ["platform_variant_id"])
    op.create_index(
        "ix_firmware_types_name_global", "firmware_types", ["name"],
        unique=True, postgresql_where=sa.text("platform_variant_id IS NULL"),
    )
    op.create_index(
        "ix_firmware_types_name_scoped", "firmware_types", ["platform_variant_id", "name"],
        unique=True, postgresql_where=sa.text("platform_variant_id IS NOT NULL"),
    )

    op.create_table(
        "part_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("part_categories.id"), nullable=False),
        sa.Column("manufacturer", sa.String(128), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("revision", sa.String(32), nullable=True),
        sa.Column("specs", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_part_types_category_id", "part_types", ["category_id"])

    op.create_table(
        "part_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_type_id", sa.Integer(), sa.ForeignKey("part_types.id"), nullable=False),
        sa.Column("serial_number", sa.String(128), nullable=True),
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
        sa.Column("firmware_type_id", sa.Integer(), sa.ForeignKey("firmware_types.id"), nullable=False),
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
        ["part_unit_id", "firmware_type_id", "image_slot", "recorded_at"],
    )

    op.create_table(
        "platform_variant_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=False),
        sa.Column("slot_name", sa.String(64), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("part_categories.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("platform_variant_id", "slot_name", name="uq_platform_variant_slot_name"),
    )
    op.create_index(
        "ix_platform_variant_slots_platform_variant_id", "platform_variant_slots", ["platform_variant_id"]
    )

    # As-planned firmware requirement for a variant: "this variant's
    # motherboard needs BIOS" etc. track_backup marks a dual-image
    # firmware type (BIOS/BMC) where a backup/secondary image is also
    # expected to be tracked — the backup is never itself required for
    # completeness (see app/services/firmware_records.py), only primary
    # is. Single-image firmware (CPLD, backplane) leaves track_backup
    # false.
    op.create_table(
        "platform_variant_firmware_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=False),
        sa.Column("firmware_type_id", sa.Integer(), sa.ForeignKey("firmware_types.id"), nullable=False),
        sa.Column("track_backup", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint(
            "platform_variant_id", "firmware_type_id", name="uq_platform_variant_firmware_requirement"
        ),
    )
    op.create_index(
        "ix_platform_variant_firmware_requirements_variant_id",
        "platform_variant_firmware_requirements", ["platform_variant_id"],
    )

    # As-planned MAC requirement for a variant: a labeled MAC address
    # slot ("BMC" required, "LAN" optional, ...) — actual assignment
    # lives in mac_addresses, matched to a requirement by label.
    op.create_table(
        "platform_variant_mac_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("platform_variants.id"), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("platform_variant_id", "label", name="uq_platform_variant_mac_requirement"),
    )
    op.create_index(
        "ix_platform_variant_mac_requirements_variant_id",
        "platform_variant_mac_requirements", ["platform_variant_id"],
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

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_login_attempts_username_created_at", "login_attempts", ["username", "created_at"]
    )

    # Starter set of part categories — fully editable/extensible via the
    # /part-categories UI afterward, this is just a reasonable default so
    # the constructor isn't empty on first use. All global (NULL
    # platform_variant_id).
    part_categories_table = sa.table(
        "part_categories",
        sa.column("name", sa.String),
        sa.column("group", sa.String),
    )
    op.bulk_insert(
        part_categories_table,
        [
            {"name": "PCIe карта", "group": "purchased"},
            {"name": "OCP карта", "group": "purchased"},
            {"name": "DDR", "group": "purchased"},
            {"name": "CPU", "group": "purchased"},
            {"name": "PSU", "group": "purchased"},
            {"name": "SSD M.2", "group": "purchased"},
            {"name": "Диск LFF", "group": "purchased"},
            {"name": "Диск SFF", "group": "purchased"},
            {"name": "Райзер-карта", "group": "purchased"},
            {"name": "Материнская плата", "group": "custom"},
            {"name": "Шасси", "group": "custom"},
            {"name": "Мидплейн", "group": "custom"},
            {"name": "Бэкплейн (передний)", "group": "custom"},
            {"name": "Бэкплейн (задний)", "group": "custom"},
            {"name": "IO-плата", "group": "custom"},
            {"name": "USB-плата", "group": "custom"},
        ],
    )

    # Starter set of global firmware types, same rationale.
    firmware_types_table = sa.table(
        "firmware_types",
        sa.column("name", sa.String),
    )
    op.bulk_insert(
        firmware_types_table,
        [
            {"name": "BIOS"},
            {"name": "BMC"},
            {"name": "CPLD"},
            {"name": "Прошивка бэкплейна"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_username_created_at", table_name="login_attempts")
    op.drop_table("login_attempts")
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
    op.drop_index("ix_platform_variant_mac_requirements_variant_id", table_name="platform_variant_mac_requirements")
    op.drop_table("platform_variant_mac_requirements")
    op.drop_index(
        "ix_platform_variant_firmware_requirements_variant_id",
        table_name="platform_variant_firmware_requirements",
    )
    op.drop_table("platform_variant_firmware_requirements")
    op.drop_index("ix_platform_variant_slots_platform_variant_id", table_name="platform_variant_slots")
    op.drop_table("platform_variant_slots")
    op.drop_index("ix_firmware_records_current_lookup", table_name="firmware_records")
    op.drop_index("ix_firmware_records_part_unit_id", table_name="firmware_records")
    op.drop_table("firmware_records")
    op.drop_index("ix_part_units_serial_number", table_name="part_units")
    op.drop_index("ix_part_units_part_type_id", table_name="part_units")
    op.drop_table("part_units")
    op.drop_index("ix_part_types_category_id", table_name="part_types")
    op.drop_table("part_types")
    op.drop_index("ix_firmware_types_name_scoped", table_name="firmware_types")
    op.drop_index("ix_firmware_types_name_global", table_name="firmware_types")
    op.drop_index("ix_firmware_types_platform_variant_id", table_name="firmware_types")
    op.drop_table("firmware_types")
    op.drop_index("ix_part_categories_name_scoped", table_name="part_categories")
    op.drop_index("ix_part_categories_name_global", table_name="part_categories")
    op.drop_index("ix_part_categories_platform_variant_id", table_name="part_categories")
    op.drop_table("part_categories")
    op.drop_index("ix_platform_variants_platform_id", table_name="platform_variants")
    op.drop_table("platform_variants")
    op.drop_index("ix_platforms_name", table_name="platforms")
    op.drop_table("platforms")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
