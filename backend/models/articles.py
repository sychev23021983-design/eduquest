from typing import Optional
from pydantic import BaseModel


class ArticleIn(BaseModel):
    subject: str
    grade: Optional[int] = None
    title: str
    summary: Optional[str] = None
    cover_image: Optional[str] = None
    blocks: list


class MaterialAssignmentIn(BaseModel):
    coins_reward: int = 30
    count: int = 3
