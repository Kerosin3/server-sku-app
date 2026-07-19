"""
Single source of truth for backend-code -> Russian UI label translation.

Project-wide language convention:
- Web UI (Jinja templates, and any user-facing text rendered in the
  browser) is in Russian.
- Everything else — Python identifiers, comments, docstrings, DB column
  and enum/status code values, CLI scripts, log messages — is in English.

Whenever a new enum/status code is introduced anywhere in the codebase
(new PlatformItem.status value, new PlatformEvent.event_type, etc.), add
its Russian label here in the same change. Never hardcode a translated
string inline in a template or router — always go through this module,
so there is exactly one place to check/update for correctness.

Exception: part categories (app/models/part_category.py) and firmware
types (app/models/firmware_type.py) are NOT here — they're
user-editable catalog data (part_categories / firmware_types tables),
not a Python-hardcoded enum. See PART_CATEGORY_GROUPS below for the two
fixed groups a category can belong to; firmware types have no
equivalent grouping.
"""

USER_ROLES = {
    "admin": "Администратор",
    "engineer": "Инженер",
    "viewer": "Наблюдатель",
}

# NOTE: part categories are NOT here. Unlike every other dictionary in
# this module, part categories are live data in the part_categories
# table (app/models/part_category.py), editable through /part-categories
# — engineers add new physical shapes themselves, no code deploy needed.
# Only the two fixed *groups* a category can belong to get a label here.
PART_CATEGORY_GROUPS = {
    "custom": "В составе изделия",
    "purchased": "Покупное",
}

PART_UNIT_STATUSES = {
    "in_stock": "На складе",
    "installed": "Установлен",
    "rma": "RMA",
    "scrapped": "Списан",
    "retired": "Выведен из эксплуатации",
}

PLATFORM_STATUSES = {
    "assembly": "Сборка",
    "assembled": "Укомплектовано",
    "testing": "Тестирование",
    "shipped": "Отгружен",
    "deployed": "В эксплуатации",
    "rma": "RMA",
    "decommissioned": "Списан",
}

# See app/models/platform_event.py — this is the interactive milestone
# log for a platform item (completion date, test start/end, ship date,
# ...). Extensible: add a new event_type code + its Russian label here,
# no schema migration needed. Order here is the process order and drives
# the order of milestone buttons on the item page — keep it that way.
PLATFORM_EVENT_TYPES = {
    "assembled": "Укомплектовано",
    "test_started": "Тестирование начато",
    "test_passed": "Тест пройден",
    "test_passed_with_remarks": "Тест пройден с замечаниями",
    "test_failed": "Тест не пройден",
    "shipped": "Отгружено",
    "service": "Сервисное обслуживание",
}

FIRMWARE_IMAGE_SLOTS = {
    "primary": "Основная",
    "backup": "Резервная",
}

_REGISTRY = {
    "role": USER_ROLES,
    "part_category_group": PART_CATEGORY_GROUPS,
    "part_unit_status": PART_UNIT_STATUSES,
    "platform_status": PLATFORM_STATUSES,
    "platform_event_type": PLATFORM_EVENT_TYPES,
    "firmware_image_slot": FIRMWARE_IMAGE_SLOTS,
}


def label(code: str, dictionary_name: str) -> str:
    """
    Jinja filter: {{ p.status | label('platform_status') }}

    Returns the Russian label for a backend code. Falls back to the raw
    code wrapped in brackets (e.g. "[unknown_code]") instead of raising,
    so a missing translation is visible and obvious in the UI rather than
    silently disappearing or crashing the page.
    """
    mapping = _REGISTRY.get(dictionary_name, {})
    return mapping.get(code, f"[{code}]")
