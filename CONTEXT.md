# server-tracker — краткий контекст для агента

Веб-приложение для учёта и трассировки серверных платформ собственного
производства (50–300 юнитов/год, self-hosted, Docker Compose).

**Стек**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL 16,
Jinja2 + HTMX (без SPA/React), сессионная авторизация (argon2), Docker
Compose + Caddy.

Перед тем как что-либо менять — прочитать **`AGENTS.md`** целиком, там
все архитектурные решения с обоснованием и roadmap. Здесь — только
самое важное, чтобы не сломать на первом же шаге.

## 5 вещей, которые нельзя нарушать

1. **Язык.** Веб-интерфейс (Jinja-шаблоны, то, что видит пользователь) —
   русский. Весь код (идентификаторы, докстринги, комментарии, CLI) —
   английский. Перевод enum/status-кодов только через `app/i18n.py` +
   Jinja-фильтр `label` (уже зарегистрирован в `app/templating.py`).

2. **История вместо колонок.** Три сущности в проекте — это append-only
   логи с временной меткой, а не фиксированные колонки на "родительской"
   таблице:
   - `platform_components` — что физически установлено в платформе
     сейчас/было раньше (`installed_at`/`removed_at`);
   - `platform_events` — вехи жизненного цикла платформы (изготовлено,
     проверено, тесты, отгрузка — `occurred_at`);
   - `firmware_records` — версии прошивок part_unit'а, с учётом того,
     что BIOS/BMC ведутся в двух независимых образах (`image_slot`).

   Это осознанный выбор: новый тип события/прошивки не требует миграции
   схемы, а полная история (не только текущее значение) нужна для
   расследования отказов и RMA.

3. **Конструктор (as-planned vs as-built).** `platform_models` +
   `platform_model_slots` — эталон: какие посадочные места должна иметь
   платформа данной модели (midplane, backplane front/rear, io board,
   usb board, psu, cpu, dimm, riser card и т.д.), с quantity/required.
   `platform_components` — факт. Разделение даёт бесплатную проверку
   комплектности без ручного дублирования структуры для каждого юнита.

4. **Схема — источник истины.**
   `alembic/versions/0001_initial_schema.py`. Полностью сверена с
   моделями (11 таблиц: users, part_types, part_units, firmware_records,
   platform_models, platform_model_slots, platforms, platform_components,
   platform_events, mac_addresses, audit_log) — колонки, nullable,
   unique/check-constraints и индексы совпадают 1:1, downgrade()
   корректен по порядку FK-зависимостей.

5. **Сохранность данных при изменениях.** БД и код будут меняться
   постоянно — это норма, а не исключение. Любая миграция/рефакторинг,
   затрагивающие существующие данные, должны максимально их сохранять
   (backfill вместо drop+add, rename вместо пересоздания, явный маппинг
   старых enum-значений). `DROP TABLE`/`DROP COLUMN` и особенно
   усечение append-only логов (`platform_components`, `platform_events`,
   `firmware_records`, `audit_log`) — только после явного согласия
   пользователя. `downgrade()` всегда реализован по-настоящему, не
   `pass`. Подробности и обоснование — в `AGENTS.md`.

## С чего начать

Roadmap в конце `AGENTS.md`, по порядку: auth → part_types/part_units
(+ firmware_records) → platform_models/slots (конструктор) → platforms
(+ mac_addresses + platform_events) → поиск → импорт/экспорт → UI.

Локальный запуск — см. `README.md` (`docker compose up -d --build`,
затем `alembic upgrade head`, затем `python -m app.create_admin`).
