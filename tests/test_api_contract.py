"""
Contract tests for /api/v1 — the promises a consumer (an LLM agent built
on this API) is allowed to rely on.

These are not "does the endpoint work" tests. They pin the *shape* of
what comes back: field names, the set of error codes, the error
envelope, code/label separation, timestamp format, and the fact that
dry_run writes nothing. A refactor that quietly renames `status_label`
or turns a 409 into a 500 is exactly the kind of change that breaks an
agent silently in production and that these catch at commit time.

Fixture data is the demo example the app seeds on first admin creation;
see tests/conftest.py for why there is no mock server here.
"""
import re
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.i18n import PLATFORM_EVENT_TYPES, PLATFORM_STATUSES
from tests.conftest import event_count

AGENTS_MD = Path(__file__).resolve().parent.parent / "AGENTS.md"


def _normalize(path: str) -> str:
    """`/items/{id}` and `/items/{item_id}` are the same endpoint here."""
    return re.sub(r"\{[^}]+\}", "{}", path)


# --------------------------------------------------------------------------
# The documented surface must be the real surface
# --------------------------------------------------------------------------


def test_documented_endpoints_match_the_implementation(client: TestClient):
    """
    AGENTS.md carries a catalog of what an agent can do, and the rule
    that it is updated in the same change as the endpoint. This test is
    what makes that rule real rather than aspirational: add an endpoint
    without documenting it (or document one that doesn't exist) and this
    fails.

    The agent builds its tools from that catalog *and* from
    /openapi.json; it cannot notice the two disagreeing, so something
    else has to.
    """
    section = AGENTS_MD.read_text(encoding="utf-8").split("### Что агент может через API", 1)
    assert len(section) == 2, "the API capability section is missing from AGENTS.md"
    documented = {
        f"{method} {_normalize(path)}"
        for method, path in re.findall(r"`(GET|POST|PATCH|PUT|DELETE) (/[^`?]*)", section[1])
    }

    schema = client.get("/openapi.json").json()
    implemented = {
        f"{method.upper()} {_normalize(path.removeprefix('/api/v1'))}"
        for path, methods in schema["paths"].items()
        if path.startswith("/api/v1")
        for method in methods
    }

    assert documented == implemented, (
        f"AGENTS.md and the code disagree.\n"
        f"  documented but missing: {sorted(documented - implemented)}\n"
        f"  implemented but undocumented: {sorted(implemented - documented)}"
    )


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


# Both take api_token without sending it: a live token has to exist for
# these to be testing "your token is wrong" rather than "this deployment
# has no API", which is a different code (see api_disabled below).


