# Чек-лист боевого сервера: бэкапы и мониторинг

Всё ниже — для одной папки салона на сервере в РФ (например `/root/salon-parik`). Для каждого следующего салона на том же сервере повторить пункты 2–4 в его папке.

## 1. Сервер и связь с Telegram

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/kkkarumi/parik-bot.git /root/salon-parik
cd /root/salon-parik
./setup.sh                      # спросит токен, название, адрес релея
docker compose exec backend python -m app.manage check-telegram
docker compose ps               # backend и bot должны быть (healthy) через 1–2 минуты
```

Если `check-telegram` не OK — поднять релей по [relay/README.md](../relay/README.md) и вписать `TELEGRAM_API_BASE`.

**Порт 8000 наружу не открываем.** В `docker-compose.yml` у бэкенда нет `ports:` — так и оставить: бот ходит в API по внутренней сети Docker.

## 2. Бэкапы

```bash
./scripts/install-cron.sh       # ежедневный бэкап в 04:15, можно запускать повторно — дублей не будет
./scripts/backup.sh             # первый бэкап прямо сейчас
./scripts/restore-test.sh       # ОДИН РАЗ обязательно: бэкап реально восстанавливается?
```

`restore-test.sh` поднимает временный Postgres, заливает в него последний бэкап и печатает число клиентов и записей. Рабочую базу не трогает. Повторяйте раз в месяц и после крупных обновлений.

**Копия вне сервера** (если сервер умрёт целиком, локальные бэкапы умрут вместе с ним):

1. Поставить rclone: `curl https://rclone.org/install.sh | sudo bash`
2. `rclone config` → добавить хранилище (S3-совместимое и т. п.), назвать, например, `s3remote`.
3. В `.env`: `BACKUP_REMOTE=s3remote:имя-бакета/parik`
4. `./scripts/backup.sh` → в конце должно быть `OK: копия в …`.

Важно:
- В бэкапе — имена и телефоны клиентов. Хранилище лучше **в РФ** (⚠️ проверить у провайдера, где физически лежат данные), иначе это трансграничная передача. Плюс можно включить шифрование: в rclone это remote типа `crypt` поверх обычного ([rclone.org/crypt](https://rclone.org/crypt/)) — тогда `BACKUP_REMOTE=имя-crypt-remote:parik`. Пароль от crypt хранить отдельно от сервера.
- Старые копии в хранилище скрипт не удаляет. Настройте срок хранения в самом хранилище (lifecycle-правило, например 60 дней) или чистите руками.
- Если копия наружу не ушла, `backup.sh` завершается с кодом 3 и пишет `ВНИМАНИЕ` в `backups/backup.log`. `update.sh` при этом продолжает работу (локальный бэкап есть).

## 3. Мониторинг «салон жив»

Безопасная схема без открытия портов: **push-мониторинг**. Сервер сам раз в минуту «отмечается» у внешнего мониторинга, если всё в порядке. Нет отметок N минут — мониторинг шлёт вам тревогу.

`scripts/heartbeat.sh` пингует `HEARTBEAT_URL`, только если:
- API отвечает на `/health` (проверка изнутри контейнера, порт наружу не нужен);
- контейнер бота `healthy` — значит, `getUpdates` доходит до Telegram/релея (heartbeat-файл свежий).

Если бот завис, нет связи с релеем, упал бэкенд или весь сервер, пинги прекращаются → тревога.

### Вариант А: Uptime Kuma на VPS релея (рекомендуемый)

Релей и так за границей и доступен с российского сервера, а сам Kuma оттуда может слать тревоги в Telegram напрямую.

⚠️ Uptime Kuma просит больше памяти, чем Caddy: на VPS с 512 МБ может быть тесно — проверьте `free -m` после запуска, при нехватке возьмите тариф с 1 ГБ.

1. На VPS релея добавьте в `relay/docker-compose.yml` сервис (не включён по умолчанию):
   ```yaml
     uptime-kuma:
       image: louislam/uptime-kuma:1
       restart: unless-stopped
       volumes: [kuma_data:/app/data]
   ```
   и `kuma_data:` в раздел `volumes:`. В `relay/Caddyfile` — отдельный поддомен (A-запись на тот же IP):
   ```
   kuma.example.com {
   	reverse_proxy uptime-kuma:3001
   }
   ```
   `docker compose up -d`, открыть `https://kuma.example.com`, создать пользователя с надёжным паролем.
2. **Add New Monitor** → тип **Push** → Heartbeat Interval 60 с, Retries 2–3 (чтобы перезапуск контейнеров не будил вас ночью). Скопировать Push URL.
3. **Settings → Notifications → Telegram**: токен *отдельного* бота для тревог (создать в @BotFather) и ваш chat id. Привязать уведомление к монитору. Нажать «Test».
4. На сервере салона в `.env`: `HEARTBEAT_URL=<Push URL>` и:
   ```bash
   ./scripts/heartbeat.sh && echo пинг-ушёл
   ./scripts/install-cron.sh       # добавит пинг раз в минуту
   ```
5. Проверка тревоги: `docker compose stop bot`, через 2–4 минуты должна прийти тревога; `docker compose start bot` — «снова в строю».

### Вариант Б: внешний сервис

Подойдёт любой сервис с «heartbeat / push / cron-мониторами», куда сервер раз в минуту делает GET (healthchecks.io, UptimeRobot heartbeat и т. п.). ⚠️ проверить: доступен ли сервис с российского сервера, есть ли такой тип мониторинга на бесплатном тарифе, умеет ли он слать тревоги в Telegram. Дальше так же: `HEARTBEAT_URL` в `.env` и `./scripts/install-cron.sh`.

## 4. Ошибки (Sentry, по желанию)

1. Завести проект на sentry.io (Python), взять DSN.
2. `.env`: `SENTRY_DSN=…`, затем `docker compose up -d`.
3. Ошибки бота и бэкенда приходят туда. Телефоны, токены, ключ API и секрет релея вырезаются перед отправкой, переменные из трейсбеков не отправляются. Но Sentry — сервис за рубежом: см. `docs/legal/поручение_обработки_пдн.md`.
4. Если бэкенд 5 раз подряд не смог отправить сообщение в Telegram, в Sentry придёт одна ошибка «Telegram недоступен».

## 5. Регулярно

| Когда | Что |
|---|---|
| Раз в неделю | `docker compose logs --since 168h bot backend \| grep -iE "error\|warning" \| tail -50`, письма Sentry |
| Раз в месяц | `./scripts/restore-test.sh`, место на диске `df -h`, `apt upgrade` |
| При обновлении | `./scripts/update.sh` (сам сделает бэкап) |

## 6. Демо-бот (для показа клиентам)

Отдельная папка и отдельный бот в @BotFather:

```bash
git clone https://github.com/kkkarumi/parik-bot.git /root/demo-bot && cd /root/demo-bot
./setup.sh                                   # на вопрос про демо-данные ответить y
echo "DEMO_MODE=1" >> .env && docker compose up -d
./scripts/install-cron.sh                    # увидит DEMO_MODE=1 и добавит ночной сброс в 04:45
docker compose exec backend python -m app.manage reset-demo   # сбросить прямо сейчас
```

В демо-режиме рассылка по клиентам отключена, а `reset-demo` без `DEMO_MODE=1` откажется работать — боевой салон им не стереть.
