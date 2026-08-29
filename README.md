# Server SKU Tracker

Учёт серверных платформ собственного производства: серийники шасси,
материнских плат, памяти, процессоров, карт в райзере — с полной историей
установки и замены компонентов.

Этот файл — про **эксплуатацию**: как поднять, как войти, как выпустить
токен, как бэкапить.

| Если нужно | Смотреть |
|---|---|
| понять, что это за проект и как устроен | [OVERVIEW.md](OVERVIEW.md) |
| менять код — архитектура и обоснования | [AGENTS.md](AGENTS.md) |
| правила, которые нельзя нарушать, коротко | [CONTEXT.md](CONTEXT.md) |
| работать с LLM-агентом | [agent/GUIDE.md](agent/GUIDE.md) |
| устройство агента | [agent/README.md](agent/README.md) |

**Содержание:** [Быстрый старт](#быстрый-старт) ·
[Первый вход](#первый-вход) · [Если забыли пароль](#если-забыли-пароль) ·
[Карта интерфейса](#карта-интерфейса) · [JSON API](#json-api) ·
[Агент](#llm-агент) · [Разработка и тесты](#разработка-и-тесты) ·
[Бэкапы](#бэкапы) · [Чего ещё нет](#чего-ещё-нет)

---

## Быстрый старт

```bash
./scripts/deploy.sh
```

[`scripts/deploy.sh`](scripts/deploy.sh) идемпотентен — безопасно
запускать повторно после `git pull`, ничего не затирает. Создаст `.env`
со случайными `POSTGRES_PASSWORD`/`SECRET_KEY`, каталоги данных, поднимет
контейнеры, применит миграции и проверит, что схема БД совпадает с
моделями.

Дальше — [первый вход](#первый-вход).

<details>
<summary>То же самое вручную</summary>

```bash
cp .env.example .env
# задать POSTGRES_PASSWORD и SECRET_KEY:
#   openssl rand -hex 32

docker compose up -d --build
docker compose exec app alembic upgrade head
docker compose exec app python -m app.create_admin
```

`DATA_DIR` и `BACKUP_DIR` в [`.env`](.env.example) — куда на хосте лягут
данные БД, загруженные файлы и бэкапы. Это bind mount, а не анонимный
том: так проще бэкапить и смотреть занятое место. По умолчанию `./data`
и `./backups` рядом с проектом; в проде разумнее абсолютный путь вроде
`/srv/server-tracker/data`. Подробнее — [AGENTS.md → «Где физически
хранятся данные»](AGENTS.md).

</details>

<details>
<summary>Caddy и сетевой доступ</summary>

Приложение доступно через Caddy на портах 80/443. В
[`Caddyfile`](Caddyfile) укажите реальный домен или адрес вместо
`tracker.internal.example`, либо настройте internal TLS для чисто
внутренней сети без публичного домена.

Для локальной разработки без Caddy — напрямую:

```bash
docker compose exec app uvicorn app.main:app --reload --host 0.0.0.0
```

</details>

## Первый вход

После `deploy.sh` в базе нет пользователей, и приложение это понимает:
`/login` сам ведёт на **`/setup`**. Форма просит логин, пароль (от 8
символов) и **контрольный вопрос с ответом**.

Без браузера — то же самое из CLI
([`app/create_admin.py`](app/create_admin.py)):

```bash
docker compose exec app python -m app.create_admin
```

> **Разница между путями существенная.** `create_admin` контрольный
> вопрос **не задаёт**, и созданный им администратор не сможет
> восстановить пароль сам. Заведите вопрос сразу после входа на
> `/account/security-question` — ссылка в шапке, это ваше имя
> пользователя.

Вместе с самым первым пользователем заводится демонстрационный пример:
платформа «DEMO 4U AI Server», исполнение «8x GPU Full Config», изделие
«DEMO-0001» с укомплектованными компонентами, прошивками, MAC-адресами,
историей этапов и файлами — чтобы система открылась заполненной, а не
пустым дашбордом. Создаётся ровно один раз, пока в базе нет ни одного
пользователя, и удаляется как обычные данные
([`app/services/demo_seed.py`](app/services/demo_seed.py)).

Остальные пользователи заводятся на `/users` (только `admin`).

## Если забыли пароль

**`/forgot-password`** — логин, свой контрольный вопрос, ответ, новый
пароль. Администратор не нужен, в этом и смысл вопроса. Ответ
сравнивается без учёта регистра и пробелов по краям.

**Лимит: 10 неудачных попыток на логин за 15 минут** блокируют и вход, и
восстановление — счётчик общий, потому что неверный ответ на контрольный
вопрос это такая же попытка подобрать доступ, как и неверный пароль
([`app/services/login_attempts.py`](app/services/login_attempts.py)).

Если вопрос не задан или пользователь деактивирован, восстановление
недоступно, и форма не уточняет, какая из причин, — иначе по ней можно
проверять существование логинов. Тогда:

1. **другой администратор** — `/users` → карточка → «Сбросить пароль»;
2. **администратор один и доступа нет** — командой в контейнере:

```bash
docker compose exec app python -c "
from getpass import getpass
from app.db import SessionLocal
from app.models import User
from app.services import users as users_service
db = SessionLocal()
admin = db.query(User).filter_by(username='admin').one()
users_service.reset_password(db, actor=admin, target=admin, new_password=getpass('Новый пароль: '))
print('Пароль обновлён.')
"
```

Через сервис, а не прямой записью хеша, — чтобы сброс попал в
`audit_log` наравне с остальными.

## Карта интерфейса

| Адрес | Что там | Код |
|---|---|---|
| `/` | дашборд: изделия, поиск, сортировка | [`routers/search.py`](app/routers/search.py) |
| `/platforms` → `/platforms/{id}` | платформы и их исполнения | [`routers/platforms.py`](app/routers/platforms.py) |
| `/variants/{id}` | конструктор исполнения: элементы, требования по прошивкам и MAC | [`routers/platform_variants.py`](app/routers/platform_variants.py) |
| `/items/{id}` | карточка изделия: комплектность, компоненты, этапы, прошивки, MAC, файлы, выгрузка в JSON | [`routers/platform_items.py`](app/routers/platform_items.py) |
| `/part-units/unowned` | детали, не установленные никуда | [`routers/part_units.py`](app/routers/part_units.py) |
| `/part-categories`, `/firmware-types` | пользовательские каталоги | [`part_categories.py`](app/routers/part_categories.py), [`firmware_types.py`](app/routers/firmware_types.py) |
| `/users` | пользователи, только `admin` | [`routers/users.py`](app/routers/users.py) |
| `/api-tokens` | выпуск и отзыв токенов, только `admin` | [`routers/api_tokens.py`](app/routers/api_tokens.py) |
| `/account/security-question` | свой контрольный вопрос | [`routers/account.py`](app/routers/account.py) |

Иерархия строго вложенная: **Платформа → Исполнение → Изделие**. Деталь
заводится неявно, в момент установки на изделие.

## JSON API

Машинный интерфейс к тем же данным — `/api/v1`, **27 операций**: весь
цикл от создания платформы до отгрузки и удаления. Реализация —
[`app/routers/api_v1.py`](app/routers/api_v1.py), схемы —
[`app/schemas/api.py`](app/schemas/api.py), полный каталог с границами и
ролями — [AGENTS.md → «Что агент может через
API»](AGENTS.md).

**По умолчанию выключен**: пока не выпущено ни одного токена, отвечает
`api_disabled`.

Ключевое при использовании:

- вызывает **те же сервисы**, что и веб, — порядок этапов, блокировка
  состава, аудит действуют одинаково, обойти правило через API нельзя;
- у каждой записи есть `"dry_run": true` — все проверки выполняются
  по-настоящему, в транзакции, которая откатывается;
- коды и подписи разделены: `"status": "assembled"` — контракт,
  `"status_label": "Укомплектовано"` — для человека;
- ошибки машинно-читаемые, с подсказкой:

  ```json
  { "error": { "code": "components_locked",
               "message": "The item is marked assembled, so its component list is locked.",
               "hint": "Record a 'disassembled' event via POST /api/v1/items/{id}/events to reopen it." } }
  ```

Схема для генерации инструментов — `/openapi.json`.

### Выпустить токен

1. Завести пользователя на `/users` — например `api`, роль `engineer`
   (или `viewer`, если нужно только чтение).
2. `/api-tokens` → название, от чьего имени, роль → «Создать».
3. Скопировать. **Показывается один раз**: в базе только хеш.

Перезапускать приложение не нужно. Из CLI то же самое —
[`app/create_api_token.py`](app/create_api_token.py):

```bash
docker compose exec app python -m app.create_api_token \
    --name "агент LangChain" --user api --role engineer
docker compose exec app python -m app.create_api_token --list
```

Проверить:

```bash
curl -H "Authorization: Bearer stk_..." \
     "http://localhost:8000/api/v1/search?q=DEMO-CPU-0001"
```

### Роль и пользователь токена

Работают обе. **Роль** решает, что токен может: `viewer` — чтение без
коммерческих полей, `engineer` — плюс запись. **Пользователь** даёт
токену личность: он пишется автором в `audit_log`, так что «кто установил
компонент» остаётся отвечаемым и когда это сделал агент.

Роль токена никогда не выше роли его пользователя. Понизили или
деактивировали пользователя — все его токены ограничились вместе с ним,
искать их не нужно. Отзыв — кнопка на `/api-tokens`, действует немедленно
и только на один токен.

Реализация — [`app/services/api_tokens.py`](app/services/api_tokens.py),
проверка на запросе — [`app/api_auth.py`](app/api_auth.py).

## LLM-агент

[`agent/`](agent/) — ассистент на LangChain поверх API: девять
инструментов, локальная модель через Ollama, переключение на внешнюю
одной переменной окружения. Не часть приложения, а его потребитель: свои
зависимости, `app/` его не импортирует.

- как пользоваться, с разбором живых сессий — [agent/GUIDE.md](agent/GUIDE.md)
- как устроен и почему так — [agent/README.md](agent/README.md)
- пример реальной сессии целиком — [report.md](report.md)

## Разработка и тесты

```bash
./scripts/test-api.sh              # весь набор
./scripts/test-api.sh -k dry_run   # одна группа
./scripts/test-api.sh -v           # подробно
```

Тесты идут против **настоящего приложения на одноразовой базе** — скрипт
создаёт её, применяет миграции, засевает демо-пример и потом удаляет.
Рабочие данные не затрагиваются.

Мок-сервера нет намеренно: он был бы второй реализацией того же
контракта и разошёлся бы с первой — с итогом «в моке работает, на
реальном API падает». Подробнее —
[`tests/conftest.py`](tests/conftest.py).

[`tests/test_api_contract.py`](tests/test_api_contract.py) фиксирует то,
на что опирается потребитель: имена полей, коды ошибок, форму конверта,
формат дат и то, что `dry_run` ничего не пишет. Там же проверяется, что
каталог эндпоинтов в `AGENTS.md` совпадает с реализацией — забытое
обновление документации роняет сборку.

Тесты агента отдельно, без модели и без сервера:

```bash
cd agent && .venv/bin/python -m pytest test_agent.py -q
```

Локальная разработка без Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # включает requirements.txt
```

## Бэкапы

БД — источник истины по производству, бэкапы обязательны.
[`scripts/backup.sh`](scripts/backup.sh) дампит БД (`pg_dump`, gzip),
архивирует загруженные файлы и ротирует — оставляет последние
`BACKUP_RETENTION` копий (по умолчанию 10; при запуске раз в 3 дня это
около месяца истории).

```bash
./scripts/backup.sh
```

Раз в 3 дня через cron на хосте:

```cron
0 3 */3 * * cd /path/to/server-tracker && ./scripts/backup.sh >> /var/log/server-tracker-backup.log 2>&1
```

Или systemd-таймером — [`scripts/systemd/README.md`](scripts/systemd/README.md);
юниты в репозитории заготовлены, но не включены, накатывать руками.

**Храните копии вне сервера** (второй хост, S3, что угодно): локальная
копия на том же диске не защищает от отказа диска или машины целиком.

Автозапуск при перезагрузке — заготовка
[`scripts/systemd/server-tracker.service`](scripts/systemd/server-tracker.service),
тоже не установлена.

## Чего ещё нет

- Отдельного CRUD для деталей в вебе — деталь заводится неявно, при
  установке на изделие. Есть только список бесхозных и удаление.
- Импорта и табличного экспорта. Выгрузка одного изделия в JSON есть —
  `/items/{id}/export`, пачкой и в CSV/XLSX нет.
- Фильтров на дашборде (в API они есть — `GET /api/v1/items`).

Приоритеты и открытые вопросы по правилам процесса — roadmap в конце
[AGENTS.md](AGENTS.md).