def test_request_without_token_is_rejected(client: TestClient, api_token):
    response = client.get("/api/v1/items")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_request_with_wrong_token_is_rejected(client: TestClient, api_token):
    response = client.get("/api/v1/items", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


# --------------------------------------------------------------------------
# Error envelope
# --------------------------------------------------------------------------


def test_every_error_uses_the_same_envelope(client: TestClient, auth):
    """
    One shape for every failure, including the ones FastAPI raises itself
    (unknown route, malformed body). A consumer that learned to read
    error.code must never meet a different envelope.
    """
    responses = [
        client.get("/api/v1/items"),  # 401, from the auth dependency
        client.get("/api/v1/items/999999", headers=auth),  # 404, from the router
        client.get("/api/v1/nope", headers=auth),  # 404, from FastAPI's routing
        client.post("/api/v1/items/1/events", json={}, headers=auth),  # 422, validation
    ]
    for response in responses:
        assert response.status_code >= 400, response.text
        body = response.json()
        assert set(body) == {"error"}, f"{response.url} returned {body}"
        error = body["error"]
        assert isinstance(error.get("code"), str) and error["code"]
        assert isinstance(error.get("message"), str) and error["message"]
        assert "hint" in error


def test_domain_errors_carry_an_actionable_hint(client: TestClient, auth, demo_item):
    """A hint naming the call that would fix it is what lets an agent self-correct."""
    response = client.post(
        f"/api/v1/items/{demo_item['id']}/events",
        json={"event_type": "test_passed_with_remarks"},
        headers=auth,
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "remarks_required"
    assert error["hint"], "a domain error without a hint leaves the agent guessing"


@pytest.mark.parametrize(
    "endpoint, payload, expected_code",
    [
        ("events", {"event_type": "no_such_stage"}, "invalid_event_type"),
        ("events", {"event_type": "test_passed_with_remarks"}, "remarks_required"),
        ("components", {"platform_variant_slot_id": 1, "serial_number": "X"}, "components_locked"),
        ("firmware", {"part_unit_id": 999999, "firmware_type_id": 1, "version": "1.0"}, "part_not_installed"),
        ("mac", {"mac_address": "not-a-mac"}, "invalid_mac_format"),
    ],
)
def test_error_codes_are_stable(client: TestClient, auth, demo_item, endpoint, payload, expected_code):
    """
    These codes are the branch labels an agent's logic hangs off. Renaming
    one is a breaking change and has to be a deliberate decision, not a
    side effect of touching a service.
    """
    response = client.post(f"/api/v1/items/{demo_item['id']}/{endpoint}", json=payload, headers=auth)
    assert response.status_code >= 400
    assert response.json()["error"]["code"] == expected_code


# --------------------------------------------------------------------------
# Codes vs labels, timestamps
# --------------------------------------------------------------------------


def test_status_is_a_code_with_a_separate_label(demo_item):
    """
    The whole point of emitting both: `status` is the contract, and
    renaming the Russian text in app/i18n.py must not break a consumer.
    """
    assert demo_item["status"] in PLATFORM_STATUSES
    assert demo_item["status_label"] == PLATFORM_STATUSES[demo_item["status"]]


def test_event_types_are_codes_with_labels(demo_item):
    assert demo_item["events"], "the demo item should have a stage history"
    for event in demo_item["events"]:
        assert event["event_type"] in PLATFORM_EVENT_TYPES
        assert event["event_type_label"] == PLATFORM_EVENT_TYPES[event["event_type"]]


def test_timestamps_are_machine_parseable(demo_item):
    """ISO-8601, not the "16.08.2026 21:30 МСК" strings the web UI renders."""
    datetime.fromisoformat(demo_item["updated_at"])
    for event in demo_item["events"]:
        datetime.fromisoformat(event["occurred_at"])


def test_part_category_group_is_a_code_with_a_label(demo_item):
    for component in demo_item["components_installed"]:
        assert component["part"]["category_group"] in {"custom", "purchased"}
        assert component["part"]["category_group_label"]


# --------------------------------------------------------------------------
# Search — the system's core workflow
# --------------------------------------------------------------------------


def test_search_resolves_a_serial_to_the_item_holding_it(client: TestClient, auth, demo_item):
    installed = demo_item["components_installed"]
    serial = next(c["part"]["serial_number"] for c in installed if c["part"]["serial_number"])

    response = client.get("/api/v1/search", params={"q": serial}, headers=auth)
    assert response.status_code == 200
    hits = [h for h in response.json()["parts"] if h["part"]["serial_number"] == serial]
    assert hits, f"search did not find {serial}"
    assert hits[0]["currently_installed_in"]["id"] == demo_item["id"]


def test_search_rejects_a_query_that_is_too_short(client: TestClient, auth):
    response = client.get("/api/v1/search", params={"q": "x"}, headers=auth)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


# --------------------------------------------------------------------------
# dry_run
# --------------------------------------------------------------------------


def test_dry_run_writes_nothing(client: TestClient, auth, demo_item):
    item_id = demo_item["id"]
    before = event_count(item_id)

    response = client.post(
        f"/api/v1/items/{item_id}/events",
        json={"event_type": "service", "notes": "dry run check", "dry_run": True},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["dry_run"] is True

    assert event_count(item_id) == before, "dry_run committed something"


def test_dry_run_reports_the_state_the_write_would_produce(client: TestClient, auth, demo_item):
    """
    The response describes the would-be outcome — that is what makes it
    useful as a check before committing, rather than just a validator.
    """
    item_id = demo_item["id"]
    before = len(demo_item["events"])

    response = client.post(
        f"/api/v1/items/{item_id}/events",
        json={"event_type": "service", "dry_run": True},
        headers=auth,
    )
    assert response.json()["item"]["events"].__len__() == before + 1
    assert event_count(item_id) == before  # ...and still nothing on disk


def test_dry_run_reports_failures_the_same_way_as_a_real_call(client: TestClient, auth, demo_item):
    """A dry run of an invalid action must fail, not report a hypothetical success."""
    response = client.post(
        f"/api/v1/items/{demo_item['id']}/events",
        json={"event_type": "no_such_stage", "dry_run": True},
        headers=auth,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_event_type"


def test_real_write_persists_and_returns_new_state(client: TestClient, auth, demo_item):
    item_id = demo_item["id"]
    before = event_count(item_id)

    response = client.post(
        f"/api/v1/items/{item_id}/events",
        json={"event_type": "service", "notes": "contract test"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is False
    assert body["item"]["events"][0]["event_type"] == "service"
    assert event_count(item_id) == before + 1


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


def test_viewer_token_cannot_write(client: TestClient, issue_token, demo_item):
    headers = {"Authorization": f"Bearer {issue_token(role='viewer')}"}
    response = client.post(
        f"/api/v1/items/{demo_item['id']}/events", json={"event_type": "service"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_viewer_token_does_not_see_commercial_fields(client: TestClient, issue_token, demo_item):
    """
    Same rule the templates enforce for the viewer role (AGENTS.md ->
    "Роли и доступ"), applied at the serialization boundary now that
    there is a JSON consumer.
    """
    assert demo_item["customer"], "the demo item should have a customer set for this to be meaningful"

    headers = {"Authorization": f"Bearer {issue_token(role='viewer')}"}
    response = client.get(f"/api/v1/items/{demo_item['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["customer"] is None


def test_deactivating_the_user_disables_its_tokens(client: TestClient, auth):
    from app.db import SessionLocal
    from app.models import User
    from tests.conftest import SERVICE_USERNAME

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == SERVICE_USERNAME).one()
        user.is_active = False
        db.commit()

        response = client.get("/api/v1/items", headers=auth)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "service_account_disabled"
    finally:
        user.is_active = True
        db.commit()
        db.close()


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def test_revoked_token_stops_working(client: TestClient, issue_token, api_token):
    """
    Revocation is the whole reason tokens are rows rather than a .env
    value. api_token is taken but never sent: it keeps another live token
    on the deployment, so the rejection below is "this token is revoked"
    and not "this deployment has no API", which is a different code.
    """
    from app.db import SessionLocal
    from app.models import ApiToken
    from app.services import api_tokens as tokens_service

    raw_token = issue_token()
    headers = {"Authorization": f"Bearer {raw_token}"}
    assert client.get("/api/v1/items", headers=headers).status_code == 200

    db = SessionLocal()
    try:
        token = db.scalar(
            select(ApiToken).where(ApiToken.token_hash == tokens_service.hash_token(raw_token))
        )
        tokens_service.revoke_token(db, actor=None, token=token)
    finally:
        db.close()

    response = client.get("/api/v1/items", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_revoking_one_token_leaves_the_others_working(client: TestClient, issue_token):
    """The property the shared .env token could not offer at all."""
    from app.db import SessionLocal
    from app.models import ApiToken
    from app.services import api_tokens as tokens_service

    doomed = issue_token()
    survivor = issue_token()

    db = SessionLocal()
    try:
        token = db.scalar(
            select(ApiToken).where(ApiToken.token_hash == tokens_service.hash_token(doomed))
        )
        tokens_service.revoke_token(db, actor=None, token=token)
    finally:
        db.close()

    assert client.get("/api/v1/items", headers={"Authorization": f"Bearer {doomed}"}).status_code == 401
    assert client.get("/api/v1/items", headers={"Authorization": f"Bearer {survivor}"}).status_code == 200


def test_the_users_role_caps_the_tokens_role(client: TestClient, auth, demo_item, service_role):
    """
    A token issued as 'engineer' must lose write access the moment the
    user it acts as is demoted — otherwise a token would be a way to keep
    rights its owner no longer has, and demoting someone would silently
    not take effect.
    """
    service_role("viewer")
    response = client.post(
        f"/api/v1/items/{demo_item['id']}/events", json={"event_type": "service"}, headers=auth
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_a_token_cannot_be_issued_above_its_users_role(service_role):
    """The same bound, refused at the point the mistake is made."""
    from app.db import SessionLocal
    from app.models import User
    from app.services import api_tokens as tokens_service
    from tests.conftest import SERVICE_USERNAME

    service_role("viewer")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == SERVICE_USERNAME).one()
        with pytest.raises(tokens_service.RoleExceedsUserError):
            tokens_service.create_token(
                db, actor=None, name="should not exist", user=user, role="admin"
            )
    finally:
        db.close()


def test_the_plaintext_token_is_not_stored(issue_token):
    """
    Only the hash goes to the database. If the raw string were ever
    persisted, a database dump would hand over every consumer's access.
    """
    from app.db import SessionLocal
    from app.models import ApiToken
    from app.services import api_tokens as tokens_service

    raw_token = issue_token()
    db = SessionLocal()
    try:
        stored = db.scalar(
            select(ApiToken).where(ApiToken.token_hash == tokens_service.hash_token(raw_token))
        )
        assert stored is not None, "the token should be findable by its hash"
        assert raw_token not in (stored.token_hash, stored.name)
        assert stored.token_prefix and raw_token.startswith(stored.token_prefix)
        assert len(stored.token_prefix) < len(raw_token), "the stored prefix must not be the whole token"
    finally:
        db.close()


def test_the_api_is_closed_when_no_token_has_been_issued(client: TestClient, issue_token):
    """
    Safe by default: a deployment that never issues a token has no API,
    and says so rather than looking like a wrong-password failure.
    """
    from app.db import SessionLocal
    from app.models import ApiToken
    from app.services import api_tokens as tokens_service

    raw_token = issue_token()  # revoked again by the fixture's teardown
    db = SessionLocal()
    try:
        for token in db.scalars(select(ApiToken).where(ApiToken.revoked_at.is_(None))).all():
            tokens_service.revoke_token(db, actor=None, token=token)
    finally:
        db.close()

    response = client.get("/api/v1/items", headers={"Authorization": f"Bearer {raw_token}"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "api_disabled"
