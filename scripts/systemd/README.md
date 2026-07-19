# systemd-юниты (не применены, только заготовка)

Эти файлы никуда не установлены и не включены — просто лежат в
репозитории, чтобы админ мог их скопировать и включить на реальном
сервере вручную, когда решит, что пора.

- `server-tracker.service` — поднимает `docker compose up -d` при
  старте системы и опускает `docker compose down` при остановке.
- `server-tracker-backup.service` + `.timer` — прогоняет
  `scripts/backup.sh` каждые 3 дня (через `OnUnitActiveSec=3d`,
  `Persistent=true` — если сервер был выключен в момент срабатывания,
  бэкап выполнится вскоре после следующей загрузки).

## Установка (вручную, на целевом сервере)

1. В обоих `.service`-файлах поменять `WorkingDirectory=/opt/server-tracker`
   на реальный путь, куда склонирован проект.
2. Скопировать все три файла в `/etc/systemd/system/`:
   ```bash
   sudo cp scripts/systemd/server-tracker.service \
           scripts/systemd/server-tracker-backup.service \
           scripts/systemd/server-tracker-backup.timer \
           /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
3. Включить автостart приложения:
   ```bash
   sudo systemctl enable --now server-tracker.service
   ```
4. Включить таймер бэкапов (сам сервис `server-tracker-backup.service`
   не enable'ится — им управляет таймер):
   ```bash
   sudo systemctl enable --now server-tracker-backup.timer
   ```
5. Проверить:
   ```bash
   systemctl status server-tracker.service
   systemctl list-timers server-tracker-backup.timer
   ```
