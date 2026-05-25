# EduQuest 🎓

Образовательное приложение для детей с геймификацией, системой монет и Telegram-уведомлениями.

## Стек
- **Backend**: FastAPI + SQLite
- **Frontend**: React + Vite
- **Deploy**: Docker Compose

## Порты
- Frontend: `0.0.0.0:8090`
- Backend: `127.0.0.1:8091` (только localhost)

## Деплой на VPS

```bash
cd /root
git clone https://github.com/sychev23021983-design/eduquest
cd eduquest
# Отредактируй переменные окружения в docker-compose.yml
docker compose up -d --build
```

## Настройка Telegram-бота

1. Создай бота через @BotFather в Telegram
2. Получи токен и свой chat_id (через @userinfobot)
3. Вставь в `docker-compose.yml`:
   - `TELEGRAM_BOT_TOKEN=твой_токен`
   - `TELEGRAM_CHAT_ID=твой_chat_id`
4. Задеплой заново: `docker compose up -d --force-recreate`

## Пароли по умолчанию

- Родитель: `parent123`
- Ребёнок: `child123`

Измени в `docker-compose.yml` перед деплоем.
