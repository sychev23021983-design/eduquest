import os, shutil, re, json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File

from config import UPLOAD_DIR
from db import get_conn
from auth import require_parent
from telegram_service import get_integrations, save_integrations, get_telegram_config, tg_send_result
from models.settings import SettingsIn, TelegramConfigIn

router = APIRouter(prefix="/api")

DEFAULT_SETTINGS = {
    "site_name": "EduQuest",
    "logo_url": None,
    "logo_size": 28,
    "favicon_url": None,
    "bg_main": None,
    "bg_hero": None,
    "bg_lesson_of_day": None,
    "bg_subject_page": None,
    "sidebar_left_url": None,
    "sidebar_right_url": None,
    "subject_icons": {"math": None, "russian": None, "science": None, "history": None, "academy": None},
    "font_heading": "Nunito",
    "font_body": "Nunito",
    "color_accent": "#4da3ff",
    "color_accent2": "#22d38b",
    "sound_correct": None,
    "sound_wrong": None,
}

FONT_CHOICES = ["Nunito", "Rubik", "Montserrat", "PT Sans", "Comfortaa", "Ubuntu"]

def get_settings(conn):
    row = conn.execute("SELECT data FROM site_settings WHERE id=1").fetchone()
    stored = json.loads(row["data"]) if row and row["data"] else {}
    merged = {**DEFAULT_SETTINGS, **stored}
    merged["subject_icons"] = {**DEFAULT_SETTINGS["subject_icons"], **(stored.get("subject_icons") or {})}
    return merged

def save_settings(conn, data: dict):
    conn.execute("UPDATE site_settings SET data=? WHERE id=1", (json.dumps(data, ensure_ascii=False),))

# ── Settings (тема/оформление интерфейса) ───────────────────────────────────────

@router.get("/settings")
def read_settings():
    conn = get_conn(); s = get_settings(conn); conn.close()
    return s

@router.put("/settings")
def update_settings(data: SettingsIn, role: str = Depends(require_parent)):
    conn = get_conn()
    current = get_settings(conn)
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if "subject_icons" in updates:
        current["subject_icons"] = {**current["subject_icons"], **updates.pop("subject_icons")}
    current.update(updates)
    save_settings(conn, current)
    conn.commit(); conn.close()
    return current

@router.post("/settings/reset")
def reset_settings(role: str = Depends(require_parent)):
    conn = get_conn()
    save_settings(conn, dict(DEFAULT_SETTINGS))
    conn.commit(); conn.close()
    return dict(DEFAULT_SETTINGS)

SOUND_SLOTS = ("sound_correct", "sound_wrong")

@router.post("/settings/upload")
async def upload_setting_asset(slot: str, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    safe_slot = re.sub(r"[^a-z0-9_]", "", slot.lower())
    if not safe_slot:
        raise HTTPException(400, "Bad slot")
    if safe_slot in SOUND_SLOTS:
        if ext not in ("mp3", "wav", "ogg", "m4a"):
            raise HTTPException(400, "Unsupported format")
    else:
        if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg", "ico"):
            raise HTTPException(400, "Unsupported format")
    fpath = f"{UPLOAD_DIR}/site/{safe_slot}.{ext}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    url = f"/uploads/site/{safe_slot}.{ext}?v={int(datetime.utcnow().timestamp())}"
    conn = get_conn()
    current = get_settings(conn)
    if safe_slot.startswith("subject_"):
        current["subject_icons"][safe_slot.replace("subject_", "")] = url
    else:
        current[safe_slot] = url
    save_settings(conn, current)
    conn.commit(); conn.close()
    return current

# ── Интеграции (Telegram) ────────────────────────────────────────────────────

@router.get("/integrations/telegram")
def get_telegram_settings(role: str = Depends(require_parent)):
    conn = get_conn()
    cfg = get_telegram_config(conn)
    conn.close()
    return cfg

@router.put("/integrations/telegram")
def update_telegram_settings(data: TelegramConfigIn, role: str = Depends(require_parent)):
    conn = get_conn()
    current = get_integrations(conn)
    updates = {k: v for k, v in data.dict().items() if v is not None}
    current.update(updates)
    save_integrations(conn, current)
    conn.commit()
    cfg = get_telegram_config(conn)
    conn.close()
    return cfg

@router.post("/integrations/telegram/test")
async def test_telegram(role: str = Depends(require_parent)):
    child = os.environ.get("CHILD_NAME", "Тимофей")
    ok, error = await tg_send_result(
        f"🔔 Тестовое сообщение от EduQuest.\nЕсли ты это видишь — интеграция с Telegram настроена верно! "
        f"Уведомления про {child} будут приходить сюда."
    )
    if not ok:
        raise HTTPException(400, error or "Не удалось отправить сообщение")
    return {"ok": True}
