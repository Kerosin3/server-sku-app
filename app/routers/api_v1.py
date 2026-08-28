"""
JSON API for machine consumers — built for an LLM agent driving the
tracker (LangChain and similar), not for a browser.

Design notes, since this differs from the rest of the project on purpose:

- **Task-shaped, not table-shaped.** Endpoints answer the questions an
  operator actually asks ("where is this serial?", "what's missing from
  this item?", "mark the test passed") instead of exposing CRUD over
  nineteen tables. Note the tension: the surface grew from ten calls to
  twenty-seven once creating, editing and deleting the whole hierarchy
  was added, and a tool set an agent chooses correctly between wants to
  stay small. Adding an endpoint is therefore a real cost, not a free
  extension — prefer widening an existing call over inventing a
  neighbour.

- **Same services as the web.** Every mutation goes through
  app/services/, so stage ordering, the component lock after assembly,
  the "firmware only on in-house boards" rule and audit_log all apply
  identically. There is no path through this API that skips a rule the
  web interface enforces.

- **Errors are structured and actionable.** Each service exception maps
  to a stable `code` plus a `hint` naming the call that would fix it, so
  the agent can correct itself instead of retrying blindly. See _ERRORS.

- **`dry_run` on every write.** Runs the real validation and reports the
  outcome without writing (app/db.dry_run_session). This is the main
  guard rail when the caller is a model rather than a person.

Endpoint summaries and field descriptions are English — they are read by
the model through the generated OpenAPI schema, not rendered in the web
UI, so the language convention in AGENTS.md puts them on the code side.
Russian text still reaches the consumer, as `*_label` fields next to
every code (see app/schemas/api.py).
"""
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api_auth import ApiError, ApiPrincipal, require_api_role
from app.db import dry_run_session, get_db
from app.models import (
    FirmwareRecord,
    FirmwareType,
    PartCategory,
    PartType,
    PartUnit,
    PlatformComponent,
    PlatformItem,
    PlatformVariant,
)
from app.schemas import api as schemas
from app.services import firmware_records as firmware_service
from app.services import firmware_types as firmware_types_service
from app.services import mac_addresses as mac_service
from app.services import part_categories as categories_service
from app.services import platform_events as events_service
from app.services import platform_items as items_service
from app.services import platforms as platforms_service
from app.services import platform_variants as variants_service
from app.services import search as search_service

router = APIRouter(prefix="/api/v1", tags=["api"])

MAX_LIMIT = 200


# --------------------------------------------------------------------------
# Error translation
# --------------------------------------------------------------------------

