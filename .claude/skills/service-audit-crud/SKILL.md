---
name: service-audit-crud
description: Use when adding or changing a CRUD endpoint / router that mutates part_units, platform_items, or platform_components, or any code touching audit_log or role-based field visibility. Also applies to "добавить CRUD", "новый роутер", "мутация part_units/platform_items/platform_components", "audit log".
version: 1.1.0
---

# CRUD-мутации, аудит и роли в server-tracker

Иерархия: `platforms` (платформа/продуктовая линейка) →
`platform_variants` (исполнение/BOM, конструктор) → `platform_items`
(изделие, физический юнит). См. AGENTS.md "Иерархия «Платформа →
Исполнение → Изделие»" для полной модели.

## Разделение слоёв

- Бизнес-логика — в `app/services/`, роутер — тонкий: валидация входа
  через Pydantic-схему или FastAPI `Form(...)` (в этом проекте UI —
  server-rendered Jinja, не JSON API, так что чаще именно `Form`), вызов
  сервисной функции, рендер шаблона. Не писать SQLAlchemy-запросы прямо
  в роутере.
- Вся мутация (включая запись в `audit_log`) — внутри одной
  SQLAlchemy-транзакции: либо применилось всё, либо ничего.

## Аудит

- Любое создание/изменение/удаление `part_units`, `platform_items`,
  `platform_components` обязано писать запись в `audit_log` (кто, что,
  когда, diff в JSONB) через явный вызов `app/services/audit.py`.
- Не полагаться на ORM-события (`before_insert`/`after_update` и т.п.)
  для этого — только явный вызов, чтобы человек без опыта в веб-разработке
  мог прочитать сервисную функцию и увидеть весь эффект мутации в
  одном месте.
- `platforms`/`platform_variants` (каталог платформ и исполнений) не
  аудируются — справочные данные, не складской учёт.

## Роли (RBAC)

- `admin` — всё; `engineer` — CRUD по всей иерархии платформ и
  компонентам; `viewer` — только чтение.
- Для `viewer`: `platform_items.customer` и любые коммерческие заметки
  скрываются в шаблоне (`{% if user.role != 'viewer' %}`) — это и есть
  точка сериализации, пока UI полностью server-rendered. Если появится
  JSON API — фильтровать в `app/schemas/`, не полагаться на фронтенд.
  Проверять это в каждом роутере/шаблоне, который отдаёт изделие, а не
  полагаться на то, что фильтрация сделана где-то один раз.

## Компоненты изделия (RMA-паттерн)

- `platform_components` — история, не текущее состояние: снятие
  компонента — это `UPDATE removed_at = now()` на существующей строке,
  установка нового — **новая строка**, а не перезапись старой.
  `removed_at IS NULL` означает «установлен сейчас».
- Не писать код, который редактирует уже закрытую (`removed_at`
  заполнен) строку `platform_components` — это историческая запись.
