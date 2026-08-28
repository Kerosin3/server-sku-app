"""
Contract tests for the destructive calls.

These get their own file because they are the only ones that can lose
data, and because what has to be proven about them is different: not
"does it work" but "does it refuse when it should, and does it really
change nothing when asked not to". A dry run that half-happens is worse
than no dry run at all — the caller is told nothing occurred.
"""
from io import BytesIO
from uuid import uuid4

from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import SERVICE_USERNAME


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


# --------------------------------------------------------------------------
# Deleting works, and is audited
# --------------------------------------------------------------------------


def test_an_empty_platform_can_be_deleted(client: TestClient, auth, issue_token, service_role):
    service_role("admin")
    headers = {"Authorization": f"Bearer {issue_token(role='admin')}"}

    name = _unique("Платформа")
    platform = client.post("/api/v1/platforms", json={"name": name}, headers=auth).json()["platform"]

    response = client.delete(f"/api/v1/platforms/{platform['id']}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is False
    assert name in response.json()["detail"]

    assert name not in {p["name"] for p in client.get("/api/v1/platforms", headers=auth).json()}


def test_deletion_is_recorded_in_the_audit_log(client: TestClient, auth, issue_token, service_role):
    """
    After the row is gone the log is the only place the platform still
    exists, which is exactly why the entry has to be written before the
    delete and has to carry the name.
    """
    from app.db import SessionLocal
    from app.models import AuditLog

    service_role("admin")
    headers = {"Authorization": f"Bearer {issue_token(role='admin')}"}

    name = _unique("Платформа")
    platform = client.post("/api/v1/platforms", json={"name": name}, headers=auth).json()["platform"]
    client.delete(f"/api/v1/platforms/{platform['id']}", headers=headers)

    db = SessionLocal()
    try:
        row = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "platform",
                AuditLog.entity_id == platform["id"],
                AuditLog.action == "delete",
            )
        )
        assert row is not None, "a deletion with no audit entry is unrecoverable history"
        assert row.diff["name"] == name
        assert row.user_id is not None, "the deletion must have an author"
    finally:
        db.close()


