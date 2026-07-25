from typing import Optional
from pydantic import BaseModel


class LoginIn(BaseModel):
    password: str
    role: str


class MistakeIn(BaseModel):
    lesson_id: int
    question_text: Optional[str] = None
    chosen_text: Optional[str] = None
    correct_text: Optional[str] = None


class PenaltyIn(BaseModel):
    lesson_id: Optional[int] = None
    amount: int = 5
    note: Optional[str] = None


class RewardIn(BaseModel):
    name: str
    cost_coins: int
