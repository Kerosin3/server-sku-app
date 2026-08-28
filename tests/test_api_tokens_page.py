"""
The admin page that issues and revokes API tokens (/api-tokens).

Kept separate from the contract tests: those pin promises made to a
machine consumer, these check the human-facing screen an admin actually
uses to hand a token out. Both matter, for different reasons — an agent
cannot call the API at all until someone has been through this page.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import SERVICE_USERNAME

ADMIN_PASSWORD = "test-admin-password"  # set by the seeded_database fixture


@pytest.fixture
def admin_client(seeded_database) -> TestClient:
    """A client with a logged-in admin session cookie."""
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, "admin login failed, the rest of this file is meaningless"
    return client


def _live_token_names(client: TestClient) -> set[str]:
    from app.db import SessionLocal
    from app.models import ApiToken

    db = SessionLocal()
    try:
        rows = db.scalars(select(ApiToken).where(ApiToken.revoked_at.is_(None))).all()
        return {row.name for row in rows}
    finally:
        db.close()


def test_page_renders(admin_client: TestClient):
    """Catches a broken template, which no API-level test would notice."""
    response = admin_client.get("/api-tokens")
    assert response.status_code == 200
    assert "Токены API" in response.text


def test_page_is_admin_only(client: TestClient):
    """No session at all: the router must not be reachable anonymously."""
    response = client.get("/api-tokens", follow_redirects=False)
    assert response.status_code in (302, 303, 401, 403)
    assert response.status_code != 200


def test_issuing_shows_the_token_exactly_once(admin_client: TestClient):
    """
    The plaintext appears on the page that follows creation and nowhere
    afterwards — reloading the list must not bring it back, because only
    the hash was kept.
    """
    name = "тест выпуска"
    response = admin_client.post(
        "/api-tokens",
        data={"name": name, "username": SERVICE_USERNAME, "role": "viewer"},
    )
    assert response.status_code == 200
    start = response.text.find("stk_")
    assert start != -1, "the new token should be displayed once, right after creation"
    raw_token = response.text[start:].split("<")[0].strip()

    listing = admin_client.get("/api-tokens")
    assert listing.status_code == 200
    assert raw_token not in listing.text, "the token must not survive a page reload"
    assert name in listing.text

    # ...and it is a working token, not just a string on a page.
    from app.main import app

    api = TestClient(app)
    assert api.get("/api/v1/items", headers={"Authorization": f"Bearer {raw_token}"}).status_code == 200

    _revoke_by_name(admin_client, name)


def test_a_second_live_token_cannot_reuse_a_name(admin_client: TestClient):
    """Two live tokens called the same thing would make the revoke button a guess."""
    name = "тест дубликата"
    first = admin_client.post(
        "/api-tokens", data={"name": name, "username": SERVICE_USERNAME, "role": "viewer"}
    )
    assert first.status_code == 200

    second = admin_client.post(
        "/api-tokens", data={"name": name, "username": SERVICE_USERNAME, "role": "viewer"}
    )
    assert second.status_code == 409
    assert "уже есть" in second.text

    _revoke_by_name(admin_client, name)
    assert name not in _live_token_names(admin_client)

    # Revoked frees the name again — that is how a token is rotated.
    again = admin_client.post(
        "/api-tokens", data={"name": name, "username": SERVICE_USERNAME, "role": "viewer"}
    )
    assert again.status_code == 200
    _revoke_by_name(admin_client, name)


def test_the_form_refuses_a_role_above_the_users_role(admin_client: TestClient, service_role):
    service_role("viewer")
    response = admin_client.post(
        "/api-tokens", data={"name": "тест потолка", "username": SERVICE_USERNAME, "role": "admin"},
    )
    assert response.status_code == 400
    assert "выше" in response.text
    assert "тест потолка" not in _live_token_names(admin_client)


def _revoke_by_name(client: TestClient, name: str) -> None:
    from app.db import SessionLocal
    from app.models import ApiToken

    db = SessionLocal()
    try:
        token = db.scalar(select(ApiToken).where(ApiToken.name == name, ApiToken.revoked_at.is_(None)))
    finally:
        db.close()
    if token is not None:
        assert client.post(f"/api-tokens/{token.id}/revoke", follow_redirects=False).status_code == 303
