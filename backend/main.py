from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os, jwt, shutil, re, json
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import httpx, asyncio

from config import UPLOAD_DIR, SECRET_KEY, SUBJECT_LABELS, MATERIAL_SUBJECTS
from db import get_conn, migrate_add_column, init_db, parse_curriculum_text

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

# ── Telegram ──────────────────────────────────────────────────────────────────

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

# ── Auth ──────────────────────────────────────────────────────────────────────

security = HTTPBearer()

def make_token(role: str) -> str:
    payload = {"role": role, "exp": datetime.utcnow() + timedelta(days=30)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def get_role(creds: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        data = jwt.decode(creds.credentials, SECRET_KEY, algorithms=["HS256"])
        return data["role"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_parent(role: str = Depends(get_role)):
    if role != "parent":
        raise HTTPException(status_code=403, detail="Parent only")
    return role

def require_any(role: str = Depends(get_role)):
    return role

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ── Health / Config ───────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    p = os.environ.get("PARENT_PASSWORD", "parent123")
    c = os.environ.get("CHILD_PASSWORD",  "child123")
    return {"ok": True, "parent_pass_len": len(p), "child_pass_len": len(c)}

@app.get("/api/config")
def config():
    return {
        "child_name": os.environ.get("CHILD_NAME", "Тимофей"),
        "child_grade": int(os.environ.get("CHILD_GRADE", "5")),
        "subjects": SUBJECT_LABELS,
    }

# ── Settings (тема/оформление интерфейса) ───────────────────────────────────────

@app.get("/api/settings")
def read_settings():
    conn = get_conn(); s = get_settings(conn); conn.close()
    return s

class SettingsIn(BaseModel):
    site_name: Optional[str] = None
    logo_url: Optional[str] = None
    logo_size: Optional[int] = None
    favicon_url: Optional[str] = None
    bg_main: Optional[str] = None
    bg_hero: Optional[str] = None
    bg_lesson_of_day: Optional[str] = None
    bg_subject_page: Optional[str] = None
    sidebar_left_url: Optional[str] = None
    sidebar_right_url: Optional[str] = None
    subject_icons: Optional[dict] = None
    font_heading: Optional[str] = None
    font_body: Optional[str] = None
    color_accent: Optional[str] = None
    color_accent2: Optional[str] = None
    sound_correct: Optional[str] = None
    sound_wrong: Optional[str] = None

@app.put("/api/settings")
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

@app.post("/api/settings/reset")
def reset_settings(role: str = Depends(require_parent)):
    conn = get_conn()
    save_settings(conn, dict(DEFAULT_SETTINGS))
    conn.commit(); conn.close()
    return dict(DEFAULT_SETTINGS)

SOUND_SLOTS = ("sound_correct", "sound_wrong")

@app.post("/api/settings/upload")
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

class TelegramConfigIn(BaseModel):
    tg_bot_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    site_url: Optional[str] = None

@app.get("/api/integrations/telegram")
def get_telegram_settings(role: str = Depends(require_parent)):
    conn = get_conn()
    cfg = get_telegram_config(conn)
    conn.close()
    return cfg

@app.put("/api/integrations/telegram")
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

@app.post("/api/integrations/telegram/test")
async def test_telegram(role: str = Depends(require_parent)):
    child = os.environ.get("CHILD_NAME", "Тимофей")
    ok, error = await tg_send_result(
        f"🔔 Тестовое сообщение от EduQuest.\nЕсли ты это видишь — интеграция с Telegram настроена верно! "
        f"Уведомления про {child} будут приходить сюда."
    )
    if not ok:
        raise HTTPException(400, error or "Не удалось отправить сообщение")
    return {"ok": True}

# ── Login ─────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    password: str
    role: str

@app.post("/api/login")
def login(data: LoginIn):
    parent_pass = os.environ.get("PARENT_PASSWORD", "parent123")
    child_pass  = os.environ.get("CHILD_PASSWORD",  "child123")
    expected = parent_pass if data.role == "parent" else child_pass
    if data.password.strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": make_token(data.role), "role": data.role}

# ── Curriculum: Класс → Предмет → Раздел → Тема ─────────────────────────────────

class SectionIn(BaseModel):
    grade: int
    subject: str
    title: str
    order_index: int = 0
    intro: Optional[str] = None

class TopicIn(BaseModel):
    section_id: int
    title: str
    order_index: int = 0

@app.get("/api/curriculum")
def get_curriculum(grade: int, subject: str, role: str = Depends(require_any)):
    """Полное дерево разделов и тем предмета — общая картина для планирования уроков."""
    conn = get_conn()
    sections = conn.execute(
        "SELECT * FROM sections WHERE grade=? AND subject=? ORDER BY order_index, id",
        (grade, subject)
    ).fetchall()
    result = []
    for s in sections:
        topics = conn.execute(
            "SELECT * FROM topics WHERE section_id=? ORDER BY order_index, id", (s["id"],)
        ).fetchall()
        topic_list = []
        for t in topics:
            t_lessons = conn.execute(
                "SELECT id, topic, infographic, lesson_type, slides FROM lessons WHERE topic_id=? AND active=1 ORDER BY created_at", (t["id"],)
            ).fetchall()
            lesson_ids = [l["id"] for l in t_lessons]
            completed = False
            stars = 0
            if lesson_ids:
                placeholders = ",".join("?" * len(lesson_ids))
                cnt = conn.execute(
                    f"SELECT COUNT(*) as n FROM progress WHERE lesson_id IN ({placeholders}) AND finished_at IS NOT NULL",
                    lesson_ids
                ).fetchone()["n"]
                completed = cnt > 0
                if completed:
                    best = conn.execute(
                        f"SELECT MAX(score*1.0/max_score) as pct FROM progress WHERE lesson_id IN ({placeholders}) AND finished_at IS NOT NULL AND max_score > 0",
                        lesson_ids
                    ).fetchone()["pct"]
                    pct = best or 0
                    stars = 3 if pct >= 0.9 else 2 if pct >= 0.6 else 1
            topic_list.append({
                **dict(t),
                "lessons": [dict(l) for l in t_lessons],
                "lesson_count": len(t_lessons),
                "completed": completed,
                "stars": stars,
            })
        result.append({**dict(s), "intro_done": bool(s["intro_seen_at"]), "topics": topic_list})
    conn.close()
    return {"grade": grade, "subject": subject, "sections": result}

@app.get("/api/sections/{section_id}")
def get_section(section_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    s = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
    conn.close()
    if not s:
        raise HTTPException(404, "Not found")
    return {**dict(s), "intro_done": bool(s["intro_seen_at"])}

@app.post("/api/sections/{section_id}/intro-done")
def complete_intro(section_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    conn.execute("UPDATE sections SET intro_seen_at=datetime('now') WHERE id=?", (section_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/sections")
def create_section(data: SectionIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO sections (grade,subject,title,order_index,intro) VALUES (?,?,?,?,?)",
              (data.grade, data.subject, data.title, data.order_index, data.intro))
    sid = c.lastrowid; conn.commit(); conn.close()
    return {"id": sid}

@app.put("/api/sections/{section_id}")
def update_section(section_id: int, data: SectionIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE sections SET grade=?,subject=?,title=?,order_index=?,intro=? WHERE id=?",
                 (data.grade, data.subject, data.title, data.order_index, data.intro, section_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/sections/{section_id}")
def delete_section(section_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    topic_ids = [r["id"] for r in conn.execute("SELECT id FROM topics WHERE section_id=?", (section_id,)).fetchall()]
    if topic_ids:
        conn.execute("UPDATE lessons SET topic_id=NULL WHERE topic_id IN (%s)" % ",".join("?"*len(topic_ids)), topic_ids)
        conn.execute("DELETE FROM topics WHERE section_id=?", (section_id,))
    conn.execute("DELETE FROM sections WHERE id=?", (section_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/topics")
def create_topic(data: TopicIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
              (data.section_id, data.title, data.order_index))
    tid = c.lastrowid; conn.commit(); conn.close()
    return {"id": tid}

@app.put("/api/topics/{topic_id}")
def update_topic(topic_id: int, data: TopicIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE topics SET section_id=?,title=?,order_index=? WHERE id=?",
                 (data.section_id, data.title, data.order_index, topic_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/topics/{topic_id}")
def delete_topic(topic_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET topic_id=NULL WHERE topic_id=?", (topic_id,))
    conn.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/topics/{topic_id}")
def get_topic(topic_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    t = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if not t:
        conn.close(); raise HTTPException(404, "Not found")
    s = conn.execute("SELECT * FROM sections WHERE id=?", (t["section_id"],)).fetchone()
    lessons = conn.execute("SELECT * FROM lessons WHERE topic_id=? AND active=1 ORDER BY created_at", (topic_id,)).fetchall()
    conn.close()
    return {**dict(t), "section": dict(s) if s else None, "lessons": [dict(l) for l in lessons]}

class ImportCurriculumIn(BaseModel):
    grade: int
    subject: str
    text: str

@app.post("/api/curriculum/import")
def import_curriculum(data: ImportCurriculumIn, role: str = Depends(require_parent)):
    """Импорт программы из текста в формате:
       **1. Раздел**
       - **Тема:** описание...
       Повторный импорт безопасен — существующие разделы/темы (по совпадению названия) не дублируются."""
    parsed = parse_curriculum_text(data.text)
    if not parsed:
        raise HTTPException(400, "Не удалось распознать структуру. Формат: **1. Раздел** и пункты - **Тема:** описание")
    conn = get_conn()
    existing_sections = {r["title"]: r["id"] for r in conn.execute(
        "SELECT id, title FROM sections WHERE grade=? AND subject=?", (data.grade, data.subject)).fetchall()}
    base_order = len(existing_sections)
    sections_created, topics_created = 0, 0
    for i, sec in enumerate(parsed):
        if sec["title"] in existing_sections:
            sid = existing_sections[sec["title"]]
        else:
            c = conn.cursor()
            c.execute("INSERT INTO sections (grade,subject,title,order_index) VALUES (?,?,?,?)",
                      (data.grade, data.subject, sec["title"], base_order + i))
            sid = c.lastrowid
            existing_sections[sec["title"]] = sid
            sections_created += 1
        existing_topics = {r["title"] for r in conn.execute(
            "SELECT title FROM topics WHERE section_id=?", (sid,)).fetchall()}
        topic_base = conn.execute("SELECT COUNT(*) as n FROM topics WHERE section_id=?", (sid,)).fetchone()["n"]
        added = 0
        for t_title in sec["topics"]:
            if t_title in existing_topics:
                continue
            conn.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
                         (sid, t_title, topic_base + added))
            added += 1
        topics_created += added
    conn.commit(); conn.close()
    return {"sections_found": len(parsed), "sections_created": sections_created, "topics_created": topics_created}

# ── Lessons ───────────────────────────────────────────────────────────────────

class LessonIn(BaseModel):
    subject: str
    grade: int = 4
    topic: str
    topic_id: Optional[int] = None
    context_theme: str = "minecraft"
    explanation: str = ""
    explanation_game: str = ""
    questions: Optional[str] = None
    boss_task: Optional[str] = None
    coins_lesson: int = 50
    coins_boss: int = 30

@app.get("/api/lessons")
def list_lessons(subject: Optional[str] = None, topic_id: Optional[int] = None, role: str = Depends(require_any)):
    conn = get_conn()
    q = """SELECT l.*,
                  s.id           AS section_id,
                  s.title        AS section_title,
                  s.order_index  AS section_order,
                  t.title        AS topic_title,
                  t.order_index  AS topic_order
           FROM lessons l
           LEFT JOIN topics t   ON t.id = l.topic_id
           LEFT JOIN sections s ON s.id = t.section_id
           WHERE l.active=1"""
    params = []
    if subject:
        q += " AND l.subject=?"; params.append(subject)
    if topic_id:
        q += " AND l.topic_id=?"; params.append(topic_id)
    rows = conn.execute(q + " ORDER BY l.subject, s.order_index, t.order_index, l.created_at", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/lessons/{lesson_id}")
def get_lesson(lesson_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@app.post("/api/lessons")
def create_lesson(data: LessonIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO lessons
        (subject,grade,topic,topic_id,context_theme,explanation,explanation_game,questions,boss_task,coins_lesson,coins_boss)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (data.subject, data.grade, data.topic, data.topic_id, data.context_theme,
         data.explanation, data.explanation_game,
         data.questions, data.boss_task, data.coins_lesson, data.coins_boss))
    lid = c.lastrowid; conn.commit(); conn.close()
    return {"id": lid}

@app.put("/api/lessons/{lesson_id}")
def update_lesson(lesson_id: int, data: LessonIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("""UPDATE lessons SET subject=?,grade=?,topic=?,topic_id=?,context_theme=?,
        explanation=?,explanation_game=?,questions=?,boss_task=?,coins_lesson=?,coins_boss=?
        WHERE id=?""",
        (data.subject, data.grade, data.topic, data.topic_id, data.context_theme,
         data.explanation, data.explanation_game,
         data.questions, data.boss_task, data.coins_lesson, data.coins_boss, lesson_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET active=0 WHERE id=?", (lesson_id,))
    conn.commit(); conn.close()
    return {"ok": True}

# ── Upload ────────────────────────────────────────────────────────────────────

@app.delete("/api/lessons/{lesson_id}/infographic")
def clear_infographic(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET infographic=NULL WHERE id=?", (lesson_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/lessons/{lesson_id}/upload-audio")
async def upload_audio(lesson_id: int, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "ogg", "wav", "m4a"):
        raise HTTPException(400, "Unsupported format")
    fpath = f"{UPLOAD_DIR}/audio/lesson_{lesson_id}.{ext}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    conn = get_conn()
    conn.execute("UPDATE lessons SET audio_file=? WHERE id=?",
                 (f"/uploads/audio/lesson_{lesson_id}.{ext}", lesson_id))
    conn.commit(); conn.close()
    return {"audio_file": f"/uploads/audio/lesson_{lesson_id}.{ext}"}

@app.post("/api/lessons/{lesson_id}/upload-image")
async def upload_image(lesson_id: int, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        raise HTTPException(400, "Unsupported format")
    fpath = f"{UPLOAD_DIR}/images/lesson_{lesson_id}.{ext}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    conn = get_conn()
    conn.execute("UPDATE lessons SET infographic=? WHERE id=?",
                 (f"/uploads/images/lesson_{lesson_id}.{ext}", lesson_id))
    conn.commit(); conn.close()
    return {"infographic": f"/uploads/images/lesson_{lesson_id}.{ext}"}

# ── Articles (познавательные материалы — без контроля знаний) ────────────────────

class ArticleIn(BaseModel):
    subject: str
    grade: Optional[int] = None
    title: str
    summary: Optional[str] = None
    cover_image: Optional[str] = None
    blocks: list

@app.get("/api/materials/subjects")
def material_subjects(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT subject, COUNT(*) as cnt FROM articles WHERE active=1 GROUP BY subject"
    ).fetchall()
    counts = {r["subject"]: r["cnt"] for r in rows}
    conn.close()
    return [{"key": k, "label": v, "count": counts.get(k, 0)} for k, v in MATERIAL_SUBJECTS.items()]

@app.get("/api/articles")
def list_articles(subject: Optional[str] = None, role: str = Depends(require_any)):
    conn = get_conn()
    q = "SELECT id, subject, grade, title, summary, cover_image, created_at FROM articles WHERE active=1"
    params = []
    if subject:
        q += " AND subject=?"; params.append(subject)
    rows = conn.execute(q + " ORDER BY created_at DESC", params).fetchall()
    ids = [r["id"] for r in rows]
    read_ids = set()
    if ids:
        placeholders = ",".join("?" * len(ids))
        read_ids = {r["article_id"] for r in conn.execute(
            f"SELECT DISTINCT article_id FROM article_reads WHERE article_id IN ({placeholders})", ids
        ).fetchall()}
    conn.close()
    return [{**dict(r), "read": r["id"] in read_ids} for r in rows]

@app.get("/api/articles/{article_id}")
def get_article(article_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    d = dict(row)
    try: d["blocks"] = json.loads(d["blocks"])
    except Exception: d["blocks"] = []
    return d

@app.post("/api/articles")
def create_article(data: ArticleIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO articles (subject,grade,title,summary,cover_image,blocks,manually_edited) VALUES (?,?,?,?,?,?,1)",
              (data.subject, data.grade, data.title, data.summary, data.cover_image,
               json.dumps(data.blocks, ensure_ascii=False)))
    conn.commit(); aid = c.lastrowid; conn.close()
    return {"id": aid}

@app.put("/api/articles/{article_id}")
def update_article(article_id: int, data: ArticleIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET subject=?,grade=?,title=?,summary=?,cover_image=?,blocks=?,manually_edited=1 WHERE id=?",
                 (data.subject, data.grade, data.title, data.summary, data.cover_image,
                  json.dumps(data.blocks, ensure_ascii=False), article_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/articles/{article_id}")
def delete_article(article_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET active=0 WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/articles/deleted/list")
def list_deleted_articles(role: str = Depends(require_parent)):
    """Диагностика: показывает материалы, помеченные как удалённые (active=0), чтобы можно было
       убедиться, что материал действительно удалён, восстановить его или убрать навсегда."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, subject, grade, title, summary, cover_image, created_at FROM articles WHERE active=0 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/articles/{article_id}/restore")
def restore_article(article_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET active=1 WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/articles/{article_id}/purge")
def purge_article(article_id: int, role: str = Depends(require_parent)):
    """Безвозвратное удаление строки из БД (в отличие от обычного DELETE, который только
       помечает active=0). Используется, чтобы окончательно убрать дубликаты/мусорные записи."""
    conn = get_conn()
    conn.execute("DELETE FROM articles WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/articles/{article_id}/read")
def mark_article_read(article_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    already = conn.execute("SELECT id FROM article_reads WHERE article_id=?", (article_id,)).fetchone()
    if not already:
        conn.execute("INSERT INTO article_reads (article_id) VALUES (?)", (article_id,))
        conn.commit()
    conn.close()
    return {"ok": True}


# ── Рассылка материалов «на изучение» через Telegram ────────────────────────

import random as _random

def pick_next_articles(conn, n: int = 3):
    """Выбирает следующие n материалов для отправки так, чтобы они не повторялись,
    пока не будут отправлены все существующие материалы хотя бы по разу. Приоритет:
    сначала те, что ещё никогда не отправлялись (в случайном порядке), затем —
    отправленные раньше всех остальных (по дате последней отправки, от старых к новым)."""
    active_ids = [r["id"] for r in conn.execute("SELECT id FROM articles WHERE active=1").fetchall()]
    if not active_ids:
        return []
    rows = conn.execute("""
        SELECT maa.article_id as article_id, MAX(a.sent_at) as last_sent
        FROM material_assignment_articles maa
        JOIN material_assignments a ON a.id = maa.assignment_id
        GROUP BY maa.article_id
    """).fetchall()
    last_sent = {r["article_id"]: r["last_sent"] for r in rows}
    never_sent = [a for a in active_ids if a not in last_sent]
    _random.shuffle(never_sent)
    already_sent_sorted = sorted(
        (a for a in active_ids if a in last_sent),
        key=lambda a: last_sent[a]
    )
    ordered = never_sent + already_sent_sorted
    return ordered[:n]

class MaterialAssignmentIn(BaseModel):
    coins_reward: int = 30
    count: int = 3

@app.post("/api/materials/assignments")
async def create_material_assignment(data: MaterialAssignmentIn, role: str = Depends(require_parent)):
    conn = get_conn()
    article_ids = pick_next_articles(conn, max(1, min(data.count, 10)))
    if not article_ids:
        conn.close()
        raise HTTPException(400, "Нет ни одного материала, чтобы отправить")
    articles = conn.execute(
        f"SELECT id, title FROM articles WHERE id IN ({','.join('?' * len(article_ids))})", article_ids
    ).fetchall()
    titles_by_id = {r["id"]: r["title"] for r in articles}
    ordered_titles = [titles_by_id[a] for a in article_ids if a in titles_by_id]

    c = conn.cursor()
    c.execute(
        "INSERT INTO material_assignments (article_ids, coins_reward) VALUES (?,?)",
        (json.dumps(article_ids), data.coins_reward)
    )
    assignment_id = c.lastrowid
    for aid in article_ids:
        c.execute("INSERT INTO material_assignment_articles (assignment_id, article_id) VALUES (?,?)", (assignment_id, aid))
    conn.commit()

    cfg = get_telegram_config(conn)
    child = os.environ.get("CHILD_NAME", "Тимофей")
    link = f"{cfg['site_url']}/materials/assignment/{assignment_id}"
    topics_text = "\n".join(f"🔹 {t}" for t in ordered_titles)
    message = (
        f"Привет, {child}! 👋😊\n\n"
        f"📚✨ Сегодня тебе нужно узнать кое-что новое!\n"
        f"{topics_text}\n\n"
        f"🧐 Ознакомься и перескажи родителям, о чём ты узнал.\n"
        f"🏆 Награда: {data.coins_reward} 🪙 монет.\n\n"
        f"🔗 Вот ссылка на материалы: {link}"
    )
    ok, error = await tg_send_result(message)
    conn.execute("UPDATE material_assignments SET telegram_ok=?, telegram_error=? WHERE id=?",
                 (1 if ok else 0, error, assignment_id))
    conn.commit()
    conn.close()
    return {
        "id": assignment_id, "titles": ordered_titles, "coins_reward": data.coins_reward,
        "link": link, "telegram_ok": ok, "telegram_error": error,
    }

@app.get("/api/materials/assignments")
def list_material_assignments(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM material_assignments ORDER BY sent_at DESC LIMIT 60").fetchall()
    result = []
    for r in rows:
        ids = json.loads(r["article_ids"])
        titles = []
        if ids:
            arts = conn.execute(
                f"SELECT id, title FROM articles WHERE id IN ({','.join('?' * len(ids))})", ids
            ).fetchall()
            by_id = {a["id"]: a["title"] for a in arts}
            titles = [by_id.get(i, f"(материал {i} удалён)") for i in ids]
        result.append({
            "id": r["id"], "titles": titles, "coins_reward": r["coins_reward"],
            "sent_at": r["sent_at"], "completed_at": r["completed_at"],
            "telegram_ok": bool(r["telegram_ok"]), "telegram_error": r["telegram_error"],
        })
    conn.close()
    return result

@app.get("/api/materials/assignments/{assignment_id}")
def get_material_assignment(assignment_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    a = conn.execute("SELECT * FROM material_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not a:
        conn.close(); raise HTTPException(404, "Задание не найдено")
    ids = json.loads(a["article_ids"])
    articles = []
    for aid in ids:
        row = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        if not row:
            continue
        d = dict(row)
        try: d["blocks"] = json.loads(d["blocks"])
        except Exception: d["blocks"] = []
        articles.append(d)
    conn.close()
    return {
        "id": a["id"], "articles": articles, "coins_reward": a["coins_reward"],
        "sent_at": a["sent_at"], "completed_at": a["completed_at"],
    }

@app.post("/api/materials/assignments/{assignment_id}/complete")
async def complete_material_assignment(assignment_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    a = conn.execute("SELECT * FROM material_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not a:
        conn.close(); raise HTTPException(404, "Задание не найдено")
    if a["completed_at"]:
        conn.close()
        return {"ok": True, "already_completed": True, "coins_earned": 0}
    conn.execute("UPDATE material_assignments SET completed_at=datetime('now') WHERE id=?", (assignment_id,))
    coins = a["coins_reward"] or 0
    if coins > 0:
        conn.execute("INSERT INTO coins (amount,type,note) VALUES (?,?,?)",
                     (coins, "earned", "Изучение познавательных материалов"))
    conn.commit()
    ids = json.loads(a["article_ids"])
    titles = []
    if ids:
        arts = conn.execute(f"SELECT title FROM articles WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        titles = [r["title"] for r in arts]
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"📚✅ <b>{child} изучил материалы и рассказал о них!</b>\n"
        f"Темы: {', '.join(titles)}\n+{coins} 🪙 монет"
    ))
    return {"ok": True, "already_completed": False, "coins_earned": coins}



class StartLessonIn(BaseModel):
    lesson_id: int

def _number_group_pattern(digits: str) -> str:
    """Строит паттерн для целой части числа, где между группами по 3 цифры
    (справа налево) допускается необязательный пробел — обычный или
    неразрывный. Это нужно, чтобы «987650» засчитывался и как «987650»,
    и как «987 650» (привычная запись больших чисел с разделением разрядов
    пробелом), без чего верные ответы с пробелом ошибочно считались неверными."""
    rev = digits[::-1]
    chunks = [rev[i:i + 3][::-1] for i in range(0, len(rev), 3)]
    chunks = chunks[::-1]
    return r"[ \u00a0]?".join(re.escape(c) for c in chunks)


def _number_pattern(num: str) -> str:
    if "." in num:
        int_part, frac_part = num.split(".", 1)
        return _number_group_pattern(int_part) + r"[.,]" + re.escape(frac_part)
    return _number_group_pattern(num)


def _check_boss_answer(expected: str, given: str) -> bool:
    """Сверяет ответ ребёнка на финальное задание с эталонным ответом.
    Числа сверяются как отдельные "слова" (без ложных совпадений внутри
    других чисел), текстовые ответы — по вхождению как отдельного слова."""
    if not expected or not given:
        return False
    given_norm = given.strip().lower().replace(",", ".")
    numbers = re.findall(r"-?\d+(?:[.,]\d+)?", expected)
    if numbers:
        numbers_norm = [n.replace(",", ".") for n in numbers]

        def present(num: str) -> bool:
            pat = r"(?<!\d)" + _number_pattern(num) + r"(?!\d)"
            return bool(re.search(pat, given_norm))

        if all(present(n) for n in numbers_norm):
            return True
        # Иногда эталон формулируется как "промежуточный результат, итоговый код",
        # где итоговое число буквально составлено из цифр промежуточного
        # (например, "5 целых 1/6, код 516" — код 516 включает цифры 5, 1 и 6).
        # В этом случае ребёнок, назвавший только итоговое число, прав — но
        # проверка выше не засчитает это, так как цифры 5/1/6 внутри "516" не
        # являются отдельными "словами". Разрешаем такой ответ отдельно: если
        # самое длинное число эталона само присутствует в ответе как отдельное
        # число, а все остальные числа эталона целиком состоят из его цифр
        # (т.е. являются его частью), засчитываем ответ.
        longest = max(numbers_norm, key=len)
        others = [n for n in numbers_norm if n != longest]
        if others and all(n in longest for n in others) and present(longest):
            return True
        return False
    exp_norm = expected.strip().lower()
    pat = r"(?<!\w)" + re.escape(exp_norm) + r"(?!\w)"
    return bool(re.search(pat, given_norm, flags=re.UNICODE))


class FinishLessonIn(BaseModel):
    progress_id: int
    score: int
    total: int = 5
    boss_done: bool = False
    boss_answer: Optional[str] = None



@app.post("/api/progress/start")
async def start_lesson(data: StartLessonIn, role: str = Depends(require_any)):
    conn = get_conn()
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (data.lesson_id,)).fetchone()
    if not lesson:
        conn.close(); raise HTTPException(404, "Lesson not found")
    c = conn.cursor()
    c.execute("INSERT INTO progress (lesson_id) VALUES (?)", (data.lesson_id,))
    pid = c.lastrowid; conn.commit(); conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"📚 <b>{child} начал урок</b>\n"
        f"Предмет: {SUBJECT_LABELS.get(lesson['subject'], lesson['subject'])}\n"
        f"Тема: {lesson['topic']}"
    ))
    return {"progress_id": pid}

@app.post("/api/progress/finish")
async def finish_lesson(data: FinishLessonIn, role: str = Depends(require_any)):
    conn = get_conn()
    prog   = conn.execute("SELECT * FROM progress WHERE id=?", (data.progress_id,)).fetchone()
    if not prog:
        conn.close(); raise HTTPException(404)
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (prog["lesson_id"],)).fetchone()
    # Монеты за урок пропорциональны результату: score/total карточек.
    # Одна неверная карточка = минус (coins_lesson / total) монет — весомее, чем плоский штраф.
    max_score = data.total if data.total and data.total > 0 else 5
    ratio = max(data.score / max_score, 0.1) if max_score > 0 else 0.1
    base_coins = lesson["coins_lesson"] if lesson else 50
    lesson_coins = max(round(base_coins * ratio), 5)  # минимум 5 монет
    # Финальное задание: ответ ребёнка сверяется с эталонным на сервере —
    # клиенту нельзя доверять флаг "выполнено правильно"
    boss_correct = False
    if data.boss_done and lesson and lesson["boss_task"]:
        try:
            boss = json.loads(lesson["boss_task"])
        except Exception:
            boss = None
        expected = (boss or {}).get("answer")
        if expected:
            boss_correct = _check_boss_answer(expected, data.boss_answer or "")
    boss_coins = (lesson["coins_boss"] if lesson else 30) if boss_correct else 0
    coins = lesson_coins + boss_coins
    conn.execute("UPDATE progress SET finished_at=datetime('now'),score=?,max_score=?,boss_done=?,coins_earned=? WHERE id=?",
                 (data.score, max_score, 1 if boss_correct else 0, coins, data.progress_id))
    conn.execute("INSERT INTO coins (amount,type,note) VALUES (?,?,?)",
                 (coins, "earned", f"Урок: {lesson['topic'] if lesson else ''}"))
    _update_streak(conn); conn.commit()
    streak = conn.execute("SELECT days FROM streak WHERE id=1").fetchone()
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"✅ <b>{child} завершил урок!</b>\n"
        f"Тема: {lesson['topic'] if lesson else ''}\n"
        f"Результат: {data.score}/5 · +{coins} монет 🪙\n"
        f"Серия: {streak['days'] if streak else 0} дней 🔥"
    ))
    return {"coins_earned": coins, "boss_correct": boss_correct, "lesson_coins": lesson_coins, "boss_coins": boss_coins}

def _update_streak(conn):
    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
    if row["last_day"] == today:
        return
    new_days = (row["days"] + 1) if row["last_day"] == yesterday else 1
    conn.execute("UPDATE streak SET days=?,last_day=? WHERE id=1", (new_days, today))

@app.get("/api/progress")
def get_progress(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("""SELECT p.*, l.topic, l.subject FROM progress p
        LEFT JOIN lessons l ON p.lesson_id=l.id
        ORDER BY p.started_at DESC LIMIT 50""").fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Навыки (логические/классические задачи — картинка + до 3 подсказок) ────────

class SkillCategoryIn(BaseModel):
    title: str

class SkillIn(BaseModel):
    category_id: int
    image_url: Optional[str] = None
    hint1: Optional[str] = None
    hint2: Optional[str] = None
    hint3: Optional[str] = None
    answer: Optional[str] = None

@app.get("/api/skill-categories")
def list_skill_categories(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, order_index FROM skill_categories WHERE active=1 ORDER BY order_index, id"
    ).fetchall()
    counts_rows = conn.execute(
        "SELECT category_id, COUNT(*) as cnt FROM skills WHERE active=1 GROUP BY category_id"
    ).fetchall()
    conn.close()
    counts = {r["category_id"]: r["cnt"] for r in counts_rows}
    return [{**dict(r), "count": counts.get(r["id"], 0)} for r in rows]

@app.post("/api/skill-categories")
def create_skill_category(data: SkillCategoryIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    max_order = c.execute("SELECT MAX(order_index) as m FROM skill_categories").fetchone()["m"]
    c.execute("INSERT INTO skill_categories (title, order_index) VALUES (?,?)",
              (data.title, (max_order or 0) + 1))
    conn.commit(); cid = c.lastrowid; conn.close()
    return {"id": cid}

@app.put("/api/skill-categories/{category_id}")
def update_skill_category(category_id: int, data: SkillCategoryIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET title=? WHERE id=?", (data.title, category_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/skill-categories/{category_id}")
def delete_skill_category(category_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET active=0 WHERE id=?", (category_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/skill-categories/{category_id}/restore")
def restore_skill_category(category_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET active=1 WHERE id=?", (category_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/skill-categories/deleted/list")
def list_deleted_skill_categories(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, order_index FROM skill_categories WHERE active=0 ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/skills")
def list_skills(category_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, category_id, image_url, hint1, hint2, hint3, answer, order_index FROM skills "
        "WHERE active=1 AND category_id=? ORDER BY order_index, id",
        (category_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/skills/all-active")
def list_all_active_skills(role: str = Depends(require_any)):
    """Все активные задания вместе с названием категории — для слайдшоу (перемешивание
       по категориям делается на фронтенде, как и в MaterialsSlideshowPage)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT sk.id, sk.category_id, sk.image_url, sk.hint1, sk.hint2, sk.hint3, sk.answer, sc.title as category_title
        FROM skills sk
        JOIN skill_categories sc ON sc.id = sk.category_id
        WHERE sk.active=1 AND sc.active=1
        ORDER BY sk.order_index, sk.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@app.post("/api/skills")
def create_skill(data: SkillIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    max_order = c.execute(
        "SELECT MAX(order_index) as m FROM skills WHERE category_id=?", (data.category_id,)
    ).fetchone()["m"]
    c.execute(
        "INSERT INTO skills (category_id,image_url,hint1,hint2,hint3,answer,order_index) VALUES (?,?,?,?,?,?,?)",
        (data.category_id, data.image_url, data.hint1, data.hint2, data.hint3, data.answer, (max_order or 0) + 1)
    )
    conn.commit(); sid = c.lastrowid; conn.close()
    return {"id": sid}

@app.put("/api/skills/{skill_id}")
def update_skill(skill_id: int, data: SkillIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute(
        "UPDATE skills SET category_id=?,image_url=?,hint1=?,hint2=?,hint3=?,answer=? WHERE id=?",
        (data.category_id, data.image_url, data.hint1, data.hint2, data.hint3, data.answer, skill_id)
    )
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skills SET active=0 WHERE id=?", (skill_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/skills/{skill_id}/restore")
def restore_skill(skill_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skills SET active=1 WHERE id=?", (skill_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/skills/deleted/list")
def list_deleted_skills(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT sk.id, sk.category_id, sk.image_url, sk.hint1, sk.hint2, sk.hint3, sc.title as category_title
        FROM skills sk
        LEFT JOIN skill_categories sc ON sc.id = sk.category_id
        WHERE sk.active=0
        ORDER BY sk.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(role: str = Depends(require_any)):
    conn = get_conn()
    total   = conn.execute("SELECT COUNT(*) as n FROM progress WHERE finished_at IS NOT NULL").fetchone()["n"]
    earned  = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent   = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    streak  = conn.execute("SELECT days FROM streak WHERE id=1").fetchone()
    avg_row = conn.execute("SELECT AVG(score*1.0/max_score) as a FROM progress WHERE finished_at IS NOT NULL").fetchone()
    by_subj = conn.execute("""SELECT l.subject, COUNT(*) as cnt, AVG(p.score*1.0/p.max_score) as avg
        FROM progress p JOIN lessons l ON p.lesson_id=l.id WHERE p.finished_at IS NOT NULL
        GROUP BY l.subject""").fetchall()
    week    = conn.execute("""SELECT date(started_at) as day, COUNT(*) as cnt
        FROM progress WHERE started_at >= date('now','-7 days')
        GROUP BY date(started_at) ORDER BY day""").fetchall()
    weak_from_mistakes = conn.execute("""
        SELECT l.id as lesson_id, l.topic, l.subject, COUNT(m.id) as mistake_count, MAX(m.created_at) as last_at
        FROM mistakes m JOIN lessons l ON m.lesson_id = l.id
        WHERE l.active=1
        GROUP BY l.id
        ORDER BY last_at DESC
        LIMIT 8
    """).fetchall()
    weak_from_score = conn.execute("""SELECT l.id as lesson_id, l.topic, l.subject, AVG(p.score*1.0/p.max_score) as avg, COUNT(*) as attempts
        FROM progress p JOIN lessons l ON p.lesson_id=l.id WHERE p.finished_at IS NOT NULL AND l.active=1
        GROUP BY l.id HAVING avg < 0.6 AND attempts >= 1 ORDER BY avg ASC LIMIT 5""").fetchall()
    seen, weak_topics = set(), []
    for r in weak_from_mistakes:
        if r["lesson_id"] in seen: continue
        seen.add(r["lesson_id"])
        weak_topics.append({
            "lesson_id": r["lesson_id"], "topic": r["topic"], "subject": r["subject"],
            "mistake_count": r["mistake_count"], "avg": None,
        })
    for r in weak_from_score:
        if r["lesson_id"] in seen: continue
        seen.add(r["lesson_id"])
        weak_topics.append({
            "lesson_id": r["lesson_id"], "topic": r["topic"], "subject": r["subject"],
            "mistake_count": None, "avg": r["avg"],
        })
    weak_topics = weak_topics[:6]
    conn.close()
    return {
        "total_lessons": total, "balance": earned - spent,
        "total_coins_earned": earned, "streak_days": streak["days"] if streak else 0,
        "avg_score": round(avg_row["a"] * 100) if avg_row["a"] else 0,
        "by_subject": [dict(r) for r in by_subj],
        "week_activity": [dict(r) for r in week],
        "weak_topics": weak_topics,
    }

# ── Coins & Rewards ───────────────────────────────────────────────────────────

@app.get("/api/coins/balance")
def get_balance(role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent  = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    conn.close()
    return {"balance": earned - spent, "earned": earned, "spent": spent}

class MistakeIn(BaseModel):
    lesson_id: int
    question_text: Optional[str] = None
    chosen_text: Optional[str] = None
    correct_text: Optional[str] = None

@app.post("/api/mistakes")
def log_mistake(data: MistakeIn, role: str = Depends(require_any)):
    """Фиксирует неверный ответ на карточке — без начисления/списания монет,
    только для сбора статистики по проблемным темам (родитель видит, что подтянуть)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO mistakes (lesson_id, question_text, chosen_text, correct_text) VALUES (?,?,?,?)",
        (data.lesson_id, data.question_text, data.chosen_text, data.correct_text)
    )
    conn.commit(); conn.close()
    return {"ok": True}

def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11: return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14): return few
    return many

@app.get("/api/lessons/{lesson_id}/reinforcement-prompt")
def reinforcement_prompt(lesson_id: int, role: str = Depends(require_parent)):
    """Собирает по уроку (тема, где ребёнок ошибается) готовый текстовый запрос, который родитель
    может скопировать и прислать Claude в чат, чтобы тот написал дополнительный урок-закрепление
    в код и задеплоил — контент уроков в проекте принципиально не редактируется через UI-формы
    (см. CONTEXT_FOR_CLAUDE.md), поэтому этот эндпоинт не создаёт урок сам, а только готовит
    контекст (тему, раздел, конкретные ошибки, статистику) для человека-в-цикле."""
    conn = get_conn()
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    if not lesson:
        conn.close(); raise HTTPException(404, "Урок не найден")

    section_title = None
    if lesson["topic_id"]:
        srow = conn.execute("""
            SELECT s.title as section_title FROM topics t JOIN sections s ON t.section_id = s.id
            WHERE t.id=?
        """, (lesson["topic_id"],)).fetchone()
        if srow:
            section_title = srow["section_title"]

    prog = conn.execute("""
        SELECT COUNT(*) as attempts, AVG(score*1.0/max_score) as avg
        FROM progress WHERE lesson_id=? AND finished_at IS NOT NULL
    """, (lesson_id,)).fetchone()

    mistakes = conn.execute("""
        SELECT question_text, chosen_text, correct_text FROM mistakes
        WHERE lesson_id=? ORDER BY created_at DESC LIMIT 15
    """, (lesson_id,)).fetchall()
    conn.close()

    lines = ["Материал для урока закрепления (на основе ошибок ребёнка)", ""]
    lines.append(f"Предмет: {SUBJECT_LABELS.get(lesson['subject'], lesson['subject'])} ({lesson['grade']} класс)")
    if section_title:
        lines.append(f"Раздел: {section_title}")
    lines.append(f"Тема: {lesson['topic']} (урок id {lesson_id})")

    if prog and prog["attempts"]:
        att = prog["attempts"]
        lines.append(f"Точность по теме: {round((prog['avg'] or 0) * 100)}% ({att} {_plural_ru(att, 'попытка', 'попытки', 'попыток')})")

    lines.append("")
    if mistakes:
        lines.append(f"Конкретные ошибки ({len(mistakes)}):")
        for i, m in enumerate(mistakes, 1):
            parts = []
            if m["question_text"]: parts.append(f"вопрос «{m['question_text']}»")
            if m["chosen_text"]:   parts.append(f"ответил «{m['chosen_text']}»")
            if m["correct_text"]:  parts.append(f"правильно «{m['correct_text']}»")
            lines.append(f"{i}. " + ", ".join(parts))
    else:
        lines.append("Отдельные вопросы с ошибками не зафиксированы — тема попала в слабые по среднему баллу за попытки.")

    lines.append("")
    lines.append(
        f"Задача: добавь дополнительный урок «Закрепление: {lesson['topic']}»"
        + (f" в раздел «{section_title}»" if section_title else "")
        + ", с другими конкретными числами/примерами, но тем же навыком — так, чтобы закрепить "
          "именно то, в чём были ошибки выше. Добавь через seed_topic_if_missing + "
          "seed_lesson_if_missing (в конец раздела), сохрани формат LESSON_DICT, сюжетную линию "
          "и общий тон уроков проекта (см. docs/CONTEXT_FOR_CLAUDE.md). После — задеплой."
    )
    return {"prompt": "\n".join(lines)}

@app.get("/api/mistakes")
def list_mistakes(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.id, m.question_text, m.chosen_text, m.correct_text, m.created_at,
               l.id as lesson_id, l.topic, l.subject
        FROM mistakes m JOIN lessons l ON m.lesson_id = l.id
        ORDER BY m.created_at DESC LIMIT 200
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

class PenaltyIn(BaseModel):
    lesson_id: Optional[int] = None
    amount: int = 5
    note: Optional[str] = None

@app.post("/api/coins/penalty")
def coin_penalty(data: PenaltyIn, role: str = Depends(require_any)):
    """Списывает монеты сразу за неверный ответ — стимулирует отвечать вдумчивее."""
    conn = get_conn()
    amt = -abs(data.amount)
    conn.execute("INSERT INTO coins (amount,type,note) VALUES (?,?,?)",
                 (amt, "earned", data.note or "Штраф за неверный ответ"))
    conn.commit()
    earned = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent  = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    conn.close()
    return {"balance": earned - spent, "penalty": abs(amt)}

class RewardIn(BaseModel):
    name: str
    cost_coins: int

@app.post("/api/rewards/request")
async def request_reward(data: RewardIn, role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent  = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    if earned - spent < data.cost_coins:
        conn.close(); raise HTTPException(400, f"Недостаточно монет")
    conn.execute("INSERT INTO rewards (name,cost_coins) VALUES (?,?)", (data.name, data.cost_coins))
    conn.commit()
    cfg = get_telegram_config(conn)
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"🎁 <b>{child} запрашивает награду!</b>\n"
        f"{data.name} · {data.cost_coins} монет 🪙\n"
        f"{cfg['site_url']}"
    ))
    return {"ok": True}

@app.get("/api/rewards")
def get_rewards(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM rewards ORDER BY requested_at DESC LIMIT 30").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/rewards/{reward_id}/approve")
async def approve_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    r = conn.execute("SELECT * FROM rewards WHERE id=?", (reward_id,)).fetchone()
    if not r:
        conn.close(); raise HTTPException(404)
    conn.execute("UPDATE rewards SET status='approved',approved_at=datetime('now') WHERE id=?", (reward_id,))
    conn.commit(); conn.close()
    asyncio.create_task(tg_send(f"✅ Одобрено: <b>{r['name']}</b> ({r['cost_coins']} монет)"))
    return {"ok": True}

@app.post("/api/rewards/{reward_id}/reject")
def reject_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE rewards SET status='rejected' WHERE id=?", (reward_id,))
    conn.commit(); conn.close()
    return {"ok": True}
