"""
Fixtures for the API contract tests.

There is deliberately no mock server here. A hand-written mock would be
a second implementation of the same contract, and the two drift — the
failure mode being an agent that works perfectly against the mock and
breaks against the real API. Instead these tests drive the *real*
application against a throwaway database seeded with the demo example
the app already knows how to create (app/services/demo_seed.py), so
fidelity is free and there is nothing to keep in sync.

The API token is issued the same way a human would issue one, through
app/services/api_tokens.py, rather than injected through configuration.
That keeps the tests honest about how access is actually granted, and it
means the issuing path itself is exercised on every run.

scripts/test-api.sh owns the database: it creates a scratch one, points
DATABASE_URL at it, runs the migrations, and drops it afterwards. By the
time pytest imports the app, DATABASE_URL is already set — which matters,
because app/db.py binds its engine at import time.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

SERVICE_USERNAME = "api"


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    """
    First-ever admin creation also seeds the demo platform/variant/item
    (see app/services/setup.py), which is what gives these tests a fully
    worked-through fixture without a fixtures file of their own.
    """
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User
    from app.services import setup as setup_service

    db = SessionLocal()
    try:
        if setup_service.needs_setup(db):
            setup_service.create_first_admin(
                db,
                username="admin",
                password="test-admin-password",
                security_question="test",
                security_answer="test",
            )
        if db.query(User).filter(User.username == SERVICE_USERNAME).first() is None:
            # No usable password: this account exists to give API tokens an
            # identity and a role ceiling, not to log in through the web form.
            db.add(
                User(
                    username=SERVICE_USERNAME,
                    password_hash=hash_password("not-a-login-account"),
                    role="engineer",
                )
            )
            db.commit()
    finally:
        db.close()


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture
def issue_token(seeded_database):
    """
    Issue a token and revoke it when the test ends, so no test leaves a
    live one behind for the next. Names are unique per issue because
    api_tokens holds a partial unique index on the names of live tokens.
    """
    from app.db import SessionLocal
    from app.models import User
    from app.services import api_tokens as tokens_service

    issued = []

    def issue(role: str = "engineer", username: str = SERVICE_USERNAME) -> str:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).one()
            token, raw_token = tokens_service.create_token(
                db,
                actor=None,
                name=f"contract test {uuid4().hex[:8]}",
                user=user,
                role=role,
            )
            issued.append(token.id)
            return raw_token
        finally:
            db.close()

    yield issue

    db = SessionLocal()
    try:
        from app.models import ApiToken

        for token_id in issued:
            token = db.get(ApiToken, token_id)
            if token is not None:
                tokens_service.revoke_token(db, actor=None, token=token)
    finally:
        db.close()


@pytest.fixture
def api_token(issue_token) -> str:
    return issue_token()


@pytest.fixture
def auth(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def service_role():
    """
    Temporarily change the role of the user API tokens act as, then put
    it back. Used to check that the user's role caps the token's — a
    token can never be a way to hold rights its owner has lost.
    """
    from app.db import SessionLocal
    from app.models import User

    def set_role(role: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == SERVICE_USERNAME).one()
            user.role = role
            db.commit()
        finally:
            db.close()

    yield set_role
    set_role("engineer")


@pytest.fixture
def demo_variant_id(client: TestClient, auth: dict[str, str]) -> int:
    """The seeded demo configuration — a ready-made BOM to hang test items on."""
    platforms = client.get("/api/v1/platforms", headers=auth).json()
    return platforms[0]["variants"][0]["id"]


@pytest.fixture
def demo_item(client: TestClient, auth: dict[str, str]) -> dict:
    """The seeded DEMO-0001 unit, fully populated — components, firmware, MACs, stages."""
    response = client.get("/api/v1/items", params={"limit": 1}, headers=auth)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "demo seed did not create an item"
    detail = client.get(f"/api/v1/items/{items[0]['id']}", headers=auth)
    assert detail.status_code == 200, detail.text
    return detail.json()


def event_count(item_id: int) -> int:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import PlatformEvent

    db = SessionLocal()
    try:
        return db.scalar(
            select(func.count()).select_from(PlatformEvent).where(PlatformEvent.platform_item_id == item_id)
        )
    finally:
        db.close()
