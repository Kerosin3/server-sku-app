"""
Pydantic schemas for the JSON API under /api/v1 (app/routers/api_v1.py).

Two rules shape everything here, both aimed at the consumer being an LLM
agent rather than a browser:

1. Codes are the contract, labels are a convenience. Every enum-ish field
   is emitted twice: `status` carries the stable backend code
   ("assembled"), `status_label` the Russian text ("Укомплектовано") so
   the agent can quote it to a Russian-speaking user without inventing a
   translation of its own. Renaming a label in app/i18n.py must never
   break a consumer, which is exactly what the older
   app/services/export.py got wrong by emitting labels only.

2. Timestamps are ISO-8601 with offset, not the MSK display strings the
   UI uses. Formatting for humans is the UI's job (app/timezone.py); an
   API consumer needs something it can parse and compare.

Field descriptions are in English on purpose: they end up in the
generated OpenAPI schema, which is read by the model, not rendered in
the web interface — so the "UI is Russian, everything else is English"
convention in AGENTS.md puts them on the English side.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.i18n import (
    FIRMWARE_IMAGE_SLOTS,
    PART_CATEGORY_GROUPS,
    PART_UNIT_STATUSES,
    PLATFORM_EVENT_TYPES,
    PLATFORM_STATUSES,
)

# Re-exported so app/routers/api_v1.py has one import site for the label
# dictionaries it needs alongside these schemas.
PART_UNIT_STATUS_LABELS = PART_UNIT_STATUSES
from app.models import (
    FirmwareRecord,
    MacAddress,
    PlatformComponent,
    PlatformEvent,
    PlatformItem,
    PlatformVariant,
)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable error code; branch on this, not on the message.")
    message: str = Field(description="What went wrong, in English.")
    hint: str | None = Field(default=None, description="Concrete next action that would make the call succeed.")


class ErrorResponse(BaseModel):
    error: ErrorDetail


# --------------------------------------------------------------------------
# References — the small shapes that get embedded everywhere
# --------------------------------------------------------------------------


class PlatformRef(BaseModel):
    id: int
    name: str


class VariantRef(BaseModel):
    id: int
    name: str
    platform: PlatformRef


class ItemRef(BaseModel):
    id: int
    asset_tag: str


class PartRef(BaseModel):
    part_unit_id: int
    serial_number: str | None = Field(description="Null for parts registered without one (identified by comment).")
    article: str = Field(description="Part number / decimal number — PartType.model_name.")
    manufacturer: str | None = None
    revision: str | None = None
    category: str = Field(description="Russian category name; a user-editable catalog value, not a fixed code.")
    category_group: str = Field(description='"custom" (in-house board) or "purchased" (off-the-shelf part).')
    category_group_label: str
    comment: str | None = None


# --------------------------------------------------------------------------
# Item pieces
# --------------------------------------------------------------------------


class ComponentOut(BaseModel):
    id: int
    slot_name: str | None = Field(description="Which BOM line of the variant this fills.")
    part: PartRef
    installed_at: datetime
    removed_at: datetime | None = None
    currently_installed: bool


class ChecklistRow(BaseModel):
    slot_id: int
    slot_name: str
    category: str
    required: bool
    quantity: int = Field(description="How many parts this BOM line calls for.")
    installed: int = Field(description="How many are currently installed against it.")
    complete: bool


class EventOut(BaseModel):
    id: int
    event_type: str
    event_type_label: str
    occurred_at: datetime
    recorded_by: str | None = None
    notes: str | None = None


class FirmwareOut(BaseModel):
    firmware_type: str
    image_slot: str
    image_slot_label: str
    version: str
    recorded_at: datetime
    part_serial_number: str | None = None


class FirmwareChecklistRow(BaseModel):
    firmware_type_id: int
    firmware_type: str
    track_backup: bool = Field(description="Whether a redundant backup image is tracked for this type.")
    primary: FirmwareOut | None = None
    backup: FirmwareOut | None = None
    satisfied: bool = Field(description="True once the primary image has a recorded version.")


class MacOut(BaseModel):
    id: int
    mac_address: str
    label: str | None = None
    owner: str = Field(description='"item" (chassis-level, e.g. BMC) or "part_unit" (on a specific board).')
    part_serial_number: str | None = None


class MacChecklistRow(BaseModel):
    label: str
    required: bool
    macs: list[MacOut]
    satisfied: bool


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


class ItemSummary(BaseModel):
    id: int
    asset_tag: str
    status: str
    status_label: str
    variant: VariantRef
    location: str | None = None
    customer: str | None = Field(
        default=None,
        description="Commercial data — omitted entirely for tokens with the viewer role.",
    )
    updated_at: datetime


class ItemDetail(ItemSummary):
    notes: str | None = None
    components_locked: bool = Field(
        description=(
            "True once the item has been marked assembled: installing or removing components is "
            "rejected until a 'disassembled' event reopens it."
        )
    )
    checklist: list[ChecklistRow]
    components_installed: list[ComponentOut]
    components_removed: list[ComponentOut]
    firmware: list[FirmwareChecklistRow]
    mac_addresses: list[MacChecklistRow]
    events: list[EventOut]


class ItemList(BaseModel):
    total: int = Field(description="Total matching items, ignoring limit/offset.")
    items: list[ItemSummary]


# --------------------------------------------------------------------------
# Variants / platforms
# --------------------------------------------------------------------------


class SlotOut(BaseModel):
    id: int
    slot_name: str
    category: str
    quantity: int
    required: bool


class FirmwareRequirementOut(BaseModel):
    firmware_type_id: int
    firmware_type: str
    track_backup: bool


class MacRequirementOut(BaseModel):
    label: str
    required: bool


class VariantDetail(BaseModel):
    id: int
    name: str
    description: str | None = None
    platform: PlatformRef
    slots: list[SlotOut]
    firmware_requirements: list[FirmwareRequirementOut]
    mac_requirements: list[MacRequirementOut]
    item_count: int


class PlatformOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    variants: list[VariantRef]


class PartCategoryOut(BaseModel):
    """A kind of part a BOM slot can call for — the catalog behind slot.category."""

    id: int
    name: str = Field(description="Russian catalog name, editable by users; not a fixed code.")
    group: str = Field(description='"custom" (in-house board) or "purchased" (off-the-shelf part).')
    group_label: str
    platform_variant_id: int | None = Field(
        default=None,
        description="Null for a category available everywhere; otherwise it exists only for that variant.",
    )


class FirmwareTypeOut(BaseModel):
    id: int
    name: str
    platform_variant_id: int | None = Field(
        default=None,
        description="Null for a firmware type available everywhere; otherwise scoped to that variant.",
    )


# --------------------------------------------------------------------------
# Search / part history
# --------------------------------------------------------------------------


class PartHit(BaseModel):
    part: PartRef
    currently_installed_in: ItemRef | None = None
    status: str
    status_label: str


class MacHit(BaseModel):
    mac: MacOut
    owner_item: ItemRef | None = None


class SearchResults(BaseModel):
    query: str
    items: list[ItemSummary]
    parts: list[PartHit]
    mac_addresses: list[MacHit]


class PartInstallation(BaseModel):
    item: ItemRef
    slot_name: str | None = None
    installed_at: datetime
    removed_at: datetime | None = None
    currently_installed: bool


class PartHistory(BaseModel):
    part: PartRef
    status: str
    status_label: str
    installations: list[PartInstallation] = Field(
        description="Every item this part was ever installed in, newest first."
    )
    firmware: list[FirmwareOut]


# --------------------------------------------------------------------------
# Write requests
# --------------------------------------------------------------------------


class DryRunnable(BaseModel):
    """
    Base for every write request, and the place the strictness lives.

    extra="forbid" matters more here than in a browser-facing API.
    Pydantic's default is to drop unknown fields silently, so
    PATCH /items/{id} with {"asset_tag": "..."} — a field that is
    deliberately not editable — would return 200 having changed nothing.
    A person would notice; a model would take the 200 as confirmation and
    carry on reasoning from something that never happened. Rejecting the
    field outright turns a hallucinated or misspelled parameter into a
    422 the caller can see and correct.
    """

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(
        default=False,
        description=(
            "Run every validation the real call would run and report the outcome, but write nothing. "
            "Use this to check an action is valid before committing it."
        ),
    )


class RecordEventRequest(DryRunnable):
    event_type: str = Field(
        description=(
            "One of: assembled, disassembled, test_started, test_passed, test_passed_with_remarks, "
            "test_failed, shipped, service. Process order is enforced — e.g. 'shipped' requires a "
            "prior passing test."
        )
    )
    notes: str | None = Field(
        default=None,
        description="Required for test_passed_with_remarks: describe the remarks.",
    )


class InstallComponentRequest(DryRunnable):
    platform_variant_slot_id: int = Field(description="Which BOM line of the item's variant this fills.")
    serial_number: str | None = Field(
        default=None,
        description="Serial of the physical part. Omit only for parts that genuinely have none.",
    )
    article: str | None = Field(
        default=None,
        description="Part number / decimal number. Required when the serial is not already on record.",
    )
    comment: str | None = Field(
        default=None,
        description="Required when serial_number is omitted — this is what identifies the part instead.",
    )


class RecordFirmwareRequest(DryRunnable):
    part_unit_id: int = Field(description="Must be a component currently installed in this item.")
    firmware_type_id: int = Field(description="Must be declared as a firmware requirement of the item's variant.")
    version: str
    image_slot: str = Field(default="primary", description='"primary" or "backup".')
    notes: str | None = None


class AddMacRequest(DryRunnable):
    mac_address: str = Field(description="Any separator format; normalized to AA:BB:CC:DD:EE:FF on write.")
    label: str | None = Field(
        default=None,
        description="Matched against the variant's MAC requirements by name, e.g. 'BMC' or 'LAN1'.",
    )
    part_unit_id: int | None = Field(
        default=None,
        description="Attach to a specific installed board. Omit for a chassis-level MAC owned by the item.",
    )


class CreateItemRequest(DryRunnable):
    platform_variant_id: int = Field(description="Which configuration this unit is built to; GET /platforms lists them.")
    asset_tag: str = Field(description="Unique identifier of the physical unit. Rejected if already used.")
    customer: str | None = None
    location: str | None = None
    notes: str | None = None


class UpdateItemRequest(DryRunnable):
    """
    Only these three fields are editable. asset_tag and the variant are
    what the unit *is*, and changing either would silently rewrite the
    identity of records already pointing at it.

    Every field is optional; omitting one leaves it alone, passing null
    clears it.
    """

    customer: str | None = None
    location: str | None = None
    notes: str | None = None


class RemoveComponentRequest(DryRunnable):
    """No fields of its own — which component is in the path."""


class CreatePlatformRequest(DryRunnable):
    name: str = Field(description="Product family name, unique across the system.")
    description: str | None = None


class CreateVariantRequest(DryRunnable):
    name: str = Field(description="Configuration name, unique within its platform.")
    description: str | None = None


class AddSlotRequest(DryRunnable):
    slot_name: str = Field(description="What this BOM line is called, e.g. 'CPU 1'. Unique within the variant.")
    part_category_id: int = Field(description="Kind of part this line calls for; GET /part-categories lists them.")
    quantity: int = Field(default=1, ge=1)
    required: bool = Field(default=True, description="False marks the line optional for completeness checks.")


class AddFirmwareRequirementRequest(DryRunnable):
    firmware_type_id: int = Field(description="GET /firmware-types lists them.")
    track_backup: bool = Field(
        default=False,
        description="True if this firmware has a backup image whose version is recorded separately.",
    )


class AddMacRequirementRequest(DryRunnable):
    label: str = Field(description="Name of the expected address, e.g. 'BMC' or 'LAN1'. Unique within the variant.")
    required: bool = True


class CreatePartCategoryRequest(DryRunnable):
    name: str
    group: str = Field(description='"custom" for in-house boards, "purchased" for off-the-shelf parts.')
    platform_variant_id: int | None = Field(
        default=None,
        description="Omit to make the category available everywhere; set it to scope it to one variant.",
    )


class CreateFirmwareTypeRequest(DryRunnable):
    name: str
    platform_variant_id: int | None = Field(
        default=None,
        description="Omit to make the firmware type available everywhere; set it to scope it to one variant.",
    )


class WriteResult(BaseModel):
    """
    One envelope for every write. Exactly one of the object fields is
    filled in, whichever the call affected — the state after the write,
    so a consumer never needs a follow-up GET to see the result.
    """

    ok: bool
    dry_run: bool = Field(description="True when nothing was written.")
    detail: str = Field(description="What happened, or what would have happened on a dry run.")
    item: ItemDetail | None = Field(default=None, description="The item's state after the write.")
    variant: VariantDetail | None = Field(default=None, description="The configuration's state after the write.")
    platform: PlatformOut | None = Field(default=None, description="The platform's state after the write.")
    part_category: PartCategoryOut | None = Field(default=None, description="The category that was created.")
    firmware_type: FirmwareTypeOut | None = Field(default=None, description="The firmware type that was created.")


# --------------------------------------------------------------------------
# Builders — ORM -> schema
# --------------------------------------------------------------------------


def platform_ref(variant: PlatformVariant) -> PlatformRef:
    return PlatformRef(id=variant.platform.id, name=variant.platform.name)


def variant_ref(variant: PlatformVariant) -> VariantRef:
    return VariantRef(id=variant.id, name=variant.name, platform=platform_ref(variant))


def item_ref(item: PlatformItem) -> ItemRef:
    return ItemRef(id=item.id, asset_tag=item.asset_tag)


def part_ref(part_unit) -> PartRef:
    part_type = part_unit.part_type
    group = part_type.category.group
    return PartRef(
        part_unit_id=part_unit.id,
        serial_number=part_unit.serial_number,
        article=part_type.model_name,
        manufacturer=part_type.manufacturer or None,
        revision=part_type.revision,
        category=part_type.category.name,
        category_group=group,
        category_group_label=PART_CATEGORY_GROUPS.get(group, group),
        comment=part_unit.notes,
    )


def component_out(component: PlatformComponent) -> ComponentOut:
    return ComponentOut(
        id=component.id,
        slot_name=component.platform_variant_slot.slot_name if component.platform_variant_slot else None,
        part=part_ref(component.part_unit),
        installed_at=component.installed_at,
        removed_at=component.removed_at,
        currently_installed=component.removed_at is None,
    )


def event_out(event: PlatformEvent) -> EventOut:
    return EventOut(
        id=event.id,
        event_type=event.event_type,
        event_type_label=PLATFORM_EVENT_TYPES.get(event.event_type, event.event_type),
        occurred_at=event.occurred_at,
        recorded_by=event.user.username if event.user else None,
        notes=event.notes,
    )


def firmware_out(record: FirmwareRecord) -> FirmwareOut:
    return FirmwareOut(
        firmware_type=record.firmware_type.name,
        image_slot=record.image_slot,
        image_slot_label=FIRMWARE_IMAGE_SLOTS.get(record.image_slot, record.image_slot),
        version=record.version,
        recorded_at=record.recorded_at,
        part_serial_number=record.part_unit.serial_number,
    )


def mac_out(mac: MacAddress) -> MacOut:
    return MacOut(
        id=mac.id,
        mac_address=mac.mac_address,
        label=mac.label,
        owner="item" if mac.platform_item_id else "part_unit",
        part_serial_number=mac.part_unit.serial_number if mac.part_unit_id else None,
    )


def item_summary(item: PlatformItem, *, include_customer: bool) -> ItemSummary:
    return ItemSummary(
        id=item.id,
        asset_tag=item.asset_tag,
        status=item.status,
        status_label=PLATFORM_STATUSES.get(item.status, item.status),
        variant=variant_ref(item.platform_variant),
        location=item.location,
        customer=item.customer if include_customer else None,
        updated_at=item.updated_at,
    )


def item_detail(
    item: PlatformItem,
    *,
    include_customer: bool,
    checklist: list[dict],
    firmware_rows: list[dict],
    mac_rows: list[dict],
    events: list[PlatformEvent],
    components_locked: bool,
) -> ItemDetail:
    installed = [c for c in item.components if c.removed_at is None]
    removed = sorted(
        (c for c in item.components if c.removed_at is not None), key=lambda c: c.removed_at, reverse=True
    )
    return ItemDetail(
        **item_summary(item, include_customer=include_customer).model_dump(),
        notes=item.notes,
        components_locked=components_locked,
        checklist=[
            ChecklistRow(
                slot_id=row["slot"].id,
                slot_name=row["slot"].slot_name,
                category=row["slot"].category.name,
                required=row["slot"].required,
                quantity=row["slot"].quantity,
                installed=row["installed"],
                complete=row["complete"],
            )
            for row in checklist
        ],
        components_installed=[component_out(c) for c in installed],
        components_removed=[component_out(c) for c in removed],
        firmware=[
            FirmwareChecklistRow(
                firmware_type_id=row["requirement"].firmware_type_id,
                firmware_type=row["requirement"].firmware_type.name,
                track_backup=row["requirement"].track_backup,
                primary=firmware_out(row["primary"]) if row["primary"] else None,
                backup=firmware_out(row["backup"]) if row["backup"] else None,
                satisfied=row["primary"] is not None,
            )
            for row in firmware_rows
        ],
        mac_addresses=[
            MacChecklistRow(
                label=row["requirement"].label,
                required=row["requirement"].required,
                macs=[mac_out(m) for m in row["macs"]],
                satisfied=bool(row["macs"]) or not row["requirement"].required,
            )
            for row in mac_rows
        ],
        events=[event_out(e) for e in events],
    )


def part_category_out(category) -> PartCategoryOut:
    return PartCategoryOut(
        id=category.id,
        name=category.name,
        group=category.group,
        group_label=PART_CATEGORY_GROUPS.get(category.group, category.group),
        platform_variant_id=category.platform_variant_id,
    )


def firmware_type_out(firmware_type) -> FirmwareTypeOut:
    return FirmwareTypeOut(
        id=firmware_type.id,
        name=firmware_type.name,
        platform_variant_id=firmware_type.platform_variant_id,
    )


def platform_out(platform) -> PlatformOut:
    return PlatformOut(
        id=platform.id,
        name=platform.name,
        description=platform.description,
        variants=[
            VariantRef(id=v.id, name=v.name, platform=PlatformRef(id=platform.id, name=platform.name))
            for v in platform.variants
        ],
    )


def variant_detail(variant: PlatformVariant, *, item_count: int) -> VariantDetail:
    """
    item_count is passed in rather than read off the relationship: the
    callers that have it already counted it with a COUNT query, and
    loading every item of a configuration to call len() on them would be
    a needless read of the largest table in the system.
    """
    return VariantDetail(
        id=variant.id,
        name=variant.name,
        description=variant.description,
        platform=PlatformRef(id=variant.platform.id, name=variant.platform.name),
        slots=[
            SlotOut(
                id=s.id,
                slot_name=s.slot_name,
                category=s.category.name,
                quantity=s.quantity,
                required=s.required,
            )
            for s in variant.slots
        ],
        firmware_requirements=[
            FirmwareRequirementOut(
                firmware_type_id=r.firmware_type_id,
                firmware_type=r.firmware_type.name,
                track_backup=r.track_backup,
            )
            for r in variant.firmware_requirements
        ],
        mac_requirements=[MacRequirementOut(label=r.label, required=r.required) for r in variant.mac_requirements],
        item_count=item_count,
    )
