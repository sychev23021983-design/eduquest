import jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import SECRET_KEY

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
