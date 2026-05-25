from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import sqlite3, os, jwt, shutil, json
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import httpx, asyncio

DB_PATH        = os.getenv("DB_PATH",         "/app/data/eduquest.db")
SECRET_KEY     = os.getenv("SECRET_KEY",      "eduquest-secret-key-2026")
PARENT_PASS    = os.getenv("PARENT_PASSWORD", "parent123")
CHILD_PASS     = os.getenv("CHILD_PASSWORD",  "child123")
CHILD_NAME     = os.getenv("CHILD_NAME",      "Тимофей")
UPLOAD_DIR     = os.getenv("UPLOAD_DIR",      "/app/data/uploads")
TG_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID",   "")

# ── DB ────────────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(f"{UPLOAD_DIR}/audio", exist_ok=True)
    os.makedirs(f"{UPLOAD_DIR}/images", exist_ok=True)
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS lessons (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            subject       TEXT NOT NULL,
            grade         INTEGER NOT NULL DEFAULT 4,
            topic         TEXT NOT NULL,
            context_theme TEXT DEFAULT 'minecraft',
            explanation   TEXT,
            explanation_game TEXT,
            audio_file    TEXT,
            infographic   TEXT,
            questions     TEXT,
            boss_task     TEXT,
            coins_lesson  INTEGER DEFAULT 50,
            coins_boss    INTEGER DEFAULT 30,
            created_at    TEXT DEFAULT (datetime('now')),
            active        INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS progress (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id    INTEGER NOT NULL,
            started_at   TEXT DEFAULT (datetime('now')),
            finished_at  TEXT,
            score        INTEGER DEFAULT 0,
            max_score    INTEGER DEFAULT 5,
            coins_earned INTEGER DEFAULT 0,
            boss_done    INTEGER DEFAULT 0,
            FOREIGN KEY(lesson_id) REFERENCES lessons(id)
        );

        CREATE TABLE IF NOT EXISTS coins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            amount     INTEGER NOT NULL,
            type       TEXT NOT NULL,
            note       TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rewards (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            cost_coins   INTEGER NOT NULL,
            status       TEXT DEFAULT 'pending',
            requested_at TEXT DEFAULT (datetime('now')),
            approved_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS streak (
            id       INTEGER PRIMARY KEY CHECK (id = 1),
            days     INTEGER DEFAULT 0,
            last_day TEXT
        );

        INSERT OR IGNORE INTO streak(id, days, last_day) VALUES (1, 0, NULL);
    """)
    conn.commit()
    conn.close()

# ── Telegram ──────────────────────────────────────────────────────────────────

async def tg_send(text: str):
    if not TG_TOKEN or not TG_CHAT_ID or TG_TOKEN == "YOUR_BOT_TOKEN_HERE":
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
            )
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ── Login ─────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    password: str
    role: str  # "parent" | "child"

@app.post("/api/login")
def login(data: LoginIn):
    # Re-read env each request so changing docker-compose + recreate works instantly
    parent_pass = os.environ.get("PARENT_PASSWORD", "parent123")
    child_pass  = os.environ.get("CHILD_PASSWORD",  "child123")
    expected = parent_pass if data.role == "parent" else child_pass
    if data.password.strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": make_token(data.role), "role": data.role}

@app.get("/api/config")
def get_config():
    """Public config — child name, no secrets"""
    return {"child_name": os.environ.get("CHILD_NAME", "Тимофей")}

@app.get("/api/health")
def health():
    p = os.environ.get("PARENT_PASSWORD", "parent123")
    c = os.environ.get("CHILD_PASSWORD",  "child123")
    return {
        "ok": True,
        "parent_pass_set": p != "parent123",
        "child_pass_set":  c != "child123",
        "parent_pass_len": len(p),
        "child_pass_len":  len(c),
    }

# ── Lessons ───────────────────────────────────────────────────────────────────

SUBJECTS = ["math", "russian", "science", "history"]
SUBJECT_LABELS = {
    "math":    "Математика",
    "russian": "Русский язык",
    "science": "Окружающий мир",
    "history": "История"
}

class LessonIn(BaseModel):
    subject: str
    grade: int = 4
    topic: str
    context_theme: str = "minecraft"
    explanation: str = ""
    explanation_game: str = ""
    questions: Optional[str] = None
    boss_task: Optional[str] = None
    coins_lesson: int = 50
    coins_boss: int = 30

@app.get("/api/lessons")
def list_lessons(subject: Optional[str] = None, role: str = Depends(require_any)):
    conn = get_conn()
    q = "SELECT * FROM lessons WHERE active=1"
    params = []
    if subject:
        q += " AND subject=?"
        params.append(subject)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
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
    c.execute("""
        INSERT INTO lessons (subject, grade, topic, context_theme, explanation,
            explanation_game, questions, boss_task, coins_lesson, coins_boss)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (data.subject, data.grade, data.topic, data.context_theme,
          data.explanation, data.explanation_game,
          data.questions, data.boss_task,
          data.coins_lesson, data.coins_boss))
    lesson_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": lesson_id}

@app.put("/api/lessons/{lesson_id}")
def update_lesson(lesson_id: int, data: LessonIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("""
        UPDATE lessons SET subject=?, grade=?, topic=?, context_theme=?,
            explanation=?, explanation_game=?, questions=?, boss_task=?,
            coins_lesson=?, coins_boss=?
        WHERE id=?
    """, (data.subject, data.grade, data.topic, data.context_theme,
          data.explanation, data.explanation_game,
          data.questions, data.boss_task,
          data.coins_lesson, data.coins_boss, lesson_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET active=0 WHERE id=?", (lesson_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/lessons/{lesson_id}/upload-audio")
async def upload_audio(lesson_id: int, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "ogg", "wav", "m4a"):
        raise HTTPException(400, "Audio format not supported")
    fname = f"audio/lesson_{lesson_id}.{ext}"
    fpath = f"{UPLOAD_DIR}/{fname}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    conn = get_conn()
    conn.execute("UPDATE lessons SET audio_file=? WHERE id=?", (f"/uploads/{fname}", lesson_id))
    conn.commit()
    conn.close()
    return {"audio_file": f"/uploads/{fname}"}

@app.post("/api/lessons/{lesson_id}/upload-image")
async def upload_image(lesson_id: int, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        raise HTTPException(400, "Image format not supported")
    fname = f"images/lesson_{lesson_id}.{ext}"
    fpath = f"{UPLOAD_DIR}/{fname}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    conn = get_conn()
    conn.execute("UPDATE lessons SET infographic=? WHERE id=?", (f"/uploads/{fname}", lesson_id))
    conn.commit()
    conn.close()
    return {"infographic": f"/uploads/{fname}"}

# ── Progress ──────────────────────────────────────────────────────────────────

class StartLessonIn(BaseModel):
    lesson_id: int

class FinishLessonIn(BaseModel):
    progress_id: int
    score: int
    boss_done: bool = False

@app.post("/api/progress/start")
async def start_lesson(data: StartLessonIn, role: str = Depends(require_any)):
    conn = get_conn()
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (data.lesson_id,)).fetchone()
    if not lesson:
        conn.close()
        raise HTTPException(404, "Lesson not found")
    c = conn.cursor()
    c.execute("INSERT INTO progress (lesson_id) VALUES (?)", (data.lesson_id,))
    progress_id = c.lastrowid
    conn.commit()
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"📚 <b>{child} начал урок</b>\n"
        f"Предмет: {SUBJECT_LABELS.get(lesson['subject'], lesson['subject'])}\n"
        f"Тема: {lesson['topic']}"
    ))
    return {"progress_id": progress_id}

@app.post("/api/progress/finish")
async def finish_lesson(data: FinishLessonIn, role: str = Depends(require_any)):
    conn = get_conn()
    prog = conn.execute("SELECT * FROM progress WHERE id=?", (data.progress_id,)).fetchone()
    if not prog:
        conn.close()
        raise HTTPException(404)
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (prog["lesson_id"],)).fetchone()
    coins = lesson["coins_lesson"] if lesson else 50
    if data.boss_done:
        coins += lesson["coins_boss"] if lesson else 30
    conn.execute("""
        UPDATE progress SET finished_at=datetime('now'), score=?, boss_done=?, coins_earned=?
        WHERE id=?
    """, (data.score, 1 if data.boss_done else 0, coins, data.progress_id))
    conn.execute("INSERT INTO coins (amount, type, note) VALUES (?,?,?)",
                 (coins, "earned", f"Урок: {lesson['topic'] if lesson else ''}"))
    _update_streak(conn)
    conn.commit()
    streak_row = conn.execute("SELECT days FROM streak WHERE id=1").fetchone()
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"✅ <b>{child} завершил урок!</b>\n"
        f"Тема: {lesson['topic'] if lesson else ''}\n"
        f"Результат: {data.score}/5\n"
        f"Заработано: +{coins} монет 🪙\n"
        f"Серия: {streak_row['days'] if streak_row else 0} дней 🔥"
    ))
    return {"coins_earned": coins}

