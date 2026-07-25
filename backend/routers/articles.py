import os, json, asyncio
import random as _random
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends

from config import MATERIAL_SUBJECTS
from db import get_conn
from auth import require_parent, require_any
from telegram_service import get_telegram_config, tg_send_result, tg_send
from models.articles import ArticleIn, MaterialAssignmentIn

router = APIRouter(prefix="/api")

# ── Articles (познавательные материалы — без контроля знаний) ────────────────────

@router.get("/materials/subjects")
def material_subjects(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT subject, COUNT(*) as cnt FROM articles WHERE active=1 GROUP BY subject"
    ).fetchall()
    counts = {r["subject"]: r["cnt"] for r in rows}
    conn.close()
    return [{"key": k, "label": v, "count": counts.get(k, 0)} for k, v in MATERIAL_SUBJECTS.items()]

@router.get("/articles")
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

@router.get("/articles/{article_id}")
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

@router.post("/articles")
def create_article(data: ArticleIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO articles (subject,grade,title,summary,cover_image,blocks,manually_edited) VALUES (?,?,?,?,?,?,1)",
              (data.subject, data.grade, data.title, data.summary, data.cover_image,
               json.dumps(data.blocks, ensure_ascii=False)))
    conn.commit(); aid = c.lastrowid; conn.close()
    return {"id": aid}

@router.put("/articles/{article_id}")
def update_article(article_id: int, data: ArticleIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET subject=?,grade=?,title=?,summary=?,cover_image=?,blocks=?,manually_edited=1 WHERE id=?",
                 (data.subject, data.grade, data.title, data.summary, data.cover_image,
                  json.dumps(data.blocks, ensure_ascii=False), article_id))
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/articles/{article_id}")
def delete_article(article_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET active=0 WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.get("/articles/deleted/list")
def list_deleted_articles(role: str = Depends(require_parent)):
    """Диагностика: показывает материалы, помеченные как удалённые (active=0), чтобы можно было
       убедиться, что материал действительно удалён, восстановить его или убрать навсегда."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, subject, grade, title, summary, cover_image, created_at FROM articles WHERE active=0 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.post("/articles/{article_id}/restore")
def restore_article(article_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET active=1 WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/articles/{article_id}/purge")
def purge_article(article_id: int, role: str = Depends(require_parent)):
    """Безвозвратное удаление строки из БД (в отличие от обычного DELETE, который только
       помечает active=0). Используется, чтобы окончательно убрать дубликаты/мусорные записи."""
    conn = get_conn()
    conn.execute("DELETE FROM articles WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.post("/articles/{article_id}/read")
def mark_article_read(article_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    already = conn.execute("SELECT id FROM article_reads WHERE article_id=?", (article_id,)).fetchone()
    if not already:
        conn.execute("INSERT INTO article_reads (article_id) VALUES (?)", (article_id,))
        conn.commit()
    conn.close()
    return {"ok": True}


# ── Рассылка материалов «на изучение» через Telegram ────────────────────────

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

@router.post("/materials/assignments")
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

@router.get("/materials/assignments")
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

@router.get("/materials/assignments/{assignment_id}")
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

@router.post("/materials/assignments/{assignment_id}/complete")
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
