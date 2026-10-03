# Booking bot (bot + API)

    cp .env.example .env          # вписать BOT_TOKEN, ключ, ADMIN_CHAT_ID
    docker compose up -d --build
    docker compose exec backend python -m app.seed   # демо-салон, мастера, услуги

Новый клиент = копия папки/`.env` с другим BOT_TOKEN и `docker compose -p <client> up -d`.
