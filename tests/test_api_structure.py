"""
Contract tests for the calls that build structure and manage an item's
whole life: platform, configuration, BOM, then a unit built to it.

The centrepiece is test_a_configuration_can_be_built_from_nothing — the
one test that proves the claim this part of the API exists to make, that
an agent can go from an empty system to a finished, fully specified unit
without a human opening the web interface. If that ever stops passing,
the API no longer does what it was extended to do, whatever the smaller
tests say.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import SERVICE_USERNAME


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _random_mac() -> str:
    return ":".join(f"{b:02X}" for b in (0x02, *(int(uuid4().hex[i : i + 2], 16) for i in range(0, 10, 2))))


@pytest.fixture
def fresh_item(client: TestClient, auth, demo_variant_id) -> dict:
    """A new, empty unit under the seeded demo configuration."""
    response = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": _unique("TEST")},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()["item"]


# --------------------------------------------------------------------------
# The whole point
# --------------------------------------------------------------------------


def test_a_configuration_can_be_built_from_nothing(client: TestClient, auth):
    """
    Platform -> configuration -> catalog -> BOM -> unit -> component ->
    firmware -> MAC -> stages -> shipped, entirely through the API.

    Also checks the completeness checklist actually goes green, which is
    what makes this a build rather than a sequence of accepted calls.
    """
    def post(path: str, payload: dict) -> dict:
        response = client.post(f"/api/v1{path}", json=payload, headers=auth)
        assert response.status_code == 200, f"{path} -> {response.status_code} {response.text}"
        return response.json()

    platform = post("/platforms", {"name": _unique("Платформа"), "description": "из теста"})["platform"]

    variant = post(f"/platforms/{platform['id']}/variants", {"name": "Базовое исполнение"})["variant"]
    variant_id = variant["id"]
    assert variant["slots"] == [], "a new configuration starts with an empty BOM"

    category = post("/part-categories", {"name": _unique("Плата"), "group": "custom"})["part_category"]
    firmware_type = post("/firmware-types", {"name": _unique("BIOS")})["firmware_type"]

    variant = post(
        f"/variants/{variant_id}/slots",
        {"slot_name": "Материнская плата", "part_category_id": category["id"], "quantity": 1},
    )["variant"]
    slot_id = variant["slots"][0]["id"]

    post(
        f"/variants/{variant_id}/firmware-requirements",
        {"firmware_type_id": firmware_type["id"], "track_backup": False},
    )
    variant = post(f"/variants/{variant_id}/mac-requirements", {"label": "BMC", "required": True})["variant"]
    assert len(variant["firmware_requirements"]) == 1
    assert len(variant["mac_requirements"]) == 1

    item = post(
        "/items",
        {"platform_variant_id": variant_id, "asset_tag": _unique("SRV"), "customer": "ООО Тест"},
    )["item"]
    item_id = item["id"]
    assert item["checklist"][0]["complete"] is False, "an empty unit is not complete"

    serial = _unique("SN")
    item = post(
        f"/items/{item_id}/components",
        {"platform_variant_slot_id": slot_id, "serial_number": serial, "article": "СКЮ-ТЕСТ"},
    )["item"]
    part_unit_id = item["components_installed"][0]["part"]["part_unit_id"]

    post(
        f"/items/{item_id}/firmware",
        {"part_unit_id": part_unit_id, "firmware_type_id": firmware_type["id"], "version": "1.0.0"},
    )
    item = post(f"/items/{item_id}/mac", {"mac_address": _random_mac(), "label": "BMC"})["item"]

    assert all(row["complete"] for row in item["checklist"]), "every BOM line should be filled"
    assert all(row["satisfied"] for row in item["firmware"]), "firmware should be recorded"
    assert all(row["satisfied"] for row in item["mac_addresses"]), "the BMC address should be registered"

    for stage in ("assembled", "test_started", "test_passed", "shipped"):
        item = post(f"/items/{item_id}/events", {"event_type": stage})["item"]

    assert item["status"] == "shipped"
    assert [e["event_type"] for e in item["events"]][:4] == [
        "shipped",
        "test_passed",
        "test_started",
        "assembled",
    ], "history is newest-first"


# --------------------------------------------------------------------------
# dry_run reaches the new writes too
# --------------------------------------------------------------------------


def test_dry_run_on_a_structure_write_creates_nothing(client: TestClient, auth):
    name = _unique("Платформа")
    response = client.post("/api/v1/platforms", json={"name": name, "dry_run": True}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is True
    assert response.json()["platform"]["name"] == name

    listed = {p["name"] for p in client.get("/api/v1/platforms", headers=auth).json()}
    assert name not in listed, "dry_run committed a platform"


def test_dry_run_on_item_creation_creates_nothing(client: TestClient, auth, demo_variant_id):
    asset_tag = _unique("DRY")
    response = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": asset_tag, "dry_run": True},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["item"]["asset_tag"] == asset_tag

    found = client.get("/api/v1/search", params={"q": asset_tag}, headers=auth).json()
    assert found["items"] == [], "dry_run committed an item"


# --------------------------------------------------------------------------
# PATCH semantics — omitted vs explicit null
# --------------------------------------------------------------------------


def test_patch_leaves_omitted_fields_alone(client: TestClient, auth, fresh_item):
    item_id = fresh_item["id"]
    client.patch(
        f"/api/v1/items/{item_id}",
        json={"customer": "ООО Первый", "location": "Стойка A1"},
        headers=auth,
    )

    response = client.patch(f"/api/v1/items/{item_id}", json={"location": "Стойка B2"}, headers=auth)
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["location"] == "Стойка B2"
    assert item["customer"] == "ООО Первый", "an omitted field must not be wiped"


def test_patch_clears_a_field_when_given_an_explicit_null(client: TestClient, auth, fresh_item):
    item_id = fresh_item["id"]
    client.patch(f"/api/v1/items/{item_id}", json={"customer": "ООО Второй"}, headers=auth)

    response = client.patch(f"/api/v1/items/{item_id}", json={"customer": None}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["item"]["customer"] is None


def test_patch_cannot_change_the_asset_tag(client: TestClient, auth, fresh_item):
    """
    Not a validation message but a fact about the schema: the field does
    not exist, so an agent that tries gets a 422 rather than a silent
    no-op it might mistake for success.
    """
    response = client.patch(
        f"/api/v1/items/{fresh_item['id']}", json={"asset_tag": "ДРУГОЙ"}, headers=auth
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


# --------------------------------------------------------------------------
# Removing a component
# --------------------------------------------------------------------------


def _install(client: TestClient, auth, item_id: int, slot_id: int) -> dict:
    response = client.post(
        f"/api/v1/items/{item_id}/components",
        json={
            "platform_variant_slot_id": slot_id,
            "serial_number": _unique("SN"),
            "article": "СКЮ-ТЕСТ",
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()["item"]


def test_removing_a_component_keeps_it_in_the_history(client: TestClient, auth, fresh_item, demo_variant_id):
    """
    platform_components is append-only: removal records that the part
    left, it does not erase that the part was ever installed. Losing that
    would break exactly the question this system exists to answer.
    """
    item_id = fresh_item["id"]
    slot_id = client.get(f"/api/v1/variants/{demo_variant_id}", headers=auth).json()["slots"][0]["id"]
    item = _install(client, auth, item_id, slot_id)
    component = item["components_installed"][0]

    response = client.post(
        f"/api/v1/items/{item_id}/components/{component['id']}/remove", json={}, headers=auth
    )
    assert response.status_code == 200, response.text
    item = response.json()["item"]

    assert component["id"] not in [c["id"] for c in item["components_installed"]]
    removed = [c for c in item["components_removed"] if c["id"] == component["id"]]
    assert removed, "the component must stay in the record as removed"
    assert removed[0]["removed_at"] is not None
    assert removed[0]["part"]["serial_number"] == component["part"]["serial_number"]


def test_a_removed_part_can_be_installed_elsewhere(client: TestClient, auth, demo_variant_id):
    """Removal returns the part to stock; otherwise it would be stranded."""
    slot_id = client.get(f"/api/v1/variants/{demo_variant_id}", headers=auth).json()["slots"][0]["id"]

    def new_item() -> int:
        response = client.post(
            "/api/v1/items",
            json={"platform_variant_id": demo_variant_id, "asset_tag": _unique("MOVE")},
            headers=auth,
        )
        return response.json()["item"]["id"]

    source, target = new_item(), new_item()
    item = _install(client, auth, source, slot_id)
    component = item["components_installed"][0]
    serial = component["part"]["serial_number"]

    client.post(f"/api/v1/items/{source}/components/{component['id']}/remove", json={}, headers=auth)

    response = client.post(
        f"/api/v1/items/{target}/components",
        json={"platform_variant_slot_id": slot_id, "serial_number": serial},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["item"]["components_installed"][0]["part"]["serial_number"] == serial


def test_removal_is_blocked_while_the_item_is_assembled(client: TestClient, auth, fresh_item, demo_variant_id):
    """Same lock as installing — the component list is frozen, both directions."""
    item_id = fresh_item["id"]
    slot_id = client.get(f"/api/v1/variants/{demo_variant_id}", headers=auth).json()["slots"][0]["id"]
    component = _install(client, auth, item_id, slot_id)["components_installed"][0]

    client.post(f"/api/v1/items/{item_id}/events", json={"event_type": "assembled"}, headers=auth)

    response = client.post(
        f"/api/v1/items/{item_id}/components/{component['id']}/remove", json={}, headers=auth
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "components_locked"


# --------------------------------------------------------------------------
# Error codes for the new calls
# --------------------------------------------------------------------------


def test_duplicate_platform_name_is_rejected(client: TestClient, auth):
    name = _unique("Платформа")
    assert client.post("/api/v1/platforms", json={"name": name}, headers=auth).status_code == 200

    response = client.post("/api/v1/platforms", json={"name": name}, headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_name_taken"


def test_duplicate_asset_tag_is_rejected(client: TestClient, auth, fresh_item, demo_variant_id):
    response = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": fresh_item["asset_tag"]},
        headers=auth,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "asset_tag_taken"


def test_item_under_a_nonexistent_configuration_is_rejected(client: TestClient, auth):
    response = client.post(
        "/api/v1/items", json={"platform_variant_id": 999999, "asset_tag": _unique("X")}, headers=auth
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "variant_not_found"


def test_bom_line_with_an_unknown_category_is_rejected(client: TestClient, auth, demo_variant_id):
    response = client.post(
        f"/api/v1/variants/{demo_variant_id}/slots",
        json={"slot_name": _unique("Позиция"), "part_category_id": 999999},
        headers=auth,
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "part_category_not_found"
    assert "part-categories" in error["hint"], "the hint should name the call that lists valid ids"


def test_invalid_category_group_is_rejected(client: TestClient, auth):
    response = client.post(
        "/api/v1/part-categories", json={"name": _unique("Что-то"), "group": "неизвестно"}, headers=auth
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_category_group"


# --------------------------------------------------------------------------
# Roles and audit
# --------------------------------------------------------------------------


def test_viewer_cannot_create_structure(client: TestClient, issue_token):
    headers = {"Authorization": f"Bearer {issue_token(role='viewer')}"}
    response = client.post("/api/v1/platforms", json={"name": _unique("Платформа")}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_catalogs_are_readable_by_a_viewer(client: TestClient, issue_token):
    headers = {"Authorization": f"Bearer {issue_token(role='viewer')}"}
    for path in ("/api/v1/part-categories", "/api/v1/firmware-types"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, path
        assert isinstance(response.json(), list)


def test_structure_created_through_the_api_has_an_author_in_the_audit_log(client: TestClient, auth):
    """
    The gap that had to be closed before opening these calls up: these
    services used to write without an actor, so a platform created by an
    agent would have appeared in the log with no author — or not at all.
    """
    from app.db import SessionLocal
    from app.models import AuditLog, User

    name = _unique("Платформа")
    platform = client.post("/api/v1/platforms", json={"name": name}, headers=auth).json()["platform"]

    db = SessionLocal()
    try:
        row = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "platform", AuditLog.entity_id == platform["id"]
            )
        )
        assert row is not None, "creating a platform must leave an audit row"
        assert row.action == "create"
        assert row.diff["name"] == name

        author = db.get(User, row.user_id)
        assert author is not None and author.username == SERVICE_USERNAME
    finally:
        db.close()


def test_bom_changes_are_audited_under_their_full_entity_name(client: TestClient, auth, demo_variant_id):
    """
    entity_type holds the singular of the table, and the longest of those
    is 37 characters — which is why migration 0003 widened the column.
    A silent truncation here would make the log unjoinable to the schema.
    """
    from app.db import SessionLocal
    from app.models import AuditLog, FirmwareType

    db = SessionLocal()
    try:
        firmware_type_id = db.scalar(select(FirmwareType.id).where(FirmwareType.platform_variant_id.is_(None)))
    finally:
        db.close()

    variant = client.post(
        f"/api/v1/platforms/{client.get('/api/v1/platforms', headers=auth).json()[0]['id']}/variants",
        json={"name": _unique("Исполнение")},
        headers=auth,
    ).json()["variant"]

    response = client.post(
        f"/api/v1/variants/{variant['id']}/firmware-requirements",
        json={"firmware_type_id": firmware_type_id, "track_backup": True},
        headers=auth,
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        row = db.scalar(
            select(AuditLog)
            .where(AuditLog.entity_type == "platform_variant_firmware_requirement")
            .order_by(AuditLog.id.desc())
        )
        assert row is not None, "the entity type must be stored whole, not truncated to fit"
        assert row.diff["platform_variant_id"] == variant["id"]
    finally:
        db.close()