def _update_streak(conn):
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
    if row["last_day"] == today:
        return
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    new_days = (row["days"] + 1) if row["last_day"] == yesterday else 1
    conn.execute("UPDATE streak SET days=?, last_day=? WHERE id=1", (new_days, today))

@app.get("/api/progress")
def get_progress(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.*, l.topic, l.subject FROM progress p
        LEFT JOIN lessons l ON p.lesson_id = l.id
        ORDER BY p.started_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(role: str = Depends(require_any)):
    conn = get_conn()
    total_lessons = conn.execute(
        "SELECT COUNT(*) as n FROM progress WHERE finished_at IS NOT NULL"
    ).fetchone()["n"]
    total_coins_earned = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'"
    ).fetchone()["s"]
    total_coins_spent = conn.execute(
        "SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'"
    ).fetchone()["s"]
    balance   = total_coins_earned - total_coins_spent
    streak    = conn.execute("SELECT days FROM streak WHERE id=1").fetchone()
    avg_score = conn.execute(
        "SELECT AVG(score*1.0/max_score) as a FROM progress WHERE finished_at IS NOT NULL"
    ).fetchone()["a"]
    by_subject = conn.execute("""
        SELECT l.subject, COUNT(*) as cnt, AVG(p.score*1.0/p.max_score) as avg
        FROM progress p JOIN lessons l ON p.lesson_id=l.id
        WHERE p.finished_at IS NOT NULL GROUP BY l.subject
    """).fetchall()
    week_activity = conn.execute("""
        SELECT date(started_at) as day, COUNT(*) as cnt,
               SUM(CASE WHEN finished_at IS NOT NULL THEN 1 ELSE 0 END) as done
        FROM progress WHERE started_at >= date('now','-7 days')
        GROUP BY date(started_at) ORDER BY day
    """).fetchall()
    weak_topics = conn.execute("""
        SELECT l.topic, l.subject, AVG(p.score*1.0/p.max_score) as avg, COUNT(*) as attempts
        FROM progress p JOIN lessons l ON p.lesson_id=l.id
        WHERE p.finished_at IS NOT NULL
        GROUP BY l.id HAVING avg < 0.6 AND attempts >= 1
        ORDER BY avg ASC LIMIT 5
    """).fetchall()
    conn.close()
    return {
        "total_lessons":  total_lessons,
        "balance":        balance,
        "total_coins_earned": total_coins_earned,
        "streak_days":    streak["days"] if streak else 0,
        "avg_score":      round(avg_score * 100) if avg_score else 0,
        "by_subject":     [dict(r) for r in by_subject],
        "week_activity":  [dict(r) for r in week_activity],
        "weak_topics":    [dict(r) for r in weak_topics],
    }

