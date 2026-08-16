---
name: db-migration
description: Use when writing or reviewing an Alembic migration in this project — adding/removing a column or table, renaming something, narrowing an enum/CHECK constraint, or any schema change. Also applies to "создать миграцию", "изменить схему БД", "добавить колонку", "новая таблица", "alembic revision".
version: 1.0.0
---

# Alembic-миграции в server-tracker

Приоритет проекта — надёжность и сохранность данных, не скорость
разработки схемы. См. `AGENTS.md` → «Устойчивость к изменениям —
сохранность данных при миграциях» для обоснования; здесь — чеклист.

## Перед тем как писать миграцию

1. Спросить: теряются ли существующие данные при этом изменении?
   Если да — это не решается молча, план нужно проговорить с
   пользователем до применения.
2. **`alembic/versions/0001_initial_schema.py` заморожен.** Не
   редактировать его ни при каких обстоятельствах. Любое изменение
   схемы — только новой ревизией (`0002_...`, `0003_...`).

   Раньше здесь была оговорка, разрешавшая править 0001 напрямую «пока
   нет реального развёртывания» — она снята. По ней 0001 переписывался
   12 раз, и в результате база, где миграция уже применялась, не
   получила бы ни одного последующего изменения: `alembic_version`
   остаётся `0001`, `upgrade head` не находит что применять, а код уже
   ждёт новые колонки. Обнаруживается это как 500 на ровном месте, а
   чинится только пересозданием базы, то есть потерей учёта.

3. **Модели обязаны описывать реальную схему.** `alembic check`
   сравнивает `Base.metadata` с живой БД и должен проходить чисто.
   Если индекс/constraint создан миграцией, но не объявлен в модели,
   `--autogenerate` предложит его **удалить** — так можно потерять,
   например, частичные уникальные индексы на `part_categories` /
   `firmware_types`, которые держат уникальность имён. Индекс с
   нестандартным именем или условием объявлять явно в `__table_args__`
   (образцы — `app/models/part_category.py`,
   `app/models/attachment.py`), а не через `index=True`/`unique=True`.

## Правила самой миграции

- Переименование колонки/таблицы — `op.alter_column(..., new_column_name=)`
  / `op.rename_table(...)`, никогда `drop` + `add` того же смысла под
  новым именем (это стирает данные).
- Новая `NOT NULL` колонка на непустой таблице — в три шага одной
  миграции: добавить nullable → `UPDATE` backfill → отдельный
  `ALTER COLUMN ... SET NOT NULL`. Не добавлять `NOT NULL` сразу, если
  в таблице уже могут быть строки.
- Сужение списка допустимых значений (CHECK constraint / enum) —
  сначала явный `UPDATE`, маппящий старые значения в новые, потом
  сужение constraint. Никогда не полагаться на то, что старых значений
  просто не будет.
- `downgrade()` обязателен и реален (не `pass`). Он должен быть
  безопасен для строк, вставленных уже после апгрейда — не падать, не
  портить данные, существовавшие до апгрейда, даже если часть новых
  данных при откате неизбежно теряется.
- `DROP TABLE` / `DROP COLUMN` — стоп-сигнал. Особенно для append-only
  логов (`platform_components`, `platform_events`, `firmware_records`,
  `audit_log`) — это самые ценные данные в системе. Не делать это без
  явного запроса пользователя, даже если колонка кажется неиспользуемой.

## После написания

- Прогнать полный цикл на **отдельной временной** БД, не на рабочей:

  ```bash
  PW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
  URL="postgresql+psycopg://tracker:$PW@db:5432/migration_selftest"
  docker compose exec -T db psql -U tracker -d postgres -c "CREATE DATABASE migration_selftest;"
  docker compose exec -T -e DATABASE_URL="$URL" app alembic upgrade head
  docker compose exec -T -e DATABASE_URL="$URL" app alembic check       # должно быть "No new upgrade operations detected"
  docker compose exec -T -e DATABASE_URL="$URL" app alembic downgrade -1
  docker compose exec -T -e DATABASE_URL="$URL" app alembic upgrade head
  docker compose exec -T db psql -U tracker -d postgres -c "DROP DATABASE migration_selftest;"
  ```

  Миграция должна пережить цикл без ошибок, а `check` — пройти чисто.
- Прогнать `alembic check` и на рабочей БД после `upgrade head` (это же
  делает `scripts/deploy.sh` и предупреждает, если схема разошлась с
  моделями).
- Если в проекте появилась новая таблица — обновить список таблиц в
  `AGENTS.md` («Схема данных») и `CONTEXT.md` (пункт 4), чтобы список
  таблиц (сейчас 16) оставался актуальным.
