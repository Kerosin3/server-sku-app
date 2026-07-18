---
name: add-catalog-value
description: Use when adding a new status, event type, firmware type, or category value — e.g. a new PlatformEvent.event_type, PartType.category, PlatformItem.status, or FirmwareRecord.firmware_type. Also applies to "добавить новый статус", "новый тип события", "новый тип прошивки", "новая категория детали".
version: 1.1.0
---

# Добавление нового значения статуса/типа/категории

Все backend-коды (`PartType.category`, `PlatformItem.status`,
`PlatformEvent.event_type`, `FirmwareRecord.firmware_type` и т.д.)
переводятся в русские подписи только через `app/i18n.py`. Это единая
точка перевода — не хардкодить русскую строку в шаблоне или роутере.

## Шаги

1. Найти нужный словарь в `app/i18n.py` (например `PLATFORM_EVENT_TYPES`,
   `FIRMWARE_TYPES`, `PLATFORM_STATUS`) и добавить туда новую пару
   `english_identifier: "Русская подпись"` — в том же коммите/изменении,
   которое вводит новое значение, не отдельным TODO.
2. Проверить, ограничено ли множество значений на уровне БД (Postgres
   `CHECK constraint`, см. `alembic/versions/0001_initial_schema.py`).
   Если да — нужна миграция, расширяющая constraint (см. скилл
   `db-migration`: сначала данные, потом сужение/расширение
   constraint). Если множество значений не ограничено на уровне БД —
   миграция не нужна, но убедиться, что это осознанный выбор, а не
   пропуск.
3. Для `event_type`/`firmware_type` — это append-only логи
   (`platform_events`, `firmware_records`), новое значение не требует
   миграции схемы самих таблиц, только регистрации в `i18n.py` и (если
   есть) расширения constraint.
4. Если новое значение влияет на `platform_items.status` (например,
   новый этап жизненного цикла) — обновить сервисный слой, который
   синхронизирует `platform_items.status` при записи `platform_events`,
   и добавить соответствующую интерактивную кнопку в UI (карточка
   изделия, `/items/{id}`), а не форму ручного ввода даты.
5. В шаблонах использовать Jinja-фильтр `label`
   (`{{ p.status | label('platform_status') }}`), не выводить
   backend-код напрямую и не дублировать перевод в шаблоне.
6. Если значение упоминается в `AGENTS.md` (например, «Текущий набор:
   ...») — обновить этот список там же.
