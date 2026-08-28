"""
LangChain tools over the Server SKU Tracker JSON API (/api/v1).

Separate from the tracker itself on purpose: the application must stay
deployable with one `docker compose up` and no extra dependencies
(AGENTS.md, "Конвенции кода"), and LangChain is a dependency of the
consumer, not of the service. Nothing here is imported by app/.

Two decisions shape this module, both of which follow from the caller
being a language model rather than a program:

**Failures are returned, not raised.** An exception out of a LangChain
tool becomes a stack trace or an aborted run, and the useful part — the
`hint` the API puts on every error, naming the call that would fix the
problem — never reaches the model. Every tool returns the same four-field
contract for success and for failure (see format_result), so the model
reads one shape and, when Status is error, corrects itself from the hint.
Transport failures are shaped the same way, so "the server is down" and
"you passed a bad id" arrive in a form the model can tell apart without
special-casing.

**Writes dry-run by default.** `record_item_event` will not commit
unless the caller passes dry_run=False. The API validates a dry run
exactly as it validates a real call — same service, same rules, on a
transaction that is rolled back — so the safe order is: dry run, read
the outcome, then repeat with dry_run=False. Making that the default
means a model that forgets the protocol fails safe.
"""
import json
import os

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

BASE_URL = os.environ.get("SERVER_TRACKER_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("SERVER_TRACKER_TOKEN", "")
TIMEOUT_SECONDS = float(os.environ.get("SERVER_TRACKER_TIMEOUT", "10"))


# --------------------------------------------------------------------------
# HTTP wrapper
# --------------------------------------------------------------------------


def call_api(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    """
    One explicit HTTP call to /api/v1, with every outcome flattened into
    the same dict shape:

        {"ok": True,  "status": 200, "data": {...}}
        {"ok": False, "status": 409, "code": "...", "message": "...", "hint": "..."}

    Usable on its own, without LangChain — the tools below are thin
    wrappers around it, which keeps the HTTP behaviour testable without
    a model in the loop.
    """
    if not TOKEN:
        return {
            "ok": False,
            "status": None,
            "code": "no_token_configured",
            "message": "SERVER_TRACKER_TOKEN is not set, so no request was attempted.",
            "hint": "Issue a token at /api-tokens and export SERVER_TRACKER_TOKEN=stk_...",
        }

    url = f"{BASE_URL}/api/v1{path}"
    try:
        response = httpx.request(
            method,
            url,
            params=params,
            json=body,
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        # Never reached the server: no status, and retrying the same call
        # is pointless until whatever this is gets fixed.
        return {
            "ok": False,
            "status": None,
            "code": "transport_error",
            "message": f"Could not reach the tracker at {BASE_URL}: {exc.__class__.__name__}.",
            "hint": "Check that the application is running and SERVER_TRACKER_URL is correct.",
        }

    if response.status_code < 400:
        return {"ok": True, "status": response.status_code, "data": response.json()}

    # The API guarantees {"error": {code, message, hint}} for every
    # failure, including the ones FastAPI raises itself. The fallback
    # below only matters if something upstream (a proxy, say) answers
    # instead, which would not follow that contract.
    try:
        error = response.json()["error"]
    except (ValueError, KeyError, TypeError):
        return {
            "ok": False,
            "status": response.status_code,
            "code": "unexpected_response",
            "message": response.text[:500],
            "hint": "This did not come from the tracker's API; check what is answering on this URL.",
        }

    return {
        "ok": False,
        "status": response.status_code,
        "code": error.get("code"),
        "message": error.get("message"),
        "hint": error.get("hint"),
    }


def format_result(action: str, payload: dict) -> str:
    """
    Render an outcome into the fixed shape every tool returns:

        Status: success | error
        Action: <что делали>
        Data:   <результат API>
        Errors: <код, сообщение, подсказка>

    One shape for success and failure means the model learns to read one
    thing. `Data` and `Errors` are mutually exclusive and each is omitted
    when it would be empty — an "Errors: —" line on every successful call
    is noise the model has to read past on every single step.

    `Action` restates what was attempted. Without it a bare result is
    ambiguous once several calls are in the conversation, and it is also
    what makes the trace readable to the person watching.

    Data stays JSON, with ensure_ascii=False: the API answers with
    Russian labels next to every code, and escaped \\uXXXX would be both
    unreadable and roughly twice the tokens.
    """
    if payload.get("ok"):
        data = json.dumps(payload.get("data"), ensure_ascii=False, indent=2)
        return f"Status: success\nAction: {action}\nData: {data}"

    errors = f"{payload.get('code')}: {payload.get('message')}"
    if payload.get("hint"):
        errors += f"\nПодсказка: {payload['hint']}"
    return f"Status: error\nAction: {action}\nErrors: {errors}"


def is_error(result: str) -> bool:
    return result.startswith("Status: error")


def summary(result: str) -> str:
    """One-line description of an outcome, for the trace in chat.py."""
    if not is_error(result):
        return "success"
    for line in result.splitlines():
        if line.startswith("Errors: "):
            return "error — " + line.removeprefix("Errors: ").split(":", 1)[0]
    return "error"


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


class SearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        description=(
            "Serial number, part number (article), asset tag or MAC address. "
            "Partial values work. This is whatever the user named the thing by."
        ),
    )


@tool("search_inventory", args_schema=SearchInput)
def search_inventory(query: str) -> str:
    """Find where a part, item or MAC address is right now.

    Call this first whenever the user names a physical thing. For a part
    the answer says which item it is installed in at the moment, and the
    ids it returns are what every other tool takes as input.

    On success Data holds {"items": [...], "parts": [...],
    "mac_addresses": [...]}. Empty lists mean nothing matched — that is a
    valid answer, not an error.
    """
    return format_result(
        f"Поиск по запросу «{query}»",
        call_api("GET", "/search", params={"q": query}),
    )


class GetItemInput(BaseModel):
    item_id: int = Field(description="Numeric id of the item, e.g. from search_inventory.")


@tool("get_item", args_schema=GetItemInput)
def get_item(item_id: int) -> str:
    """Get the full state of one manufactured item.

    Returns its completeness checklist against the configuration it is
    built to, the components installed and removed, firmware versions,
    MAC addresses and the full stage history. Use this before answering
    anything detailed about a unit, and to get the component and slot ids
    that write operations need.

    `status` is a stable code; `status_label` is the same thing in
    Russian — quote the label to the user, branch on the code.
    """
    return format_result(
        f"Чтение состояния изделия id={item_id}",
        call_api("GET", f"/items/{item_id}"),
    )


class RecordEventInput(BaseModel):
    item_id: int = Field(description="Numeric id of the item.")
    event_type: str = Field(
        description=(
            "One of: assembled, disassembled, test_started, test_passed, "
            "test_passed_with_remarks, test_failed, shipped, service."
        )
    )
    # Plain str with an empty default, not `str | None`. A nullable field
    # gives a model two ways to say "nothing here" and this one reliably
    # picked a third: the first attempt at filling it came back as -2026,
    # or as false, before the model corrected itself on a retry. With the
    # union gone it fills the field or leaves it empty, which are the only
    # two things that make sense.
    notes: str = Field(
        default="",
        description=(
            "Free-text comment. Leave it as an empty string when there is nothing to add. "
            "Required for test_passed_with_remarks: what the remarks were."
        ),
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "True checks the stage is allowed and reports what would happen, writing nothing. "
            "Pass False only after a dry run succeeded and the user has confirmed."
        ),
    )


@tool("record_item_event", args_schema=RecordEventInput)
def record_item_event(item_id: int, event_type: str, notes: str = "", dry_run: bool = True) -> str:
    """Record a lifecycle stage against an item. Defaults to a dry run.

    Stage order is enforced by the tracker: shipping needs a passed test,
    testing needs the unit assembled, and so on. A refusal comes back as
    Status: error with the code prerequisite_not_met and a hint naming
    what is missing — read it.

    Use it in two steps. First call it as-is to check the stage is
    allowed; the response describes the state the write would produce
    without touching the database. Then, once the user has confirmed,
    call it again with dry_run=false to commit.
    """
    body = {"event_type": event_type, "dry_run": dry_run}
    if notes:
        body["notes"] = notes
    action = f"Этап «{event_type}» на изделие id={item_id}"
    if notes:
        action += f", комментарий «{notes}»"
    action += " — проверка без записи" if dry_run else " — запись"
    return format_result(action, call_api("POST", f"/items/{item_id}/events", body=body))


class ListItemsInput(BaseModel):
    status: str = Field(
        default="",
        description=(
            "Filter by current stage: assembly, assembled, disassembled, testing, shipped. "
            "Empty string means every stage."
        ),
    )
    variant_id: int = Field(
        default=0,
        description="Restrict to one configuration; 0 means all of them. Get ids from list_platforms.",
    )
    limit: int = Field(default=20, ge=1, le=100)


@tool("list_items", args_schema=ListItemsInput)
def list_items(status: str = "", variant_id: int = 0, limit: int = 20) -> str:
    """Answer questions about a group of items rather than a single one.

    "What is still in testing", "how many of this configuration have
    shipped", "show me everything being assembled". For one item you
    already have an id for, get_item returns far more.

    Data holds `total` — the full count ignoring the limit — alongside
    the page of items, so you can say how many there are even when you
    only listed some.
    """
    params: dict = {"limit": limit}
    described = []
    if status:
        params["status"] = status
        described.append(f"этап «{status}»")
    if variant_id:
        params["variant_id"] = variant_id
        described.append(f"исполнение id={variant_id}")
    action = "Список изделий" + (": " + ", ".join(described) if described else " (все)")
    return format_result(action, call_api("GET", "/items", params=params))


class PartHistoryInput(BaseModel):
    serial_number: str = Field(description="Exact serial number of the part.")


@tool("get_part_history", args_schema=PartHistoryInput)
def get_part_history(serial_number: str) -> str:
    """Every item a part has ever been installed in, plus its firmware.

    This is the view for investigating a failure or an RMA: where the
    part is now, where it was before, and when it moved. search_inventory
    only says where it is at the moment.
    """
    return format_result(
        f"История детали {serial_number}",
        call_api("GET", f"/part-units/{serial_number}"),
    )


class NoInput(BaseModel):
    pass


@tool("list_platforms", args_schema=NoInput)
def list_platforms() -> str:
    """The catalog of platforms and the configurations under each.

    Use it to turn a name a person said ("четырёхюнитовый с восемью GPU")
    into the numeric variant_id the other tools take. Also the way to
    answer "what do we even make".
    """
    return format_result("Каталог платформ и исполнений", call_api("GET", "/platforms"))


class GetVariantInput(BaseModel):
    variant_id: int = Field(description="Numeric id of the configuration, from list_platforms.")


@tool("get_variant", args_schema=GetVariantInput)
def get_variant(variant_id: int) -> str:
    """What a configuration requires — the standard items are checked against.

    Which parts and how many, which firmware must be recorded, which MAC
    addresses are expected. This is where valid slot ids come from when
    installing a component, and it answers "what is supposed to be in
    this machine" as opposed to "what actually is".
    """
    return format_result(
        f"Состав исполнения id={variant_id}",
        call_api("GET", f"/variants/{variant_id}"),
    )


class InstallComponentInput(BaseModel):
    item_id: int = Field(description="Which item the part goes into.")
    slot_id: int = Field(
        description="Which BOM line of that item's configuration this fills; from get_item -> checklist."
    )
    serial_number: str = Field(
        default="",
        description="Serial of the physical part. Leave empty only for parts that genuinely have none.",
    )
    article: str = Field(
        default="",
        description="Part number. Required when this serial is not on record yet; otherwise leave empty.",
    )
    comment: str = Field(
        default="",
        description="Required instead of a serial number when the part has none — this identifies it.",
    )
    dry_run: bool = Field(
        default=True,
        description="True checks the install and writes nothing. Pass False only after a dry run and a confirmation.",
    )


@tool("install_component", args_schema=InstallComponentInput)
def install_component(
    item_id: int,
    slot_id: int,
    serial_number: str = "",
    article: str = "",
    comment: str = "",
    dry_run: bool = True,
) -> str:
    """Install a part into one BOM line of an item. Defaults to a dry run.

    Refused while the item is marked assembled: its component list is
    locked until a 'disassembled' event reopens it. Also refused if the
    part is currently installed somewhere else — find it with
    search_inventory and remove it there first.

    Same two steps as record_item_event: check, show the person, then
    call again with dry_run=false.
    """
    body: dict = {"platform_variant_slot_id": slot_id, "dry_run": dry_run}
    if serial_number:
        body["serial_number"] = serial_number
    if article:
        body["article"] = article
    if comment:
        body["comment"] = comment

    what = serial_number or comment or "деталь без серийника"
    action = f"Установка «{what}» в элемент id={slot_id} изделия id={item_id}"
    action += " — проверка без записи" if dry_run else " — запись"
    return format_result(action, call_api("POST", f"/items/{item_id}/components", body=body))


# Eight tools out of the API's twenty-seven operations, and the gap is
# the point. A model picks correctly from a short, clearly separated
# list; mapping every endpoint to a tool would make several of them
# near-synonyms and the choice unreliable. Firmware and MAC registration
# are the obvious next candidates — they belong to the same build flow —
# but they are narrower than these, so they wait until something actually
# needs them.
TOOLS = [
    search_inventory,
    get_item,
    list_items,
    get_part_history,
    list_platforms,
    get_variant,
    record_item_event,
    install_component,
]
