import os
from fastapi import APIRouter

from config import SUBJECT_LABELS

router = APIRouter(prefix="/api")

# ── Health / Config ───────────────────────────────────────────────────────────

@router.get("/health")
def health():
    p = os.environ.get("PARENT_PASSWORD", "parent123")
    c = os.environ.get("CHILD_PASSWORD",  "child123")
    return {"ok": True, "parent_pass_len": len(p), "child_pass_len": len(c)}

@router.get("/config")
def config():
    return {
        "child_name": os.environ.get("CHILD_NAME", "Тимофей"),
        "child_grade": int(os.environ.get("CHILD_GRADE", "5")),
        "subjects": SUBJECT_LABELS,
    }
