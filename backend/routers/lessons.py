import shutil
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File

from config import UPLOAD_DIR
from db import get_conn
from auth import require_parent, require_any
from models.lessons import LessonIn

router = APIRouter(prefix="/api")

# ── Lessons ───────────────────────────────────────────────────────────────────

@router.get("/lessons")
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

@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@router.post("/lessons")
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

@router.put("/lessons/{lesson_id}")
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

@router.delete("/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET active=0 WHERE id=?", (lesson_id,))
    conn.commit(); conn.close()
    return {"ok": True}

# ── Upload ────────────────────────────────────────────────────────────────────

@router.delete("/lessons/{lesson_id}/infographic")
def clear_infographic(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET infographic=NULL WHERE id=?", (lesson_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.post("/lessons/{lesson_id}/upload-audio")
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

@router.post("/lessons/{lesson_id}/upload-image")
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