# Service exception -> (HTTP status, code, hint). The message comes from
# the entry too, because a service exception's own text is an internal
# identifier (usually just the offending id), not something a consumer
# can act on.
_ERRORS: dict[type[Exception], tuple[int, str, str, str]] = {
    events_service.InvalidEventTypeError: (
        400, "invalid_event_type",
        "Unknown event_type.",
        "Use one of: assembled, disassembled, test_started, test_passed, "
        "test_passed_with_remarks, test_failed, shipped, service.",
    ),
    events_service.RemarksRequiredError: (
        400, "remarks_required",
        "test_passed_with_remarks requires the remarks to be written down.",
        "Repeat the call with a non-empty 'notes' describing the remarks.",
    ),
    events_service.PrerequisiteNotMetError: (
        409, "prerequisite_not_met",
        "The process order does not allow this stage yet.",
        "Check GET /api/v1/items/{id} -> events to see which stages are already recorded.",
    ),
    items_service.ComponentsLockedError: (
        409, "components_locked",
        "The item is marked assembled, so its component list is locked.",
        "Record a 'disassembled' event via POST /api/v1/items/{id}/events to reopen it.",
    ),
    items_service.SlotNotFoundError: (
        400, "slot_not_found",
        "platform_variant_slot_id does not belong to this item's variant.",
        "Get the valid slot ids from GET /api/v1/variants/{variant_id} -> slots.",
    ),
    items_service.CommentRequiredError: (
        400, "comment_required",
        "A part installed without a serial number needs a comment identifying it.",
        "Repeat the call with either 'serial_number' or a non-empty 'comment'.",
    ),
    items_service.ArticleRequiredError: (
        400, "article_required",
        "This serial number is not on record yet, so the part cannot be registered.",
        "Repeat the call adding 'article' (the part number / decimal number).",
    ),
    items_service.PartUnitAlreadyInstalledError: (
        409, "part_already_installed",
        "That part is currently installed in another item.",
        "Find it with GET /api/v1/search?q=<serial>, then remove it there first.",
    ),
    firmware_service.PartUnitNotInstalledError: (
        400, "part_not_installed",
        "part_unit_id is not a component currently installed in this item.",
        "Use GET /api/v1/items/{id} -> components_installed to get valid part_unit_id values.",
    ),
    firmware_service.PurchasedPartCannotCarryFirmwareError: (
        400, "purchased_part_no_firmware",
        "Firmware is recorded on in-house boards, not on purchased parts.",
        "Pick a component whose part.category_group is 'custom'.",
    ),
    firmware_service.FirmwareTypeNotRequiredError: (
        400, "firmware_type_not_required",
        "This item's variant does not declare that firmware type.",
        "Get the valid firmware_type_id values from GET /api/v1/variants/{variant_id}.",
    ),
    firmware_service.BackupNotTrackedError: (
        400, "backup_not_tracked",
        "This firmware type does not track a backup image.",
        "Repeat the call with image_slot='primary'.",
    ),
    mac_service.InvalidMacFormatError: (
        400, "invalid_mac_format",
        "Not a MAC address — 12 hex digits are required.",
        "Any separator style is accepted, e.g. AA:BB:CC:DD:EE:FF or AABBCCDDEEFF.",
    ),
    mac_service.MacAddressTakenError: (
        409, "mac_taken",
        "That MAC address is already registered elsewhere.",
        "Find its current owner with GET /api/v1/search?q=<mac>.",
    ),
    mac_service.PartUnitNotInstalledError: (
        400, "part_not_installed",
        "part_unit_id is not a component currently installed in this item.",
        "Omit part_unit_id for a chassis-level MAC, or pick an installed component.",
    ),
    # --- creating items and the structure they are built against ---
    items_service.VariantNotFoundError: (
        400, "variant_not_found",
        "No configuration with that platform_variant_id.",
        "List the catalog with GET /api/v1/platforms.",
    ),
    items_service.AssetTagTakenError: (
        409, "asset_tag_taken",
        "Another item already carries that asset tag.",
        "Find it with GET /api/v1/search?q=<asset tag>, or pick a different tag.",
    ),
    items_service.ComponentNotActiveError: (
        400, "component_not_installed",
        "That component is not currently installed in this item.",
        "Use GET /api/v1/items/{id} -> components_installed for the valid component ids.",
    ),
    platforms_service.PlatformNameTakenError: (
        409, "platform_name_taken",
        "A platform with that name already exists.",
        "Names are unique system-wide; check GET /api/v1/platforms first.",
    ),
    variants_service.VariantNameTakenError: (
        409, "variant_name_taken",
        "This platform already has a configuration with that name.",
        "Names are unique within a platform; check GET /api/v1/platforms.",
    ),
    variants_service.SlotNameTakenError: (
        409, "slot_name_taken",
        "This configuration already has a BOM line with that name.",
        "Check the existing lines with GET /api/v1/variants/{id} -> slots.",
    ),
    variants_service.CategoryNotFoundError: (
        400, "part_category_not_found",
        "No part category with that id.",
        "List them with GET /api/v1/part-categories, or create one with POST /api/v1/part-categories.",
    ),
    variants_service.FirmwareTypeNotFoundError: (
        400, "firmware_type_not_found",
        "No firmware type with that id.",
        "List them with GET /api/v1/firmware-types, or create one with POST /api/v1/firmware-types.",
    ),
    variants_service.FirmwareRequirementTakenError: (
        409, "firmware_requirement_exists",
        "This configuration already requires that firmware type.",
        "Check GET /api/v1/variants/{id} -> firmware_requirements.",
    ),
    variants_service.MacLabelTakenError: (
        409, "mac_label_taken",
        "This configuration already expects a MAC address with that label.",
        "Check GET /api/v1/variants/{id} -> mac_requirements.",
    ),
    categories_service.CategoryNameTakenError: (
        409, "part_category_name_taken",
        "A part category with that name already exists in this scope.",
        "Reuse the existing one from GET /api/v1/part-categories, or scope the new one to a variant.",
    ),
    categories_service.InvalidGroupError: (
        400, "invalid_category_group",
        "group must be 'custom' or 'purchased'.",
        "'custom' is for in-house boards, 'purchased' for off-the-shelf parts.",
    ),
    firmware_types_service.FirmwareTypeNameTakenError: (
        409, "firmware_type_name_taken",
        "A firmware type with that name already exists in this scope.",
        "Reuse the existing one from GET /api/v1/firmware-types, or scope the new one to a variant.",
    ),
    # --- deletion, all of it refused while something still depends on it ---
    items_service.ItemShippedError: (
        409, "item_shipped",
        "A shipped item cannot be deleted — that is delivered-product history.",
        "Nothing undoes this through the API. If the record is genuinely wrong, a human has to decide.",
    ),
    platforms_service.PlatformInUseError: (
        409, "platform_in_use",
        "The platform still has configurations under it.",
        "Delete those first: GET /api/v1/platforms shows them, DELETE /api/v1/variants/{id} removes one.",
    ),
    variants_service.VariantInUseError: (
        409, "variant_in_use",
        "The configuration still has items built to it, or catalog entries of its own that are in use.",
        "Delete its items first: GET /api/v1/items?variant_id=<id> lists them.",
    ),
    categories_service.CategoryInUseError: (
        409, "part_category_in_use",
        "The category is still referenced by a BOM line or a registered part.",
        "Remove the BOM lines using it first: GET /api/v1/variants/{id} -> slots.",
    ),
    firmware_types_service.FirmwareTypeInUseError: (
        409, "firmware_type_in_use",
        "The firmware type is still required by a configuration or has recorded versions.",
        "Recorded firmware versions are permanent, so a type that was ever used cannot be removed.",
    ),
}


