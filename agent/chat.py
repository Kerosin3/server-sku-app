"""
The agent loop, and the only executable here.

    export SERVER_TRACKER_TOKEN=stk_...
    python chat.py                       # диалог
    python chat.py "где стоит DEMO-CPU-0001?"   # один вопрос и выход

What the loop actually does is worth stating plainly, because it is
easy to assume more magic than there is: the model never calls anything.
It reads the conversation and writes back either an answer or a request
to call a tool. This file executes that request, appends the result to
the conversation, and asks the model again. Repeat until it answers.

Two guards live here rather than in the prompt:

- **A write needs a human "yes".** The prompt tells the model to dry-run
  first and ask; this file refuses to execute a committing call until
  the person at the keyboard confirms it. Guidance a model can forget is
  not a safeguard — the API's dry_run is only worth something if
  skipping it is impossible rather than merely discouraged.
- **A step limit.** A model that misreads an error can call the same
  tool forever. The cap turns that into a visible stop instead of a
  process spinning against the tracker.
"""
import json
import sys

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from model import build_model, describe
from prompt import SYSTEM_PROMPT
from server_tracker_tools import TOOLS

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
MAX_STEPS = 12
MAX_IDENTICAL_CALLS = 2

# A call is committing unless it is explicitly a dry run. Stated this way
# round on purpose: a tool added later without a dry_run argument is
# treated as committing and gets the confirmation prompt, rather than
# slipping through because a key was missing.
def _is_committing(args: dict) -> bool:
    return args.get("dry_run") is False


def _error(code: str, message: str, hint: str) -> str:
    return json.dumps({"ok": False, "code": code, "message": message, "hint": hint}, ensure_ascii=False)


def _validate(tool, args: dict) -> str | None:
    """
    Check the arguments against the tool's schema, returning an error
    envelope if they don't fit and None if they do.

    This runs *before* the confirmation gate, and the order is the whole
    point. Confirming first meant a malformed call was refused as
    "user declined" — so the model never learned its argument was the
    wrong type, produced the same call again, and the human was asked to
    approve the same broken write over and over until the step limit cut
    it off. Rejecting on shape first gives the model the one piece of
    information that lets it fix itself, and keeps the human out of a
    decision that was never real.
    """
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return None
    try:
        schema.model_validate(args)
    except Exception as exc:
        return _error(
            "invalid_arguments",
            f"{type(exc).__name__}: {exc}",
            "Fix the argument types and call again. Do not drop the field to make the call pass.",
        )
    return None


def _invoke(tool, args: dict) -> str:
    """
    Run a tool, turning any exception into the same envelope its normal
    failures use.

    server_tracker_tools already returns API errors as data instead of
    raising, but that only covers what happens *inside* the tool.
    Argument validation runs before it: a model that passes notes=-2026
    when a string is expected trips Pydantic in LangChain, and without
    this the whole loop dies on a mistake the model could have fixed
    itself. Pydantic's own message names the field and the expected type,
    so it is worth passing through verbatim.
    """
    try:
        return tool.invoke(args)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "code": "invalid_arguments",
                "message": f"{type(exc).__name__}: {exc}",
                "hint": "Re-read the tool's argument types and call it again with corrected values.",
            },
            ensure_ascii=False,
        )


def _confirm(tool_name: str, args: dict) -> bool:
    shown = {k: v for k, v in args.items() if k != "dry_run"}
    print(f"\n  ⚠ Модель хочет записать в базу: {tool_name}({json.dumps(shown, ensure_ascii=False)})")
    try:
        answer = input("    Выполнить? [y/N] ").strip().lower()
    except EOFError:
        # Non-interactive run (a pipe, a test): refuse rather than
        # silently write, and let the model report that to the user.
        print("    (нет ввода — отказано)")
        return False
    return answer in ("y", "yes", "д", "да")


def run_turn(model, messages: list, *, verbose: bool = True) -> str:
    """One user question through to an answer, executing tools on the way."""
    # Asked once and told no, the answer stays no for the rest of this
    # turn. Otherwise a model that ignores the refusal re-prompts the
    # person for the same write until the step limit stops it.
    declined = False
    # A model that misreads a rejection tends to re-send the identical
    # call. Counting them turns a silent spin against the step limit into
    # a message it can actually act on.
    attempts: dict[str, int] = {}

    for _ in range(MAX_STEPS):
        abort = None
        reply = model.invoke(messages)
        messages.append(reply)

        if not reply.tool_calls:
            return reply.content

        for call in reply.tool_calls:
            name, args = call["name"], call["args"]
            tool = TOOLS_BY_NAME.get(name)
            if verbose:
                print(f"  → {name}({json.dumps(args, ensure_ascii=False)})")

            signature = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
            attempts[signature] = attempts.get(signature, 0) + 1

            if attempts[signature] > MAX_IDENTICAL_CALLS:
                # Telling the model to stop is not enough — it has already
                # ignored the same rejection twice, and a third explanation
                # buys nothing but latency. Give up out loud instead: the
                # person gets a straight answer about what failed rather
                # than a turn that quietly runs out of steps.
                abort = (
                    f"Не справился: модель повторяет один и тот же неверный вызов "
                    f"{name}({json.dumps(args, ensure_ascii=False)}) и не реагирует на объяснение ошибки.\n"
                    "Попробуй переформулировать задачу или сделать это в веб-интерфейсе."
                )
                result = _error(
                    "repeated_call",
                    "This exact call has already failed the same way; the turn is being abandoned.",
                    "Nothing was written.",
                )
            elif tool is None:
                # The model invented a tool. Say so in the conversation
                # instead of crashing: it can recover from being told.
                result = _error(
                    "unknown_tool",
                    f"There is no tool named {name!r}.",
                    f"Available tools: {', '.join(TOOLS_BY_NAME)}.",
                )
            elif (invalid := _validate(tool, args)) is not None:
                result = invalid
            elif _is_committing(args) and (declined or not _confirm(name, args)):
                declined = True
                result = _error(
                    "refused_by_user",
                    "The user did not confirm this write, so nothing was done.",
                    "Tell the user it was cancelled. Do not retry it in this turn.",
                )
            else:
                result = _invoke(tool, args)

            if verbose:
                payload = json.loads(result)
                print(f"    {'ok' if payload.get('ok') else payload.get('code')}")

            # Appended even when giving up: every tool_call in a reply
            # needs its ToolMessage, or the next turn starts from a
            # conversation the model cannot parse.
            messages.append(ToolMessage(result, tool_call_id=call["id"]))

        if abort:
            return abort

    return (
        f"Прервано: модель сделала {MAX_STEPS} шагов и не пришла к ответу. "
        "Скорее всего, она зациклилась на одной ошибке."
    )


def main() -> None:
    model = build_model().bind_tools(TOOLS)
    messages = [SystemMessage(SYSTEM_PROMPT)]

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        messages.append(HumanMessage(question))
        print(f"> {question}")
        print(f"\n{run_turn(model, messages)}")
        return

    print(f"Трекер-ассистент. Модель: {describe()}. Пустая строка — выход.\n")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            return
        messages.append(HumanMessage(question))
        print(f"\n{run_turn(model, messages)}\n")


if __name__ == "__main__":
    main()
