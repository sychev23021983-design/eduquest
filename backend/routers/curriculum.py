from fastapi import APIRouter, HTTPException, Depends

from db import get_conn, parse_curriculum_text
from auth import require_parent, require_any
from models.curriculum import SectionIn, TopicIn, ImportCurriculumIn

router = APIRouter(prefix="/api")

# ── Curriculum: Класс → Предмет → Раздел → Тема ─────────────────────────────────

@router.get("/curriculum")
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

@router.get("/sections/{section_id}")
def get_section(section_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    s = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
    conn.close()
    if not s:
        raise HTTPException(404, "Not found")
    return {**dict(s), "intro_done": bool(s["intro_seen_at"])}

@router.post("/sections/{section_id}/intro-done")
def complete_intro(section_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    conn.execute("UPDATE sections SET intro_seen_at=datetime('now') WHERE id=?", (section_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.post("/sections")
def create_section(data: SectionIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO sections (grade,subject,title,order_index,intro) VALUES (?,?,?,?,?)",
              (data.grade, data.subject, data.title, data.order_index, data.intro))
    sid = c.lastrowid; conn.commit(); conn.close()
    return {"id": sid}

@router.put("/sections/{section_id}")
def update_section(section_id: int, data: SectionIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE sections SET grade=?,subject=?,title=?,order_index=?,intro=? WHERE id=?",
                 (data.grade, data.subject, data.title, data.order_index, data.intro, section_id))
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/sections/{section_id}")
def delete_section(section_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    topic_ids = [r["id"] for r in conn.execute("SELECT id FROM topics WHERE section_id=?", (section_id,)).fetchall()]
    if topic_ids:
        conn.execute("UPDATE lessons SET topic_id=NULL WHERE topic_id IN (%s)" % ",".join("?"*len(topic_ids)), topic_ids)
        conn.execute("DELETE FROM topics WHERE section_id=?", (section_id,))
    conn.execute("DELETE FROM sections WHERE id=?", (section_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.post("/topics")
def create_topic(data: TopicIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
              (data.section_id, data.title, data.order_index))
    tid = c.lastrowid; conn.commit(); conn.close()
    return {"id": tid}

@router.put("/topics/{topic_id}")
def update_topic(topic_id: int, data: TopicIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE topics SET section_id=?,title=?,order_index=? WHERE id=?",
                 (data.section_id, data.title, data.order_index, topic_id))
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET topic_id=NULL WHERE topic_id=?", (topic_id,))
    conn.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.get("/topics/{topic_id}")
def get_topic(topic_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    t = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if not t:
        conn.close(); raise HTTPException(404, "Not found")
    s = conn.execute("SELECT * FROM sections WHERE id=?", (t["section_id"],)).fetchone()
    lessons = conn.execute("SELECT * FROM lessons WHERE topic_id=? AND active=1 ORDER BY created_at", (topic_id,)).fetchall()
    conn.close()
    return {**dict(t), "section": dict(s) if s else None, "lessons": [dict(l) for l in lessons]}

@router.post("/curriculum/import")
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
