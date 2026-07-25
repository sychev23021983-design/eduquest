import os, json
import httpx

from db import get_conn

# Интеграции (Telegram и т.п.) хранятся отдельно от site_settings, потому что
# /api/settings отдаётся без авторизации (используется для оформления интерфейса
# на странице логина) — токен бота там светить нельзя. Всё, что лежит в
# integrations, доступно только через parent-эндпоинты.
DEFAULT_INTEGRATIONS = {
    "tg_bot_token": "",
    "tg_chat_id": "",
    "site_url": "",
}

def get_integrations(conn):
    row = conn.execute("SELECT data FROM integrations WHERE id=1").fetchone()
    stored = json.loads(row["data"]) if row and row["data"] else {}
    return {**DEFAULT_INTEGRATIONS, **stored}

def save_integrations(conn, data: dict):
    conn.execute("UPDATE integrations SET data=? WHERE id=1", (json.dumps(data, ensure_ascii=False),))

def get_telegram_config(conn):
    """Токен/chat_id берутся из настроек (кабинет родителя → Настройки → Telegram),
    а если там пусто — из переменных окружения (старый способ, для обратной совместимости)."""
    integ = get_integrations(conn)
    return {
        "bot_token": integ.get("tg_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id":   integ.get("tg_chat_id")   or os.environ.get("TELEGRAM_CHAT_ID", ""),
        "site_url":  (integ.get("site_url") or os.environ.get("SITE_URL", "") or "http://147.45.42.169:8090").rstrip("/"),
    }

async def tg_send_result(text: str):
    """Отправляет сообщение и возвращает (ok, error) — используется там, где нужно
    показать родителю результат сразу (тест интеграции, рассылка материалов)."""
    conn = get_conn()
    cfg = get_telegram_config(conn)
    conn.close()
    token, chat = cfg["bot_token"], cfg["chat_id"]
    if not token or not chat or token == "YOUR_BOT_TOKEN_HERE":
        return False, "Telegram не настроен — заполни токен бота и chat_id в Настройках"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            )
        if resp.status_code != 200:
            detail = None
            try: detail = resp.json().get("description")
            except Exception: pass
            return False, detail or f"Telegram вернул ошибку {resp.status_code}"
        return True, None
    except Exception as e:
        return False, str(e)

async def tg_send(text: str):
    """Отправка «в фоне», без ожидания результата — как и раньше, ошибки просто проглатываются."""
    try:
        await tg_send_result(text)
    except Exception:
        pass