# ── Coins & Rewards ───────────────────────────────────────────────────────────

@app.get("/api/coins/balance")
def get_balance(role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'"
    ).fetchone()["s"]
    spent = conn.execute(
        "SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'"
    ).fetchone()["s"]
    conn.close()
    return {"balance": earned - spent, "earned": earned, "spent": spent}

class RewardIn(BaseModel):
    name: str
    cost_coins: int

@app.post("/api/rewards/request")
async def request_reward(data: RewardIn, role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'"
    ).fetchone()["s"]
    spent = conn.execute(
        "SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'"
    ).fetchone()["s"]
    balance = earned - spent
    if balance < data.cost_coins:
        conn.close()
        raise HTTPException(400, f"Недостаточно монет. Баланс: {balance}")
    c = conn.cursor()
    c.execute("INSERT INTO rewards (name, cost_coins) VALUES (?,?)", (data.name, data.cost_coins))
    conn.commit()
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"🎁 <b>{child} запрашивает награду!</b>\n"
        f"Награда: {data.name}\n"
        f"Стоимость: {data.cost_coins} монет 🪙\n\n"
        f"Открой кабинет родителя чтобы одобрить: http://147.45.42.169:8090"
    ))
    return {"ok": True}

@app.get("/api/rewards")
def get_rewards(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM rewards ORDER BY requested_at DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/rewards/{reward_id}/approve")
async def approve_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    reward = conn.execute("SELECT * FROM rewards WHERE id=?", (reward_id,)).fetchone()
    if not reward:
        conn.close()
        raise HTTPException(404)
    conn.execute(
        "UPDATE rewards SET status='approved', approved_at=datetime('now') WHERE id=?",
        (reward_id,)
    )
    conn.commit()
    conn.close()
    asyncio.create_task(tg_send(
        f"✅ Награда одобрена: <b>{reward['name']}</b> ({reward['cost_coins']} монет)"
    ))
    return {"ok": True}

@app.post("/api/rewards/{reward_id}/reject")
def reject_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE rewards SET status='rejected' WHERE id=?", (reward_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
