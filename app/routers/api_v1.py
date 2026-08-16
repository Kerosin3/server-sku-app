"""
JSON API for machine consumers — built for an LLM agent driving the
tracker (LangChain and similar), not for a browser.

Design notes, since this differs from the rest of the project on purpose:

- **Task-shaped, not table-shaped.** Ten endpoints answering the
  questions an operator actually asks ("where is this serial?", "what's
  missing from this item?", "mark the test passed"), rather than CRUD
  over sixteen tables. A small, well-named tool set is what an agent can
  actually choose correctly between.

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

from app.api_auth import ApiError, require_api_role
from app.db import dry_run_session, get_db
from app.models import FirmwareRecord, PartType, PartUnit, PlatformComponent, PlatformItem, PlatformVariant, User
from app.schemas import api as schemas
from app.services import firmware_records as firmware_service
from app.services import mac_addresses as mac_service
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


def _detail(db: Session, item: PlatformItem, user: User) -> schemas.ItemDetail:
    return schemas.item_detail(
        item,
        include_customer=user.role != "viewer",
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
    user: User,
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
            item=_detail(session, _get_item(session, item_id), user),
        )


# --------------------------------------------------------------------------
# Read endpoints
# --------------------------------------------------------------------------


@router.get("/search", response_model=schemas.SearchResults, summary="Find a part, item or MAC address")
def search(
    q: str = Query(min_length=2, description="Serial number, part number, asset tag or MAC address (partial ok)."),
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("viewer")),
):
    """
    Call this first whenever the user names a physical thing — a serial
    number, a part number, an asset tag, a MAC — and you need to know
    what and where it is. For a part, the response says which item it is
    installed in right now, which is the question this system exists to
    answer.
    """
    results = search_service.search(db, q)
    include_customer = user.role != "viewer"
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
    user: User = Depends(require_api_role("viewer")),
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
        items=[schemas.item_summary(i, include_customer=user.role != "viewer") for i in items],
    )


@router.get("/items/{item_id}", response_model=schemas.ItemDetail, summary="Full state of one item")
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("viewer")),
):
    """
    Everything recorded about one manufactured unit: which parts are
    installed and which the configuration still expects (`checklist`),
    firmware versions, MAC addresses, and the full stage history. Call
    this before any write against the item — it carries the ids
    (`slot_id`, `part_unit_id`, `firmware_type_id`) the write endpoints
    require, and `components_locked` tells you whether edits are open.
    """
    return _detail(db, _get_item(db, item_id), user)


@router.get("/platforms", response_model=list[schemas.PlatformOut], summary="Platform and configuration catalog")
def list_platforms(
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("viewer")),
):
    """
    The product catalog: platforms (product lines) and the
    configurations under each. Use it to turn a name the user said into
    the variant_id the other endpoints take.
    """
    return [
        schemas.PlatformOut(
            id=p.id,
            name=p.name,
            description=p.description,
            variants=[
                schemas.VariantRef(
                    id=v.id, name=v.name, platform=schemas.PlatformRef(id=p.id, name=p.name)
                )
                for v in p.variants
            ],
        )
        for p in platforms_service.list_platforms(db)
    ]


@router.get("/variants/{variant_id}", response_model=schemas.VariantDetail, summary="What a configuration requires")
def get_variant(
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("viewer")),
):
    """
    The as-planned specification for one configuration: which parts it
    calls for and how many, which firmware types must be recorded, which
    MAC addresses are expected. This is where the valid `slot_id` and
    `firmware_type_id` values for writes against items of this
    configuration come from.
    """
    variant = variants_service.get_variant(db, variant_id)
    if variant is None:
        raise _not_found(
            f"No variant with id {variant_id}.",
            "List the catalog with GET /api/v1/platforms.",
        )
    return schemas.VariantDetail(
        id=variant.id,
        name=variant.name,
        description=variant.description,
        platform=schemas.PlatformRef(id=variant.platform.id, name=variant.platform.name),
        slots=[
            schemas.SlotOut(
                id=s.id,
                slot_name=s.slot_name,
                category=s.category.name,
                quantity=s.quantity,
                required=s.required,
            )
            for s in variant.slots
        ],
        firmware_requirements=[
            schemas.FirmwareRequirementOut(
                firmware_type_id=r.firmware_type_id,
                firmware_type=r.firmware_type.name,
                track_backup=r.track_backup,
            )
            for r in variant.firmware_requirements
        ],
        mac_requirements=[
            schemas.MacRequirementOut(label=r.label, required=r.required) for r in variant.mac_requirements
        ],
        item_count=db.scalar(
            select(func.count()).select_from(PlatformItem).where(PlatformItem.platform_variant_id == variant.id)
        )
        or 0,
    )


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
    user: User = Depends(require_api_role("viewer")),
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
    user: User = Depends(require_api_role("engineer")),
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
            session, actor=user, item=item, event_type=payload.event_type, notes=payload.notes
        )
        return f"record stage '{payload.event_type}' on item {item.asset_tag}"

    return _write(db, user, item_id, payload.dry_run, action)


@router.post("/items/{item_id}/components", response_model=schemas.WriteResult, summary="Install a component")
def install_component(
    item_id: int,
    payload: schemas.InstallComponentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("engineer")),
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
            actor=user,
            item=item,
            serial_number=payload.serial_number,
            platform_variant_slot_id=payload.platform_variant_slot_id,
            article=payload.article,
            comment=payload.comment,
        )
        identifier = payload.serial_number or payload.article or "unnamed part"
        return f"install part '{identifier}' into item {item.asset_tag}"

    return _write(db, user, item_id, payload.dry_run, action)


@router.post("/items/{item_id}/firmware", response_model=schemas.WriteResult, summary="Record a firmware version")
def record_firmware(
    item_id: int,
    payload: schemas.RecordFirmwareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("engineer")),
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
            actor=user,
            item=item,
            part_unit_id=payload.part_unit_id,
            firmware_type_id=payload.firmware_type_id,
            image_slot=payload.image_slot,
            version=payload.version,
            notes=payload.notes,
        )
        return f"record firmware version '{payload.version}' on part {payload.part_unit_id}"

    return _write(db, user, item_id, payload.dry_run, action)


@router.post("/items/{item_id}/mac", response_model=schemas.WriteResult, summary="Register a MAC address")
def add_mac(
    item_id: int,
    payload: schemas.AddMacRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_role("engineer")),
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
            actor=user,
            item=item,
            mac_address=payload.mac_address,
            label=payload.label,
            part_unit_id=payload.part_unit_id,
        )
        return f"register MAC '{payload.mac_address}' on item {item.asset_tag}"

    return _write(db, user, item_id, payload.dry_run, action)
