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
   - `platform_components` — что физически установлено в изделии
     сейчас/было раньше (`installed_at`/`removed_at`);
   - `platform_events` — вехи жизненного цикла изделия (изготовлено,
     проверено, тесты, отгрузка — `occurred_at`);
   - `firmware_records` — версии прошивок part_unit'а, с учётом того,
     что BIOS/BMC ведутся в двух независимых образах (`image_slot`).

   Это осознанный выбор: новый тип события/прошивки не требует миграции
   схемы, а полная история (не только текущее значение) нужна для
   расследования отказов и RMA.

3. **Иерархия Платформа → Исполнение → Изделие (as-planned vs
   as-built).** `platforms` (продуктовая линейка, напр. «2U Storage») →
   `platform_variants` + `platform_variant_slots` (конкретная
   BOM-конфигурация/«конструктор»: midplane, backplane front/rear, io
   board, usb board, psu, cpu, dimm, riser card, disk и т.д., с
   quantity/required) → `platform_items` (физический юнит с asset tag).
   `platform_components` — факт того, что реально стоит в конкретном
   изделии. Разделение даёт бесплатную проверку комплектности без
   ручного дублирования структуры для каждого изделия. UI строго
   вложенный: `/platforms` → `/platforms/{id}` (исполнения) →
   `/variants/{id}` (элементы изделия + изделия этого исполнения) →
   `/items/{id}`. В коде/БД это «slot» (`PlatformVariantSlot`), в
   русском UI/тексте — «элемент изделия», не «слот».

4. **Схема — источник истины.**
   `alembic/versions/` — 0001 создаёт базовую схему, 0002 добавляет
   `api_tokens`, 0003 расширяет `audit_log.entity_type` до 64 символов.
   Полностью сверена с моделями (19 таблиц: users,
   api_tokens, platforms, platform_variants, part_categories,
   firmware_types, part_types, part_units, firmware_records,
   platform_variant_slots, platform_variant_firmware_requirements,
   platform_variant_mac_requirements, platform_items,
   platform_components, platform_events, mac_addresses, audit_log,
   login_attempts, attachments) — колонки, nullable,
   unique/check-constraints и индексы совпадают 1:1, downgrade()
   корректен по порядку FK-зависимостей. Прошивки и
   MAC-адреса — тоже элементы конструктора (requirements-таблицы на
   исполнение), не только физические детали, см. AGENTS.md.
   `part_categories`/`firmware_types` — исключение из «языковой
   конвенции»: это
   пользовательский каталог, редактируемый из UI, а не захардкоженный в
   коде enum, см. AGENTS.md «Категории деталей».

5. **Сохранность данных при изменениях.** БД и код будут меняться
   постоянно — это норма, а не исключение. Любая миграция/рефакторинг,
   затрагивающие существующие данные, должны максимально их сохранять
   (backfill вместо drop+add, rename вместо пересоздания, явный маппинг
   старых enum-значений). `DROP TABLE`/`DROP COLUMN` и особенно
   усечение append-only логов (`platform_components`, `platform_events`,
   `firmware_records`, `audit_log`) — только после явного согласия
   пользователя. `downgrade()` всегда реализован по-настоящему, не
   `pass`. Подробности и обоснование — в `AGENTS.md`.

## Два интерфейса, одна логика

У проекта два входа к одним и тем же данным:

- **Веб** (`app/routers/*.py` + Jinja) — для человека, по-русски.
- **JSON API** (`app/routers/api_v1.py`, `/api/v1`) — для скриптов и
  LLM-агента: 8 операций чтения и 19 записи, у каждой записи есть
  `dry_run`. Покрывают весь цикл — от создания платформы и состава
  исполнения до отгрузки и удаления. Доступ — по токенам из таблицы
  `api_tokens`, которые выпускаются и отзываются на `/api-tokens`; пока
  ни одного токена нет, API закрыт.

Оба вызывают **один и тот же сервисный слой**, поэтому правила
(порядок этапов, блокировка состава, аудит) действуют одинаково и
дублировать их не нужно — и нельзя. Каталог возможностей API и границы
того, что агенту делать не дают, — в `AGENTS.md` → «Что агент может
через API»; его обязательно обновлять вместе с изменением эндпоинтов.

## С чего начать

Roadmap в конце `AGENTS.md`, по порядку: auth → part_types/part_units
(+ firmware_records) → platforms/variants (конструктор) → platform_items
(+ mac_addresses + platform_events) → поиск → импорт/экспорт → UI.

Локальный запуск — см. `README.md` (`docker compose up -d --build`,
затем `alembic upgrade head`, затем `python -m app.create_admin`).
