# Server SKU Tracker

Учёт серверных платформ собственного производства: серийники шасси,
материнских плат, памяти, процессоров, карт в райзере — с полной историей
установки/замены компонентов.

Архитектура и правила разработки — см. **AGENTS.md** (обязательно к
прочтению перед тем, как вносить изменения, особенно для кодового агента).

## Запуск (self-hosted, Docker)

```bash
cp .env.example .env
# отредактировать .env: задать POSTGRES_PASSWORD и SECRET_KEY
#   openssl rand -hex 32   # для SECRET_KEY

docker compose up -d --build

# применить миграции
docker compose exec app alembic upgrade head

# создать первого администратора
docker compose exec app python -m app.create_admin
```

Отредактируйте `Caddyfile` — укажите реальный домен/адрес вместо
`tracker.internal.example`, либо настройте internal TLS для чисто
внутренней сети без публичного домена.

Приложение будет доступно через Caddy на портах 80/443. Для локальной
разработки без Caddy можно ходить напрямую:
`docker compose exec app uvicorn app.main:app --reload --host 0.0.0.0`

## Разработка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## Бэкапы

БД — источник истины по производству, бэкапы обязательны:

```bash
docker compose exec db pg_dump -U tracker server_tracker > backups/$(date +%F).sql
```

Файлы, загруженные к исполнениям (`variant_uploads` volume — архивы
тестов и т.п.), в дампе БД не участвуют и бэкапятся отдельно:

```bash
docker run --rm -v server-tracker_variant_uploads:/data -v "$(pwd)/backups:/backup" \
  alpine tar czf /backup/variant_uploads-$(date +%F).tar.gz -C /data .
```

Вынесите обе команды в cron на хосте и храните копии вне контейнера/сервера.
См. также AGENTS.md → «Где физически хранятся данные».

## Текущий статус

Готово: схема БД, модели, аутентификация и управление пользователями
(`/users`, только `admin`). Иерархия Платформа → Исполнение → Изделие:
`/platforms` (платформы), `/platforms/{id}` (исполнения платформы),
`/variants/{id}` (конструктор элементов + изделия исполнения), `/items/{id}`
(карточка изделия с чек-листом комплектности и установкой/снятием
компонентов по серийному номеру); `/` — общий дашборд по всем изделиям.
Пока нет CRUD для part_types/part_units — без него компонент негде
завести перед установкой на изделие, это следующий приоритет.
Подробный статус — roadmap в AGENTS.md.
