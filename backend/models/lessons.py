from typing import Optional
from pydantic import BaseModel


class LessonIn(BaseModel):
    subject: str
    grade: int = 4
    topic: str
    topic_id: Optional[int] = None
    context_theme: str = "minecraft"
    explanation: str = ""
    explanation_game: str = ""
    questions: Optional[str] = None
    boss_task: Optional[str] = None
    coins_lesson: int = 50
    coins_boss: int = 30


class StartLessonIn(BaseModel):
    lesson_id: int


class FinishLessonIn(BaseModel):
    progress_id: int
    score: int
    total: int = 5
    boss_done: bool = False
    boss_answer: Optional[str] = None
