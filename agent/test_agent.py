"""
Tests for the parts of the agent that are not the model.

The loop's guards are the risky code here — they decide whether a write
happens, whether a refusal sticks, and whether a confused model spins
against the tracker. All of that is deterministic and testable with a
scripted fake model, no LLM and no server involved, which is the only
way these can run fast enough to be worth running.

What is deliberately not tested: whether the model picks the right tool.
That is not a property of this code, it changes with the model, and
demo.py plus a real conversation is the honest way to check it.
"""
import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage

import chat
import server_tracker_tools as tools


# --------------------------------------------------------------------------
# The response contract
# --------------------------------------------------------------------------


def test_success_has_data_and_no_errors_line():
    result = tools.format_result("Поиск", {"ok": True, "data": {"items": []}})
    assert result.startswith("Status: success\nAction: Поиск\nData: ")
    assert "Errors:" not in result, "an empty Errors line is noise on every single step"
    assert not tools.is_error(result)


def test_error_has_errors_and_no_data_line():
    result = tools.format_result(
        "Этап «нет-такого»",
        {"ok": False, "code": "invalid_event_type", "message": "Unknown.", "hint": "Use one of: ..."},
    )
    assert result.startswith("Status: error")
    assert "Data:" not in result
    assert "invalid_event_type: Unknown." in result
    assert "Use one of" in result, "the hint is what lets the model correct itself"
    assert tools.is_error(result)


def test_russian_is_readable_not_escaped():
    """Escaped \\uXXXX would be unreadable to a human and twice the tokens."""
    result = tools.format_result("Поиск", {"ok": True, "data": {"label": "Укомплектовано"}})
    assert "Укомплектовано" in result
    assert "\\u" not in result


def test_summary_names_the_error_code():
    result = tools.format_result("x", {"ok": False, "code": "not_found", "message": "m", "hint": "h"})
    assert tools.summary(result) == "error — not_found"
    assert tools.summary(tools.format_result("x", {"ok": True, "data": 1})) == "success"


# --------------------------------------------------------------------------
# The HTTP wrapper
# --------------------------------------------------------------------------


def test_missing_token_never_reaches_the_network(monkeypatch):
    monkeypatch.setattr(tools, "TOKEN", "")
    monkeypatch.setattr(
        tools.httpx, "request", lambda *a, **k: pytest.fail("should not have been called")
    )
    assert tools.call_api("GET", "/items")["code"] == "no_token_configured"


def test_transport_failure_is_data_not_an_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise tools.httpx.ConnectError("refused")

    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(tools.httpx, "request", boom)

    result = tools.call_api("GET", "/items")
    assert result["ok"] is False
    assert result["code"] == "transport_error"
    assert result["status"] is None, "nothing was answered, so there is no status to report"


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_api_error_envelope_is_passed_through(monkeypatch):
    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(
        tools.httpx,
        "request",
        lambda *a, **k: _Response(409, {"error": {"code": "components_locked", "message": "m", "hint": "h"}}),
    )
    result = tools.call_api("POST", "/items/1/components")
    assert (result["ok"], result["status"], result["code"], result["hint"]) == (
        False,
        409,
        "components_locked",
        "h",
    )


def test_a_reply_that_is_not_ours_is_reported_as_such(monkeypatch):
    """A proxy or a wrong URL answers something that follows no contract."""
    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(tools.httpx, "request", lambda *a, **k: _Response(502, None, "<html>gateway</html>"))
    assert tools.call_api("GET", "/items")["code"] == "unexpected_response"


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


