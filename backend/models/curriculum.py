from typing import Optional
from pydantic import BaseModel


class SectionIn(BaseModel):
    grade: int
    subject: str
    title: str
    order_index: int = 0
    intro: Optional[str] = None


class TopicIn(BaseModel):
    section_id: int
    title: str
    order_index: int = 0


class ImportCurriculumIn(BaseModel):
    grade: int
    subject: str
    text: str
