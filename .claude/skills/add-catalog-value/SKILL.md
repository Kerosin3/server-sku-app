---
name: add-catalog-value
description: Use when adding a new status, event type, or firmware type value — e.g. a new PlatformEvent.event_type, PlatformItem.status, or FirmwareRecord.firmware_type. Does NOT apply to part categories (those are user-editable DB data via /part-categories, not a hardcoded enum — see AGENTS.md "Категории деталей"). Also applies to "добавить новый статус", "новый тип события", "новый тип прошивки".
version: 1.2.0
---

# Добавление нового значения статуса/типа

Все backend-коды (`PlatformItem.status`, `PlatformEvent.event_type`,
`FirmwareRecord.firmware_type` и т.д.) переводятся в русские подписи
только через `app/i18n.py`. Это единая точка перевода — не хардкодить
русскую строку в шаблоне или роутере.

**Категории деталей (`part_categories`) сюда не относятся** — это
единственное исключение из этого паттерна в проекте: живые данные в
БД, редактируемые пользователем через `/part-categories` (и инлайн на
`/variants/{id}`), а не Python-словарь. Не добавлять новую категорию
в `app/i18n.py` — просто создать строку в `part_categories` (через UI
или, если нужно программно, `app/services/part_categories.py`).

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