def _translate(exc: Exception) -> ApiError:
    entry = _ERRORS.get(type(exc))
    if entry is None:
        raise exc
    http_status, code, message, hint = entry
    # PrerequisiteNotMetError knows exactly which stage is missing; that
    # detail is more useful to the caller than the generic message.
    detail = getattr(exc, "message", None)
    return ApiError(http_status, code, detail or message, hint)


def _not_found(what: str, hint: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "not_found", what, hint)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _get_item(db: Session, item_id: int) -> PlatformItem:
    item = items_service.get_item(db, item_id)
    if item is None:
        raise _not_found(
            f"No item with id {item_id}.",
            "List items with GET /api/v1/items, or look one up by asset tag with GET /api/v1/search.",
        )
    return item


def _detail(db: Session, item: PlatformItem, role: str) -> schemas.ItemDetail:
    return schemas.item_detail(
        item,
        include_customer=role != "viewer",
        checklist=items_service.slot_checklist(item),
        firmware_rows=firmware_service.firmware_checklist(db, item),
        mac_rows=mac_service.mac_checklist(db, item),
        events=events_service.list_events(db, item),
        components_locked=item.status not in items_service.EDITABLE_STATUSES,
    )


@contextmanager
def _session_for(db: Session, dry_run: bool) -> Iterator[Session]:
    if not dry_run:
        yield db
        return
    with dry_run_session() as session:
        yield session


def _write(
    db: Session,
    principal: ApiPrincipal,
    item_id: int,
    dry_run: bool,
    action: Callable[[Session, PlatformItem], str],
) -> schemas.WriteResult:
    """
    Shared shape for every mutating endpoint: resolve the item, run the
    service call, translate any domain error, and return the item's
    resulting state so the caller doesn't need a follow-up GET.

    On a dry run all of that happens against a session that is rolled
    back afterwards — the response describes what *would* have happened.
    """
    with _session_for(db, dry_run) as session:
        item = _get_item(session, item_id)
        try:
            detail = action(session, item)
        except Exception as exc:  # narrowed by _translate, which re-raises the unknown
            raise _translate(exc)
        session.expire_all()
        return schemas.WriteResult(
            ok=True,
            dry_run=dry_run,
            detail=f"Would {detail} (dry run, nothing written)." if dry_run else f"Did {detail}.",
            item=_detail(session, _get_item(session, item_id), principal.role),
        )


def _write_object(
    db: Session,
    dry_run: bool,
    action: Callable[[Session], tuple[str, dict]],
) -> schemas.WriteResult:
    """
    The same contract as _write, for writes that are not about a single
    item: the action reports what it did and which object belongs in the
    envelope, and on a dry run all of it runs against a session that is
    rolled back afterwards.
    """
    with _session_for(db, dry_run) as session:
        try:
            detail, payload = action(session)
        except Exception as exc:  # narrowed by _translate, which re-raises the unknown
            raise _translate(exc)
        return schemas.WriteResult(
            ok=True,
            dry_run=dry_run,
            detail=f"Would {detail} (dry run, nothing written)." if dry_run else f"Did {detail}.",
            **payload,
        )


def _variant_payload(session: Session, variant_id: int) -> dict:
    """Re-read through the service so every relationship the schema needs is loaded."""
    variant = variants_service.get_variant(session, variant_id)
    item_count = session.scalar(
        select(func.count()).select_from(PlatformItem).where(PlatformItem.platform_variant_id == variant_id)
    )
    return {"variant": schemas.variant_detail(variant, item_count=item_count or 0)}


def _get_variant(session: Session, variant_id: int) -> PlatformVariant:
    variant = variants_service.get_variant(session, variant_id)
    if variant is None:
        raise _not_found(
            f"No configuration with id {variant_id}.",
            "List the catalog with GET /api/v1/platforms.",
        )
    return variant


# --------------------------------------------------------------------------
# Read endpoints
# --------------------------------------------------------------------------


