from typing import Optional
from pydantic import BaseModel


class SkillCategoryIn(BaseModel):
    title: str


class SkillIn(BaseModel):
    category_id: int
    image_url: Optional[str] = None
    hint1: Optional[str] = None
    hint2: Optional[str] = None
    hint3: Optional[str] = None
    answer: Optional[str] = None
