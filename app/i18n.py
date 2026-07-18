"""
Single source of truth for backend-code -> Russian UI label translation.

Project-wide language convention:
- Web UI (Jinja templates, and any user-facing text rendered in the
  browser) is in Russian.
- Everything else — Python identifiers, comments, docstrings, DB column
  and enum/status code values, CLI scripts, log messages — is in English.

Whenever a new enum/status/category code is introduced anywhere in the
codebase (new PartType.category value, new Platform.status value, new
PlatformEvent.event_type, etc.), add its Russian label here in the same
change. Never hardcode a translated string inline in a template or
router — always go through this module, so there is exactly one place
to check/update for correctness.
"""

USER_ROLES = {
    "admin": "Администратор",
    "engineer": "Инженер",
    "viewer": "Наблюдатель",
}

PART_CATEGORIES = {
    "chassis": "Шасси",
    "motherboard": "Материнская плата",
    "midplane": "Мидплейн",
    "backplane_front": "Бэкплейн (передний)",
    "backplane_rear": "Бэкплейн (задний)",
    "io_board": "IO-плата",
    "usb_board": "USB-плата",
    "psu": "Блок питания",
    "cpu": "Процессор",
    "ram": "Модуль памяти",
    "riser_card": "Райзер-карта",
    "nic": "Сетевая карта",
    "disk": "Накопитель (HDD/SSD)",
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
    "testing": "Тестирование",
    "shipped": "Отгружен",
    "deployed": "В эксплуатации",
    "rma": "RMA",
    "decommissioned": "Списан",
}

# See app/models/platform_event.py — this is the interactive milestone
# log for a platform instance (manufacture date, QC/verification date,
# initial and final test dates, ship date, ...). Extensible: add a new
# event_type code + its Russian label here, no schema migration needed.
PLATFORM_EVENT_TYPES = {
    "manufactured": "Изготовлено",
    "qc_verified": "Проверено (QC)",
    "initial_test": "Первичное тестирование",
    "final_test": "Финальное тестирование",
    "shipped": "Отгружено",
}

# See app/models/firmware_record.py — firmware version history per
# part_unit. Extensible: add a new firmware_type + its Russian label here,
# no schema migration needed.
FIRMWARE_TYPES = {
    "bios": "BIOS",
    "bmc": "BMC",
    "cpld": "CPLD",
    "backplane_fw": "Прошивка бэкплейна",
}

FIRMWARE_IMAGE_SLOTS = {
    "primary": "Основная",
    "backup": "Резервная",
}

_REGISTRY = {
    "role": USER_ROLES,
    "part_category": PART_CATEGORIES,
    "part_unit_status": PART_UNIT_STATUSES,
    "platform_status": PLATFORM_STATUSES,
    "platform_event_type": PLATFORM_EVENT_TYPES,
    "firmware_type": FIRMWARE_TYPES,
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