@router.get("/search", response_model=schemas.SearchResults, summary="Find a part, item or MAC address")
def search(
    q: str = Query(min_length=2, description="Serial number, part number, asset tag or MAC address (partial ok)."),
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    Call this first whenever the user names a physical thing — a serial
    number, a part number, an asset tag, a MAC — and you need to know
    what and where it is. For a part, the response says which item it is
    installed in right now, which is the question this system exists to
    answer.
    """
    results = search_service.search(db, q)
    include_customer = principal.role != "viewer"
    return schemas.SearchResults(
        query=q,
        items=[schemas.item_summary(i, include_customer=include_customer) for i in results["items"]],
        parts=[
            schemas.PartHit(
                part=schemas.part_ref(row["part_unit"]),
                currently_installed_in=schemas.item_ref(row["current_item"]) if row["current_item"] else None,
                status=row["part_unit"].status,
                status_label=schemas.PART_UNIT_STATUS_LABELS.get(row["part_unit"].status, row["part_unit"].status),
            )
            for row in results["parts"]
        ],
        mac_addresses=[
            schemas.MacHit(
                mac=schemas.mac_out(row["mac"]),
                owner_item=schemas.item_ref(row["owner_item"]) if row["owner_item"] else None,
            )
            for row in results["macs"]
        ],
    )


@router.get("/items", response_model=schemas.ItemList, summary="List manufactured items")
def list_items(
    variant_id: int | None = Query(default=None, description="Restrict to one variant (configuration)."),
    item_status: str | None = Query(
        default=None,
        alias="status",
        description="Filter by current stage: assembly, assembled, disassembled, testing, shipped.",
    ),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    Use this for questions about a group of items ("what is still in
    testing?", "how many of this configuration have shipped?"). For one
    specific item you already have an id for, GET /api/v1/items/{id}
    returns much more.
    """
    stmt = select(PlatformItem).options(
        selectinload(PlatformItem.platform_variant).selectinload(PlatformVariant.platform)
    )
    count_stmt = select(func.count()).select_from(PlatformItem)
    if variant_id is not None:
        stmt = stmt.where(PlatformItem.platform_variant_id == variant_id)
        count_stmt = count_stmt.where(PlatformItem.platform_variant_id == variant_id)
    if item_status is not None:
        stmt = stmt.where(PlatformItem.status == item_status)
        count_stmt = count_stmt.where(PlatformItem.status == item_status)

    items = db.scalars(stmt.order_by(PlatformItem.id.desc()).limit(limit).offset(offset)).all()
    return schemas.ItemList(
        total=db.scalar(count_stmt) or 0,
        items=[schemas.item_summary(i, include_customer=principal.role != "viewer") for i in items],
    )


@router.get("/items/{item_id}", response_model=schemas.ItemDetail, summary="Full state of one item")
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    Everything recorded about one manufactured unit: which parts are
    installed and which the configuration still expects (`checklist`),
    firmware versions, MAC addresses, and the full stage history. Call
    this before any write against the item — it carries the ids
    (`slot_id`, `part_unit_id`, `firmware_type_id`) the write endpoints
    require, and `components_locked` tells you whether edits are open.
    """
    return _detail(db, _get_item(db, item_id), principal.role)


@router.get("/platforms", response_model=list[schemas.PlatformOut], summary="Platform and configuration catalog")
def list_platforms(
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    The product catalog: platforms (product lines) and the
    configurations under each. Use it to turn a name the user said into
    the variant_id the other endpoints take.
    """
    return [schemas.platform_out(p) for p in platforms_service.list_platforms(db)]


@router.get("/variants/{variant_id}", response_model=schemas.VariantDetail, summary="What a configuration requires")
def get_variant(
    variant_id: int,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    The as-planned specification for one configuration: which parts it
    calls for and how many, which firmware types must be recorded, which
    MAC addresses are expected. This is where the valid `slot_id` and
    `firmware_type_id` values for writes against items of this
    configuration come from.
    """
    _get_variant(db, variant_id)
    return _variant_payload(db, variant_id)["variant"]


@router.get(
    "/part-categories",
    response_model=list[schemas.PartCategoryOut],
    summary="Catalog of part kinds a BOM line can call for",
)
def list_part_categories(
    variant_id: int | None = Query(
        default=None,
        description="Restrict to what this configuration can use: global categories plus its own scoped ones.",
    ),
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    Source of the valid `part_category_id` for POST /variants/{id}/slots.
    Categories are user-editable data, not a fixed list of codes, so read
    them rather than assuming the names.
    """
    categories = (
        categories_service.list_available_for_variant(db, variant_id)
        if variant_id is not None
        else categories_service.list_categories(db)
    )
    return [schemas.part_category_out(c) for c in categories]


@router.get("/firmware-types", response_model=list[schemas.FirmwareTypeOut], summary="Catalog of firmware types")
def list_firmware_types(
    variant_id: int | None = Query(
        default=None,
        description="Restrict to what this configuration can use: global types plus its own scoped ones.",
    ),
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """Source of the valid `firmware_type_id` for POST /variants/{id}/firmware-requirements."""
    types = (
        firmware_types_service.list_available_for_variant(db, variant_id)
        if variant_id is not None
        else firmware_types_service.list_firmware_types(db)
    )
    return [schemas.firmware_type_out(t) for t in types]


@router.get(
    "/part-units/{serial_number}",
    response_model=schemas.PartHistory,
    summary="Full history of one physical part",
)
def get_part_history(
    serial_number: str,
    article: str | None = Query(
        default=None,
        description="Required only when the same serial exists under more than one part number.",
    ),
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("viewer")),
):
    """
    Every item this part was ever installed in, plus its firmware
    history — the RMA / failure-investigation view. Serial numbers are
    unique per part number, not globally, so a serial shared by two
    different part numbers needs `article` to disambiguate; the error
    says so and lists the candidates.
    """
    stmt = (
        select(PartUnit)
        .join(PartUnit.part_type)
        .options(selectinload(PartUnit.part_type).selectinload(PartType.category))
        .where(PartUnit.serial_number == serial_number)
    )
    if article is not None:
        stmt = stmt.where(func.lower(PartType.model_name) == article.lower())
    matches = list(db.scalars(stmt).all())

    if not matches:
        raise _not_found(
            f"No part with serial number '{serial_number}'"
            + (f" and part number '{article}'." if article else "."),
            "Try a partial match with GET /api/v1/search?q=<serial>.",
        )
    if len(matches) > 1:
        candidates = ", ".join(sorted(p.part_type.model_name for p in matches))
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "ambiguous_serial",
            f"Serial '{serial_number}' exists under several part numbers: {candidates}.",
            "Repeat the call with the 'article' query parameter set to one of them.",
        )

    part_unit = matches[0]
    installations = db.scalars(
        select(PlatformComponent)
        .options(selectinload(PlatformComponent.platform_item), selectinload(PlatformComponent.platform_variant_slot))
        .where(PlatformComponent.part_unit_id == part_unit.id)
        .order_by(PlatformComponent.installed_at.desc())
    ).all()
    records = db.scalars(
        select(FirmwareRecord)
        .options(selectinload(FirmwareRecord.firmware_type), selectinload(FirmwareRecord.part_unit))
        .where(FirmwareRecord.part_unit_id == part_unit.id)
        .order_by(FirmwareRecord.recorded_at.desc())
    ).all()

    return schemas.PartHistory(
        part=schemas.part_ref(part_unit),
        status=part_unit.status,
        status_label=schemas.PART_UNIT_STATUS_LABELS.get(part_unit.status, part_unit.status),
        installations=[
            schemas.PartInstallation(
                item=schemas.item_ref(c.platform_item),
                slot_name=c.platform_variant_slot.slot_name if c.platform_variant_slot else None,
                installed_at=c.installed_at,
                removed_at=c.removed_at,
                currently_installed=c.removed_at is None,
            )
            for c in installations
        ],
        firmware=[schemas.firmware_out(r) for r in records],
    )


# --------------------------------------------------------------------------
# Write endpoints
# --------------------------------------------------------------------------


@router.post("/items/{item_id}/events", response_model=schemas.WriteResult, summary="Record a lifecycle stage")
def record_event(
    item_id: int,
    payload: schemas.RecordEventRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Mark that a stage happened — kitting finished, testing started, the
    test passed, the unit shipped. The timestamp is now(); stages cannot
    be back-dated through this API, and the process order is enforced
    (shipping requires a passing test on record, and so on).

    Stages repeat legitimately: an item returned for repair goes through
    testing again. Use `dry_run: true` first if you are unsure the stage
    is allowed yet.
    """
    def action(session: Session, item: PlatformItem) -> str:
        events_service.record_event(
            session, actor=principal.user, item=item, event_type=payload.event_type, notes=payload.notes
        )
        return f"record stage '{payload.event_type}' on item {item.asset_tag}"

    return _write(db, principal, item_id, payload.dry_run, action)


@router.post("/items/{item_id}/components", response_model=schemas.WriteResult, summary="Install a component")
def install_component(
    item_id: int,
    payload: schemas.InstallComponentRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Fit a physical part into one BOM line of the item. A part that is
    not on record yet is registered on the fly, which is why `article`
    is needed for a serial number the system has not seen before.

    A part can only be installed in one item at a time — installing one
    that is fitted elsewhere fails rather than silently moving it.
    """
    def action(session: Session, item: PlatformItem) -> str:
        items_service.install_component(
            session,
            actor=principal.user,
            item=item,
            serial_number=payload.serial_number,
            platform_variant_slot_id=payload.platform_variant_slot_id,
            article=payload.article,
            comment=payload.comment,
        )
        identifier = payload.serial_number or payload.article or "unnamed part"
        return f"install part '{identifier}' into item {item.asset_tag}"

    return _write(db, principal, item_id, payload.dry_run, action)


@router.post("/items/{item_id}/firmware", response_model=schemas.WriteResult, summary="Record a firmware version")
def record_firmware(
    item_id: int,
    payload: schemas.RecordFirmwareRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Append a firmware version for a board installed in this item. This
    is an append-only log, not a field being overwritten: recording a
    new version keeps the previous one, because knowing which version
    was on a board when it failed is the point.
    """
    def action(session: Session, item: PlatformItem) -> str:
        firmware_service.record_firmware(
            session,
            actor=principal.user,
            item=item,
            part_unit_id=payload.part_unit_id,
            firmware_type_id=payload.firmware_type_id,
            image_slot=payload.image_slot,
            version=payload.version,
            notes=payload.notes,
        )
        return f"record firmware version '{payload.version}' on part {payload.part_unit_id}"

    return _write(db, principal, item_id, payload.dry_run, action)


@router.post("/items/{item_id}/mac", response_model=schemas.WriteResult, summary="Register a MAC address")
def add_mac(
    item_id: int,
    payload: schemas.AddMacRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Register a MAC address against the item (chassis-level, typically
    the BMC port) or against one board installed in it. The `label` is
    what ties it to the configuration's MAC requirements, so use the
    label the variant declares.
    """
    def action(session: Session, item: PlatformItem) -> str:
        mac_service.add_mac(
            session,
            actor=principal.user,
            item=item,
            mac_address=payload.mac_address,
            label=payload.label,
            part_unit_id=payload.part_unit_id,
        )
        return f"register MAC '{payload.mac_address}' on item {item.asset_tag}"

    return _write(db, principal, item_id, payload.dry_run, action)


# --------------------------------------------------------------------------
# Write endpoints — the catalog and the structure items are built against
#
# These exist so an agent can take a configuration from nothing to a
# fully specified BOM. They are deliberately more granular than the
# item-level writes above: an error here is not a mistyped serial, it
# silently changes what "complete" means for every unit of that
# configuration, so each step reports its own outcome rather than a batch
# half-applying.
# --------------------------------------------------------------------------


@router.post("/platforms", response_model=schemas.WriteResult, summary="Create a platform")
def create_platform(
    payload: schemas.CreatePlatformRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    A platform is a product family and carries no BOM of its own — that
    lives in its configurations. So this is normally the first of a
    sequence: platform, then a configuration under it, then that
    configuration's BOM lines.
    """

    def action(session: Session) -> tuple[str, dict]:
        platform = platforms_service.create_platform(
            session, actor=principal.user, name=payload.name, description=payload.description
        )
        return f"create platform '{platform.name}'", {"platform": schemas.platform_out(platform)}

    return _write_object(db, payload.dry_run, action)


@router.post(
    "/platforms/{platform_id}/variants",
    response_model=schemas.WriteResult,
    summary="Create a configuration under a platform",
)
def create_variant(
    platform_id: int,
    payload: schemas.CreateVariantRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """A configuration ("исполнение") is what items are actually built to. Starts with an empty BOM."""

    def action(session: Session) -> tuple[str, dict]:
        platform = platforms_service.get_platform(session, platform_id)
        if platform is None:
            raise _not_found(
                f"No platform with id {platform_id}.",
                "List them with GET /api/v1/platforms.",
            )
        variant = variants_service.create_variant(
            session,
            actor=principal.user,
            platform=platform,
            name=payload.name,
            description=payload.description,
        )
        return (
            f"create configuration '{variant.name}' under '{platform.name}'",
            _variant_payload(session, variant.id),
        )

    return _write_object(db, payload.dry_run, action)


@router.post("/variants/{variant_id}/slots", response_model=schemas.WriteResult, summary="Add a BOM line")
def add_slot(
    variant_id: int,
    payload: schemas.AddSlotRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    One line of the bill of materials: a named position, the kind of part
    it takes, and how many. This is what the completeness checklist of
    every item of this configuration is measured against.
    """

    def action(session: Session) -> tuple[str, dict]:
        variant = _get_variant(session, variant_id)
        slot = variants_service.add_slot(
            session,
            actor=principal.user,
            variant=variant,
            slot_name=payload.slot_name,
            category_id=payload.part_category_id,
            quantity=payload.quantity,
            required=payload.required,
        )
        return (
            f"add BOM line '{slot.slot_name}' (x{slot.quantity}) to '{variant.name}'",
            _variant_payload(session, variant_id),
        )

    return _write_object(db, payload.dry_run, action)


@router.post(
    "/variants/{variant_id}/firmware-requirements",
    response_model=schemas.WriteResult,
    summary="Require a firmware type on this configuration",
)
def add_firmware_requirement(
    variant_id: int,
    payload: schemas.AddFirmwareRequirementRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Declares that items of this configuration must have a version
    recorded for this firmware type. Until it is declared here, recording
    that firmware against an item is rejected.
    """

    def action(session: Session) -> tuple[str, dict]:
        variant = _get_variant(session, variant_id)
        requirement = variants_service.add_firmware_requirement(
            session,
            actor=principal.user,
            variant=variant,
            firmware_type_id=payload.firmware_type_id,
            track_backup=payload.track_backup,
        )
        return (
            f"require firmware '{requirement.firmware_type.name}' on '{variant.name}'",
            _variant_payload(session, variant_id),
        )

    return _write_object(db, payload.dry_run, action)


@router.post(
    "/variants/{variant_id}/mac-requirements",
    response_model=schemas.WriteResult,
    summary="Expect a MAC address on this configuration",
)
def add_mac_requirement(
    variant_id: int,
    payload: schemas.AddMacRequirementRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """The label here is what POST /items/{id}/mac matches an address against."""

    def action(session: Session) -> tuple[str, dict]:
        variant = _get_variant(session, variant_id)
        requirement = variants_service.add_mac_requirement(
            session,
            actor=principal.user,
            variant=variant,
            label=payload.label,
            required=payload.required,
        )
        return (
            f"expect MAC '{requirement.label}' on '{variant.name}'",
            _variant_payload(session, variant_id),
        )

    return _write_object(db, payload.dry_run, action)


@router.post("/part-categories", response_model=schemas.WriteResult, summary="Add a kind of part to the catalog")
def create_part_category(
    payload: schemas.CreatePartCategoryRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Only needed when no existing category fits — check
    GET /api/v1/part-categories first. The group matters beyond
    bookkeeping: firmware can only be recorded against parts in "custom"
    categories.
    """

    def action(session: Session) -> tuple[str, dict]:
        category = categories_service.create_category(
            session,
            actor=principal.user,
            name=payload.name,
            group=payload.group,
            platform_variant_id=payload.platform_variant_id,
        )
        return (
            f"add part category '{category.name}'",
            {"part_category": schemas.part_category_out(category)},
        )

    return _write_object(db, payload.dry_run, action)


@router.post("/firmware-types", response_model=schemas.WriteResult, summary="Add a firmware type to the catalog")
def create_firmware_type(
    payload: schemas.CreateFirmwareTypeRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """Check GET /api/v1/firmware-types first; reuse beats a near-duplicate name."""

    def action(session: Session) -> tuple[str, dict]:
        firmware_type = firmware_types_service.create_firmware_type(
            session,
            actor=principal.user,
            name=payload.name,
            platform_variant_id=payload.platform_variant_id,
        )
        return (
            f"add firmware type '{firmware_type.name}'",
            {"firmware_type": schemas.firmware_type_out(firmware_type)},
        )

    return _write_object(db, payload.dry_run, action)


# --------------------------------------------------------------------------
# Write endpoints — items
# --------------------------------------------------------------------------


@router.post("/items", response_model=schemas.WriteResult, summary="Create a manufactured item")
def create_item(
    payload: schemas.CreateItemRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Registers one physical unit built to a configuration. It starts empty
    — components, firmware, MAC addresses and stages are recorded through
    the calls above.
    """

    def action(session: Session) -> tuple[str, dict]:
        item = items_service.create_item(
            session,
            actor=principal.user,
            platform_variant_id=payload.platform_variant_id,
            asset_tag=payload.asset_tag,
            customer=payload.customer,
            location=payload.location,
            notes=payload.notes,
        )
        return (
            f"create item '{item.asset_tag}'",
            {"item": _detail(session, _get_item(session, item.id), principal.role)},
        )

    return _write_object(db, payload.dry_run, action)


@router.patch("/items/{item_id}", response_model=schemas.WriteResult, summary="Update an item's details")
def update_item(
    item_id: int,
    payload: schemas.UpdateItemRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Customer, location and notes only. The asset tag and the
    configuration are what the unit *is*; changing either would rewrite
    the meaning of records already pointing at it, so neither is editable
    here or in the web interface.
    """

    def action(session: Session, item: PlatformItem) -> str:
        # An omitted field keeps its current value, an explicit null
        # clears it. Without model_fields_set the two are indistinguishable
        # by the time the request is parsed, and every PATCH would wipe
        # whatever it did not mention.
        provided = payload.model_fields_set
        items_service.update_details(
            session,
            actor=principal.user,
            item=item,
            customer=payload.customer if "customer" in provided else item.customer,
            location=payload.location if "location" in provided else item.location,
            notes=payload.notes if "notes" in provided else item.notes,
        )
        return f"update item {item.asset_tag}"

    return _write(db, principal, item_id, payload.dry_run, action)


@router.post(
    "/items/{item_id}/components/{component_id}/remove",
    response_model=schemas.WriteResult,
    summary="Remove an installed component",
)
def remove_component(
    item_id: int,
    component_id: int,
    payload: schemas.RemoveComponentRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Marks a component as no longer installed and returns the part to
    stock. Not a deletion: platform_components is an append-only history,
    so the removal is written into the record rather than erasing that
    the part was ever there. That is why this is a POST .../remove and
    not a DELETE.

    Blocked while the item is marked assembled, same as installing.
    """

    def action(session: Session, item: PlatformItem) -> str:
        component = items_service.remove_component(
            session, actor=principal.user, item=item, component_id=component_id
        )
        serial = component.part_unit.serial_number or f"part_unit {component.part_unit_id}"
        return f"remove {serial} from {item.asset_tag}"

    return _write(db, principal, item_id, payload.dry_run, action)


# --------------------------------------------------------------------------
# Deletion
#
# The only calls here that destroy rather than record. Three things keep
# them survivable:
#
# - every one is refused while something still depends on the row, so a
#   delete can never cascade into inventory the caller didn't name;
# - a shipped item cannot be deleted at all — that is delivered-product
#   history, not a mistake to clean up;
# - all of them are audited, which is what makes the log the one place a
#   deleted platform still exists.
#
# dry_run is a query parameter rather than a body field: several HTTP
# stacks drop bodies on DELETE, and a silently ignored dry_run on a
# destructive call is the worst possible failure of this whole design.
# Attachments are kept on disk during a dry run (unlink_files=False in
# the services) because the filesystem is not covered by the rollback.
# --------------------------------------------------------------------------


_DRY_RUN = Query(
    default=False,
    description="Check whether the deletion is allowed and report what it would remove, without doing it.",
)


@router.delete("/items/{item_id}", response_model=schemas.WriteResult, summary="Delete an item")
def delete_item(
    item_id: int,
    dry_run: bool = _DRY_RUN,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Removes the unit and its own history — components, stages, its MAC
    addresses, its files. Parts that were installed go back to stock;
    their firmware records and their own MAC addresses stay with the
    part, because those describe the part rather than this unit.

    Refused once the item has been shipped.
    """

    def action(session: Session) -> tuple[str, dict]:
        item = _get_item(session, item_id)
        asset_tag = item.asset_tag
        items_service.delete_item(session, actor=principal.user, item=item, unlink_files=not dry_run)
        return f"delete item '{asset_tag}'", {}

    return _write_object(db, dry_run, action)


@router.delete("/variants/{variant_id}", response_model=schemas.WriteResult, summary="Delete a configuration")
def delete_variant(
    variant_id: int,
    dry_run: bool = _DRY_RUN,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("admin")),
):
    """
    Takes the whole BOM with it — slots, firmware and MAC requirements,
    and any catalog entries scoped to this configuration alone. Refused
    while any item is built to it, and refused if one of those scoped
    catalog entries is still used elsewhere.

    Requires the admin role, matching the web interface: this is the
    definition a whole production run was checked against.
    """

    def action(session: Session) -> tuple[str, dict]:
        variant = _get_variant(session, variant_id)
        name = variant.name
        variants_service.delete_variant(
            session, actor=principal.user, variant=variant, unlink_files=not dry_run
        )
        return f"delete configuration '{name}' and its BOM", {}

    return _write_object(db, dry_run, action)


@router.delete("/platforms/{platform_id}", response_model=schemas.WriteResult, summary="Delete a platform")
def delete_platform(
    platform_id: int,
    dry_run: bool = _DRY_RUN,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("admin")),
):
    """Refused while it still has configurations. Admin role, as in the web interface."""

    def action(session: Session) -> tuple[str, dict]:
        platform = platforms_service.get_platform(session, platform_id)
        if platform is None:
            raise _not_found(
                f"No platform with id {platform_id}.",
                "List them with GET /api/v1/platforms.",
            )
        name = platform.name
        platforms_service.delete_platform(session, actor=principal.user, platform=platform)
        return f"delete platform '{name}'", {}

    return _write_object(db, dry_run, action)


@router.delete(
    "/part-categories/{category_id}",
    response_model=schemas.WriteResult,
    summary="Delete a part category",
)
def delete_part_category(
    category_id: int,
    dry_run: bool = _DRY_RUN,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """Refused while any BOM line or registered part still points at it."""

    def action(session: Session) -> tuple[str, dict]:
        category = session.get(PartCategory, category_id)
        if category is None:
            raise _not_found(
                f"No part category with id {category_id}.",
                "List them with GET /api/v1/part-categories.",
            )
        name = category.name
        categories_service.delete_category(session, actor=principal.user, category=category)
        return f"delete part category '{name}'", {}

    return _write_object(db, dry_run, action)


@router.delete(
    "/firmware-types/{firmware_type_id}",
    response_model=schemas.WriteResult,
    summary="Delete a firmware type",
)
def delete_firmware_type(
    firmware_type_id: int,
    dry_run: bool = _DRY_RUN,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_api_role("engineer")),
):
    """
    Refused if any configuration requires it or any version was ever
    recorded against it — firmware history is permanent, so in practice a
    type that has been used is not removable.
    """

    def action(session: Session) -> tuple[str, dict]:
        firmware_type = session.get(FirmwareType, firmware_type_id)
        if firmware_type is None:
            raise _not_found(
                f"No firmware type with id {firmware_type_id}.",
                "List them with GET /api/v1/firmware-types.",
            )
        name = firmware_type.name
        firmware_types_service.delete_firmware_type(
            session, actor=principal.user, firmware_type=firmware_type
        )
        return f"delete firmware type '{name}'", {}

    return _write_object(db, dry_run, action)
