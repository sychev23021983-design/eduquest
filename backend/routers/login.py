import os
from fastapi import APIRouter, HTTPException

from auth import make_token
from models.misc import LoginIn

router = APIRouter(prefix="/api")

# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login")
def login(data: LoginIn):
    parent_pass = os.environ.get("PARENT_PASSWORD", "parent123")
    child_pass  = os.environ.get("CHILD_PASSWORD",  "child123")
    expected = parent_pass if data.role == "parent" else child_pass
    if data.password.strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": make_token(data.role), "role": data.role}
