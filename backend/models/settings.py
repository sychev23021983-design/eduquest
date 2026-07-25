from typing import Optional
from pydantic import BaseModel


class SettingsIn(BaseModel):
    site_name: Optional[str] = None
    logo_url: Optional[str] = None
    logo_size: Optional[int] = None
    favicon_url: Optional[str] = None
    bg_main: Optional[str] = None
    bg_hero: Optional[str] = None
    bg_lesson_of_day: Optional[str] = None
    bg_subject_page: Optional[str] = None
    sidebar_left_url: Optional[str] = None
    sidebar_right_url: Optional[str] = None
    subject_icons: Optional[dict] = None
    font_heading: Optional[str] = None
    font_body: Optional[str] = None
    color_accent: Optional[str] = None
    color_accent2: Optional[str] = None
    sound_correct: Optional[str] = None
    sound_wrong: Optional[str] = None


class TelegramConfigIn(BaseModel):
    tg_bot_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    site_url: Optional[str] = None
