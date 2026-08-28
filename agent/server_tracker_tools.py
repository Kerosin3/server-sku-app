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
problem — never reaches the model. Every tool here returns the same JSON
envelope for success and for failure, so the model reads `ok` and, when
it is false, `hint`, and corrects itself. Transport failures are shaped
the same way, so "the server is down" and "you passed a bad id" arrive
in a form the model can tell apart without special-casing.

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


def _as_tool_output(payload: dict) -> str:
    """
    Structured result, serialized for the model. ensure_ascii=False
    matters: the API answers with Russian labels next to every code, and
    escaped \\uXXXX would be both unreadable and a waste of tokens.
    """
    return json.dumps(payload, ensure_ascii=False, indent=2)


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

    Returns JSON: {"ok": true, "data": {"items": [...], "parts": [...],
    "mac_addresses": [...]}}. Empty lists mean nothing matched — that is
    a valid answer, not an error.
    """
    return _as_tool_output(call_api("GET", "/search", params={"q": query}))


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
    return _as_tool_output(call_api("GET", f"/items/{item_id}"))


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
    {"ok": false, "code": "prerequisite_not_met", "hint": "..."} — read
    the hint, it names what is missing.

    Use it in two steps. First call it as-is to check the stage is
    allowed; the response describes the state the write would produce
    without touching the database. Then, once the user has confirmed,
    call it again with dry_run=false to commit.
    """
    body = {"event_type": event_type, "dry_run": dry_run}
    if notes:
        body["notes"] = notes
    return _as_tool_output(call_api("POST", f"/items/{item_id}/events", body=body))


TOOLS = [search_inventory, get_item, record_item_event]
