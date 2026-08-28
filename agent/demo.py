"""
Exercise the tools against a running tracker, without a model.

Worth having separately from any agent: when an agent misbehaves the
first question is always whether the tools work, and answering it should
not require an LLM, an API key or a network round trip to a provider.

    export SERVER_TRACKER_TOKEN=stk_...
    python demo.py
"""
import json

from server_tracker_tools import (
    TOOLS,
    get_item,
    is_error,
    record_item_event,
    search_inventory,
    summary,
)


def show(title: str, result: str) -> dict | None:
    """Print a tool result and hand back its Data, parsed, when there is one."""
    print(f"\n=== {title} -> {summary(result)} ===")
    print(result[:900] + ("\n… (обрезано)" if len(result) > 900 else ""))
    if is_error(result):
        return None
    _, _, data = result.partition("\nData: ")
    return json.loads(data)


print("Инструменты, которые получит модель:")
for t in TOOLS:
    first_line = (t.description or "").strip().splitlines()[0]
    print(f"  - {t.name}({', '.join(t.args)}) — {first_line}")

found = show("поиск DEMO-0001", search_inventory.invoke({"query": "DEMO-0001"}))
if not found or not found["items"]:
    print("\nНечего показывать дальше — демо-изделие не найдено.")
    raise SystemExit(1)

item_id = found["items"][0]["id"]
item = show(f"состояние изделия {item_id}", get_item.invoke({"item_id": item_id}))
if item:
    print(
        f"\n  {item['asset_tag']}: {item['status_label']}, "
        f"компонентов {len(item['components_installed'])}, этапов {len(item['events'])}"
    )

show(
    "проверка этапа (dry run по умолчанию)",
    record_item_event.invoke({"item_id": item_id, "event_type": "service"}),
)
show(
    "заведомо неверный этап",
    record_item_event.invoke({"item_id": item_id, "event_type": "не-такой-этап"}),
)
show("несуществующее изделие", get_item.invoke({"item_id": 999999}))
