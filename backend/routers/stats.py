from fastapi import APIRouter, Depends

from db import get_conn
from auth import require_any

router = APIRouter(prefix="/api")

# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
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