class FakeModel:
    """Replays a script of replies, so a turn is deterministic."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self.replies.pop(0) if self.replies else AIMessage("(сценарий кончился)")


def _tool_call(name, args, call_id="1"):
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _run(model, monkeypatch=None):
    return chat.run_turn(model, [SystemMessage("system")], verbose=False)


def test_a_plain_answer_comes_back_as_success():
    result = _run(FakeModel(AIMessage("Стоит в DEMO-0001.")))
    assert result.status == "success"
    assert result.data == "Стоит в DEMO-0001."
    assert result.action == "ответ без обращения к трекеру"
    assert result.errors == ""


def test_the_action_field_records_the_chain(monkeypatch):
    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(
        tools.httpx, "request", lambda *a, **k: _Response(200, {"items": []})
    )
    result = _run(
        FakeModel(
            _tool_call("search_inventory", {"query": "DEMO-0001"}),
            AIMessage("Ничего не нашлось."),
        )
    )
    assert result.status == "success"
    assert result.action == "search_inventory [success]"


def test_a_recovered_failure_is_still_reported(monkeypatch):
    """
    The turn succeeded, but a call failed on the way. "Answered, but only
    after a rejected call" is worth knowing and is invisible otherwise.
    """
    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(
        tools.httpx,
        "request",
        lambda *a, **k: _Response(404, {"error": {"code": "not_found", "message": "m", "hint": "h"}}),
    )
    result = _run(FakeModel(_tool_call("get_item", {"item_id": 999999}), AIMessage("Не найдено.")))
    assert result.status == "success"
    assert result.errors == "get_item: not_found"


def test_an_invented_tool_does_not_crash_the_loop():
    result = _run(FakeModel(_tool_call("delete_everything", {}), AIMessage("Такого не умею.")))
    assert result.status == "success"
    assert "unknown_tool" in result.errors


def test_bad_argument_types_come_back_as_data():
    """
    Pydantic validates before the tool body runs, so without the guard in
    chat.py this raises out of the loop instead of reaching the model.
    """
    result = _run(
        FakeModel(
            _tool_call("record_item_event", {"item_id": 1, "event_type": "service", "notes": -2026}),
            AIMessage("Исправляю."),
        )
    )
    assert result.status == "success"
    assert "invalid_arguments" in result.errors


def test_a_committing_call_waits_for_a_human(monkeypatch):
    asked = []

    def fake_confirm(name, args):
        asked.append(name)
        return False

    monkeypatch.setattr(chat, "_confirm", fake_confirm)
    result = _run(
        FakeModel(
            _tool_call("record_item_event", {"item_id": 1, "event_type": "service", "dry_run": False}),
            AIMessage("Отменено."),
        )
    )
    assert asked == ["record_item_event"], "a write must not happen without being asked about"
    assert "refused_by_user" in result.errors


def test_a_refusal_is_not_re_asked(monkeypatch):
    """
    A model that ignores the refusal used to re-prompt the person for the
    same write until the step limit stopped it.
    """
    asked = []
    monkeypatch.setattr(chat, "_confirm", lambda name, args: (asked.append(name), False)[1])

    call = {"item_id": 1, "event_type": "service", "dry_run": False}
    _run(
        FakeModel(
            _tool_call("record_item_event", call, "a"),
            _tool_call("record_item_event", dict(call, notes="ещё раз"), "b"),
            AIMessage("Ладно."),
        )
    )
    assert len(asked) == 1, "the person is asked once per turn, not once per attempt"


def test_a_dry_run_is_not_treated_as_a_write(monkeypatch):
    monkeypatch.setattr(chat, "_confirm", lambda name, args: pytest.fail("dry run must not prompt"))
    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(tools.httpx, "request", lambda *a, **k: _Response(200, {"ok": True}))
    _run(
        FakeModel(
            _tool_call("record_item_event", {"item_id": 1, "event_type": "service", "dry_run": True}),
            AIMessage("Проверил."),
        )
    )


def test_repeating_one_failing_call_abandons_the_turn(monkeypatch):
    monkeypatch.setattr(tools, "TOKEN", "stk_test")
    monkeypatch.setattr(
        tools.httpx,
        "request",
        lambda *a, **k: _Response(404, {"error": {"code": "not_found", "message": "m", "hint": "h"}}),
    )
    same = _tool_call("get_item", {"item_id": 999999})
    result = _run(FakeModel(same, same, same, same, same))

    assert result.status == "error"
    assert "повторяет один и тот же неверный вызов" in result.errors
    assert result.data == "", "there is no answer to give when the turn was abandoned"


def test_the_step_limit_ends_the_turn():
    """Every reply asks for another tool and none of them repeats exactly."""
    model = FakeModel(*[_tool_call("get_item", {"item_id": i}) for i in range(chat.MAX_STEPS + 2)])
    result = _run(model)
    assert result.status == "error"
    assert "step_limit" in result.errors


def test_every_tool_call_gets_a_reply_message():
    """
    A tool_call without its ToolMessage leaves a conversation the model
    cannot parse on the next turn — including when the turn is abandoned.
    """
    messages = [SystemMessage("system")]
    same = _tool_call("get_item", {"item_id": 1})
    chat.run_turn(FakeModel(same, same, same, same), messages, verbose=False)

    tool_call_ids = {
        c["id"] for m in messages if isinstance(m, AIMessage) for c in (m.tool_calls or [])
    }
    replied_to = {m.tool_call_id for m in messages if isinstance(m, chat.ToolMessage)}
    assert tool_call_ids == replied_to


def test_loop_errors_use_the_same_contract_as_tool_errors():
    """
    A model that could tell "the tracker refused" from "the loop refused"
    by the shape of the reply would learn to parse two formats.
    """
    messages = [SystemMessage("system")]
    chat.run_turn(FakeModel(_tool_call("nope", {}), AIMessage("ок")), messages, verbose=False)
    reply = next(m for m in messages if isinstance(m, chat.ToolMessage))

    assert tools.is_error(reply.content)
    assert reply.content.startswith("Status: error\nAction: ")
    assert "Errors: unknown_tool: " in reply.content
    assert json.dumps  # the envelope is text, not JSON — nothing to parse here
