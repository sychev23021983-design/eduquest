import os, asyncio
from fastapi import APIRouter, HTTPException, Depends

from db import get_conn
from auth import require_parent, require_any
from telegram_service import get_telegram_config, tg_send
from models.misc import PenaltyIn, RewardIn

router = APIRouter(prefix="/api")

# ── Coins & Rewards ───────────────────────────────────────────────────────────

@router.get("/coins/balance")
def get_balance(role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent  = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    conn.close()
    return {"balance": earned - spent, "earned": earned, "spent": spent}

@router.post("/coins/penalty")
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

@router.post("/rewards/request")
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

@router.get("/rewards")
def get_rewards(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM rewards ORDER BY requested_at DESC LIMIT 30").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.post("/rewards/{reward_id}/approve")
async def approve_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    r = conn.execute("SELECT * FROM rewards WHERE id=?", (reward_id,)).fetchone()
    if not r:
        conn.close(); raise HTTPException(404)
    conn.execute("UPDATE rewards SET status='approved',approved_at=datetime('now') WHERE id=?", (reward_id,))
    conn.commit(); conn.close()
    asyncio.create_task(tg_send(f"✅ Одобрено: <b>{r['name']}</b> ({r['cost_coins']} монет)"))
    return {"ok": True}

@router.post("/rewards/{reward_id}/reject")
def reject_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE rewards SET status='rejected' WHERE id=?", (reward_id,))
    conn.commit(); conn.close()
    return {"ok": True}