def test_an_item_can_be_deleted_before_it_ships(client: TestClient, auth, demo_variant_id):
    asset_tag = _unique("DEL")
    item = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": asset_tag},
        headers=auth,
    ).json()["item"]

    response = client.delete(f"/api/v1/items/{item['id']}", headers=auth)
    assert response.status_code == 200, response.text

    assert client.get(f"/api/v1/items/{item['id']}", headers=auth).status_code == 404


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_a_shipped_item_cannot_be_deleted(client: TestClient, auth, demo_variant_id):
    """Delivered-product history is not a mistake to be cleaned up."""
    item = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": _unique("SHIP")},
        headers=auth,
    ).json()["item"]

    for stage in ("assembled", "test_started", "test_passed", "shipped"):
        assert (
            client.post(
                f"/api/v1/items/{item['id']}/events", json={"event_type": stage}, headers=auth
            ).status_code
            == 200
        )

    response = client.delete(f"/api/v1/items/{item['id']}", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "item_shipped"

    assert client.get(f"/api/v1/items/{item['id']}", headers=auth).status_code == 200


def test_a_platform_with_configurations_cannot_be_deleted(
    client: TestClient, auth, issue_token, service_role
):
    service_role("admin")
    headers = {"Authorization": f"Bearer {issue_token(role='admin')}"}

    platform = client.post(
        "/api/v1/platforms", json={"name": _unique("Платформа")}, headers=auth
    ).json()["platform"]
    client.post(
        f"/api/v1/platforms/{platform['id']}/variants", json={"name": "Исполнение"}, headers=auth
    )

    response = client.delete(f"/api/v1/platforms/{platform['id']}", headers=headers)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "platform_in_use"
    assert "variants" in error["hint"], "the hint should name the call that clears the way"


def test_a_configuration_with_items_cannot_be_deleted(
    client: TestClient, auth, demo_variant_id, issue_token, service_role
):
    """The demo configuration has an item built to it, so it is protected."""
    service_role("admin")
    headers = {"Authorization": f"Bearer {issue_token(role='admin')}"}

    response = client.delete(f"/api/v1/variants/{demo_variant_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "variant_in_use"


def test_a_category_in_use_cannot_be_deleted(client: TestClient, auth, demo_variant_id):
    """Every demo category is referenced by a BOM line."""
    categories = client.get(
        "/api/v1/part-categories", params={"variant_id": demo_variant_id}, headers=auth
    ).json()
    slots = client.get(f"/api/v1/variants/{demo_variant_id}", headers=auth).json()["slots"]
    used = {s["category"] for s in slots}
    category = next(c for c in categories if c["name"] in used)

    response = client.delete(f"/api/v1/part-categories/{category['id']}", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "part_category_in_use"


def test_deleting_something_that_does_not_exist_is_a_clean_404(client: TestClient, auth):
    response = client.delete("/api/v1/items/999999", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --------------------------------------------------------------------------
# dry_run on a destructive call
# --------------------------------------------------------------------------


def test_dry_run_delete_changes_nothing(client: TestClient, auth, demo_variant_id):
    asset_tag = _unique("KEEP")
    item = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": asset_tag},
        headers=auth,
    ).json()["item"]

    response = client.delete(f"/api/v1/items/{item['id']}?dry_run=true", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is True
    assert asset_tag in response.json()["detail"]

    assert client.get(f"/api/v1/items/{item['id']}", headers=auth).status_code == 200, (
        "dry_run deleted the item"
    )


def test_dry_run_delete_reports_a_refusal_rather_than_a_hypothetical_success(
    client: TestClient, auth, demo_variant_id
):
    """
    The point of dry-running a delete is to find out whether it is
    allowed. Reporting "ok" for something that would be refused would
    make it useless — and worse than useless to an agent that trusts it.
    """
    item = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": _unique("SHIP")},
        headers=auth,
    ).json()["item"]
    for stage in ("assembled", "test_started", "test_passed", "shipped"):
        client.post(f"/api/v1/items/{item['id']}/events", json={"event_type": stage}, headers=auth)

    response = client.delete(f"/api/v1/items/{item['id']}?dry_run=true", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "item_shipped"


def test_dry_run_delete_leaves_attachments_on_disk(client: TestClient, auth, demo_variant_id):
    """
    The filesystem is not covered by the transaction that gets rolled
    back, so the services take unlink_files=False on a dry run. Without
    it, "nothing was written" would still have destroyed the files —
    the one way a dry run could do real damage.
    """
    from app.db import SessionLocal
    from app.models import Attachment, PlatformItem, User
    from app.services import attachments as attachments_service

    db = SessionLocal()
    try:
        item = PlatformItem(platform_variant_id=demo_variant_id, asset_tag=_unique("FILE"))
        db.add(item)
        db.commit()
        item_id = item.id
        uploader = db.query(User).filter(User.username == SERVICE_USERNAME).one()
        attachment = attachments_service.save_file(
            db,
            actor=uploader,
            upload=UploadFile(file=BytesIO(b"test attachment"), filename="заметка.txt"),
            platform_item_id=item_id,
        )
        path = attachments_service.file_path(attachment)
        attachment_id = attachment.id
    finally:
        db.close()

    assert path.exists(), "the fixture file should have been written"

    response = client.delete(f"/api/v1/items/{item_id}?dry_run=true", headers=auth)
    assert response.status_code == 200, response.text
    assert path.exists(), "dry_run unlinked a file it promised not to touch"

    db = SessionLocal()
    try:
        assert db.get(Attachment, attachment_id) is not None, "dry_run removed the attachment row"
    finally:
        db.close()

    # ...and a real delete does remove it, so the flag is not just disabling the feature.
    assert client.delete(f"/api/v1/items/{item_id}", headers=auth).status_code == 200
    assert not path.exists(), "a real delete should remove the file"


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


def test_engineer_cannot_delete_a_platform(client: TestClient, auth):
    """Platforms and configurations are admin-only, matching the web interface."""
    platform = client.post(
        "/api/v1/platforms", json={"name": _unique("Платформа")}, headers=auth
    ).json()["platform"]

    response = client.delete(f"/api/v1/platforms/{platform['id']}", headers=auth)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_viewer_cannot_delete_anything(client: TestClient, auth, issue_token, demo_variant_id):
    item = client.post(
        "/api/v1/items",
        json={"platform_variant_id": demo_variant_id, "asset_tag": _unique("VIEW")},
        headers=auth,
    ).json()["item"]

    headers = {"Authorization": f"Bearer {issue_token(role='viewer')}"}
    response = client.delete(f"/api/v1/items/{item['id']}", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"
