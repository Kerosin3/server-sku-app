"""
Domain tests for the stage log (app/services/platform_events.py).

Written against the service rather than the API on purpose: this is a
rule about the process, not about an endpoint, and it has to hold for
the web interface and the JSON API alike because both go through this
one function. Testing it here means the test does not have to be
repeated per interface, and it cannot pass because of something an API
layer happens to do.

The heart of the file is test_a_rebuilt_unit_needs_a_new_test_before_shipping.
Everything else is the surrounding ordering that has to keep working
while that one holds.
"""
from uuid import uuid4

import pytest

from app.db import SessionLocal
from app.models import PlatformVariant, User
from app.services import platform_events as events_service
from app.services import platform_items as items_service


@pytest.fixture
def db(seeded_database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def actor(db) -> User:
    return db.query(User).filter_by(username="admin").one()


@pytest.fixture
def item(db, actor):
    """A fresh unit, so no test leans on the history another one left."""
    variant_id = db.query(PlatformVariant.id).order_by(PlatformVariant.id).limit(1).scalar()
    return items_service.create_item(
        db,
        actor=actor,
        platform_variant_id=variant_id,
        asset_tag=f"STAGE-{uuid4().hex[:8]}",
        customer=None,
        location=None,
        notes=None,
    )


def record(db, actor, item, event_type: str, notes: str | None = None):
    return events_service.record_event(
        db, actor=actor, item=item, event_type=event_type, notes=notes
    )


def build_and_ship(db, actor, item) -> None:
    for stage in ("assembled", "test_started", "test_passed", "shipped"):
        record(db, actor, item, stage)


# --------------------------------------------------------------------------
# The rule this file exists for
# --------------------------------------------------------------------------


def test_a_rebuilt_unit_needs_a_new_test_before_shipping(db, actor, item):
    """
    A unit comes back from the field, is taken apart and rebuilt — with
    different parts in it. Its original test_passed describes the machine
    it used to be, and must not be enough to ship the machine it is now.

    This was the bug: prerequisites asked "did this ever happen", so a
    repaired unit shipped again with no one testing it.
    """
    build_and_ship(db, actor, item)
    record(db, actor, item, "disassembled")
    record(db, actor, item, "assembled")

    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "shipped")

    # ...and it ships once it has actually been tested again.
    record(db, actor, item, "test_started")
    record(db, actor, item, "test_passed")
    record(db, actor, item, "shipped")
    assert item.status == "shipped"


def test_a_rebuilt_unit_needs_a_new_assembly_before_testing(db, actor, item):
    record(db, actor, item, "assembled")
    record(db, actor, item, "disassembled")

    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "test_started")


def test_a_unit_cannot_be_taken_apart_twice_running(db, actor, item):
    record(db, actor, item, "assembled")
    record(db, actor, item, "disassembled")

    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "disassembled")


def test_the_previous_cycle_stays_in_the_log(db, actor, item):
    """
    Resetting the prerequisites must not erase anything: platform_events
    is append-only, and "what did this unit go through" has to survive a
    rebuild. The rule changes what counts, not what is kept.
    """
    build_and_ship(db, actor, item)
    record(db, actor, item, "disassembled")

    history = [e.event_type for e in events_service.list_events(db, item)]
    assert history.count("assembled") == 1
    assert "test_passed" in history and "shipped" in history
    assert len(history) == 5


# --------------------------------------------------------------------------
# The ordering that has to keep working
# --------------------------------------------------------------------------


def test_the_normal_flow_runs_through(db, actor, item):
    build_and_ship(db, actor, item)
    assert item.status == "shipped"
    assert [e.event_type for e in events_service.list_events(db, item)][-1] == "assembled"


def test_cannot_test_what_was_never_assembled(db, actor, item):
    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "test_started")


def test_cannot_ship_without_a_passed_test(db, actor, item):
    record(db, actor, item, "assembled")
    record(db, actor, item, "test_started")

    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "shipped")


def test_a_failed_test_does_not_allow_shipping(db, actor, item):
    record(db, actor, item, "assembled")
    record(db, actor, item, "test_started")
    record(db, actor, item, "test_failed")

    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "shipped")


def test_passing_with_remarks_allows_shipping(db, actor, item):
    """A known defect is still a pass — it ships, and the log says why."""
    record(db, actor, item, "assembled")
    record(db, actor, item, "test_started")
    record(db, actor, item, "test_passed_with_remarks", notes="царапина на крышке")
    record(db, actor, item, "shipped")
    assert item.status == "shipped"


def test_remarks_are_not_optional(db, actor, item):
    record(db, actor, item, "assembled")
    record(db, actor, item, "test_started")

    with pytest.raises(events_service.RemarksRequiredError):
        record(db, actor, item, "test_passed_with_remarks")


def test_service_needs_a_shipped_unit(db, actor, item):
    record(db, actor, item, "assembled")

    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, item, "service")

    record(db, actor, item, "test_started")
    record(db, actor, item, "test_passed")
    record(db, actor, item, "shipped")
    record(db, actor, item, "service")


def test_an_unknown_stage_is_rejected(db, actor, item):
    with pytest.raises(events_service.InvalidEventTypeError):
        record(db, actor, item, "покрашено")


def test_stages_of_one_unit_do_not_satisfy_another(db, actor, item, actor2=None):
    """The cycle is per item; a neighbour's history must not leak in."""
    build_and_ship(db, actor, item)

    other = items_service.create_item(
        db,
        actor=actor,
        platform_variant_id=item.platform_variant_id,
        asset_tag=f"STAGE-{uuid4().hex[:8]}",
        customer=None,
        location=None,
        notes=None,
    )
    with pytest.raises(events_service.PrerequisiteNotMetError):
        record(db, actor, other, "test_started")
