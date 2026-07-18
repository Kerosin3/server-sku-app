---
name: service-audit-crud
description: Use when adding or changing a CRUD endpoint / router that mutates part_units, platforms, or platform_components, or any code touching audit_log or role-based field visibility. Also applies to "добавить CRUD", "новый роутер", "мутация part_units/platforms/platform_components", "audit log".
version: 1.0.0
---

# CRUD-мутации, аудит и роли в server-tracker

## Разделение слоёв

- Бизнес-логика — в `app/services/`, роутер — тонкий: валидация входа
  через Pydantic-схему, вызов сервисной функции, сериализация ответа.
  Не писать SQLAlchemy-запросы прямо в роутере.
- Вся мутация (включая запись в `audit_log`) — внутри одной
  SQLAlchemy-транзакции: либо применилось всё, либо ничего.

## Аудит

- Любое создание/изменение/удаление `part_units`, `platforms`,
  `platform_components` обязано писать запись в `audit_log` (кто, что,
  когда, diff в JSONB) через явный вызов `app/services/audit.py`.
- Не полагаться на ORM-события (`before_insert`/`after_update` и т.п.)
  для этого — только явный вызов, чтобы человек без опыта в веб-разработке
  мог прочитать сервисную функцию и увидеть весь эффект мутации в
  одном месте.

## Роли (RBAC)

- `admin` — всё; `engineer` — CRUD платформ/компонентов; `viewer` —
  только чтение.
- Для `viewer`: `platforms.customer` и любые коммерческие заметки
  скрываются на уровне сериализации (в `app/schemas/`), не только на
  фронтенде. Проверять это в каждом роутере, который отдаёт платформы,
  а не полагаться на то, что фильтрация сделана где-то один раз.

## Компоненты платформы (RMA-паттерн)

- `platform_components` — история, не текущее состояние: снятие
  компонента — это `UPDATE removed_at = now()` на существующей строке,
  установка нового — **новая строка**, а не перезапись старой.
  `removed_at IS NULL` означает «установлен сейчас».
- Не писать код, который редактирует уже закрытую (`removed_at`
  заполнен) строку `platform_components` — это историческая запись.
