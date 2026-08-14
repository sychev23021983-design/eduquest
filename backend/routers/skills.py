from fastapi import APIRouter, HTTPException, Depends

from db import get_conn
from auth import require_parent, require_any
from models.skills import SkillCategoryIn, SkillIn

router = APIRouter(prefix="/api")

# ── Навыки (логические/классические задачи — картинка + до 3 подсказок) ────────

@router.get("/skill-categories")
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

@router.post("/skill-categories")
def create_skill_category(data: SkillCategoryIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    max_order = c.execute("SELECT MAX(order_index) as m FROM skill_categories").fetchone()["m"]
    c.execute("INSERT INTO skill_categories (title, order_index) VALUES (?,?)",
              (data.title, (max_order or 0) + 1))
    conn.commit(); cid = c.lastrowid; conn.close()
    return {"id": cid}

@router.put("/skill-categories/{category_id}")
def update_skill_category(category_id: int, data: SkillCategoryIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET title=? WHERE id=?", (data.title, category_id))
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/skill-categories/{category_id}")
def delete_skill_category(category_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET active=0 WHERE id=?", (category_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.post("/skill-categories/{category_id}/restore")
def restore_skill_category(category_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET active=1 WHERE id=?", (category_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.get("/skill-categories/deleted/list")
def list_deleted_skill_categories(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, order_index FROM skill_categories WHERE active=0 ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/skills")
def list_skills(category_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, category_id, content, image_url, hint1, hint2, hint3, answer, order_index FROM skills "
        "WHERE active=1 AND category_id=? ORDER BY order_index, id",
        (category_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/skills/all-active")
def list_all_active_skills(role: str = Depends(require_any)):
    """Все активные задания вместе с названием категории — для слайдшоу (перемешивание
       по категориям делается на фронтенде, как и в MaterialsSlideshowPage)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT sk.id, sk.category_id, sk.content, sk.image_url, sk.hint1, sk.hint2, sk.hint3, sk.answer, sc.title as category_title
        FROM skills sk
        JOIN skill_categories sc ON sc.id = sk.category_id
        WHERE sk.active=1 AND sc.active=1
        ORDER BY sk.order_index, sk.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/skills/{skill_id}")
def get_skill(skill_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@router.post("/skills")
def create_skill(data: SkillIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    max_order = c.execute(
        "SELECT MAX(order_index) as m FROM skills WHERE category_id=?", (data.category_id,)
    ).fetchone()["m"]
    c.execute(
        "INSERT INTO skills (category_id,content,image_url,hint1,hint2,hint3,answer,order_index) VALUES (?,?,?,?,?,?,?,?)",
        (data.category_id, data.content, data.image_url, data.hint1, data.hint2, data.hint3, data.answer, (max_order or 0) + 1)
    )
    conn.commit(); sid = c.lastrowid; conn.close()
    return {"id": sid}

@router.put("/skills/{skill_id}")
def update_skill(skill_id: int, data: SkillIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute(
        "UPDATE skills SET category_id=?,content=?,image_url=?,hint1=?,hint2=?,hint3=?,answer=? WHERE id=?",
        (data.category_id, data.content, data.image_url, data.hint1, data.hint2, data.hint3, data.answer, skill_id)
    )
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skills SET active=0 WHERE id=?", (skill_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.post("/skills/{skill_id}/restore")
def restore_skill(skill_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skills SET active=1 WHERE id=?", (skill_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@router.get("/skills/deleted/list")
def list_deleted_skills(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT sk.id, sk.category_id, sk.content, sk.image_url, sk.hint1, sk.hint2, sk.hint3, sc.title as category_title
        FROM skills sk
        LEFT JOIN skill_categories sc ON sc.id = sk.category_id
        WHERE sk.active=0
        ORDER BY sk.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
