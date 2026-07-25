from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import sqlite3, os, jwt, shutil, re, json
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import httpx, asyncio

# Контент (уроки/статьи/программа) вынесен в backend/content/ — модули импортируются и по
# именам констант (используются напрямую ниже), и как модули целиком (нужны
# _lesson_answer_map(), которая обходит vars(<module>) в поисках LESSON_DICT-констант).
from content import articles_content, math_content, russian_content, academy_content
from content.articles_content import (
    ARTICLE_HOW_EARTH_FORMED, ARTICLE_CONTINENTS, ARTICLE_UNIVERSE, ARTICLE_PLANTS_GROW,
    ARTICLE_CELL, ARTICLE_HUMAN_BODY, ARTICLE_EYE, ARTICLE_SLEEP,
)
from content.math_content import (
    LESSON_NATURAL_DIGITS, LESSON_NATURAL_COMPARE, LESSON_ROUNDING, LESSON_DIVISIBILITY,
    LESSON_PRIME_COMPOSITE, LESSON_GCD_LCM, LESSON_CONTROL_NATURAL_NUMBERS, LESSON_ADD_SUBTRACT,
    LESSON_MULT_DIVIDE, LESSON_POWER, LESSON_ORDER_OPERATIONS, LESSON_CONTROL_NATURAL_OPERATIONS,
    LESSON_EXPRESSIONS, LESSON_EQUATIONS, LESSON_FORMULAS, LESSON_CONTROL_EXPRESSIONS_EQUATIONS,
    SECTION_INTRO_NATURAL_NUMBERS, SECTION_INTRO_NATURAL_OPERATIONS, SECTION_INTRO_EXPRESSIONS_EQUATIONS,
    SECTION_INTRO_FRACTIONS, LESSON_FRACTION_CONCEPT, LESSON_FRACTION_TYPES, LESSON_FRACTION_PROPERTY,
    LESSON_FRACTION_OPERATIONS, LESSON_FRACTION_PROBLEMS, LESSON_CONTROL_FRACTIONS, SECTION_INTRO_GEOMETRY,
    LESSON_GEOMETRY_BASICS, LESSON_GEOMETRY_MEASURE, LESSON_GEOMETRY_POLYGON, LESSON_GEOMETRY_ANGLES,
    LESSON_GEOMETRY_LINES, LESSON_GEOMETRY_AREA, LESSON_GEOMETRY_VOLUME, LESSON_CONTROL_GEOMETRY,
    SECTION_INTRO_DATA_ANALYSIS, LESSON_DATA_TABLES, LESSON_AVERAGE, LESSON_TYPICAL_PROBLEMS,
    LESSON_CONTROL_DATA_ANALYSIS, LESSON_FINAL_EXAM, LESSON_REINFORCE_FRACTION_PROPERTY,
    LESSON_REINFORCE_FRACTION_OPERATIONS, LESSON_REINFORCE_FRACTION_PROBLEMS, LESSON_REINFORCE_GEOMETRY_VOLUME,
    LESSON_REINFORCE_CONTROL_GEOMETRY, LESSON_REINFORCE_TYPICAL_PROBLEMS, LESSON_ARCH_MATH_SLIDESHOW,
    MATH_5_CURRICULUM,
)
from content.russian_content import (
    RUSSIAN_5_CURRICULUM, SECTION_INTRO_RU_REVIEW, LESSON_RU_TEXT, LESSON_RU_PHRASE_SENTENCE,
    LESSON_RU_WORD_STRUCTURE, LESSON_RU_SPELLING_BASICS, LESSON_RU_PARTS_OF_SPEECH, SECTION_INTRO_RU_CULTURE,
    LESSON_RU_LANGUAGE_SPEECH, LESSON_RU_NORM_CONCEPT, LESSON_RU_ORTHOEPIC_NORMS, LESSON_RU_MORPH_SYNTAX_PUNCT_NORMS,
    LESSON_RU_PRECISION_LOGIC, LESSON_RU_RICHNESS_APPROPRIATENESS, LESSON_RU_DIALOGUE_MONOLOGUE, SECTION_INTRO_RU_STYLE,
    LESSON_RU_SPEECH_SITUATION, LESSON_RU_THREE_STYLES, LESSON_RU_OFFICIAL_PUBLICISTIC, LESSON_RU_SPEECH_NORM,
    SECTION_INTRO_RU_SYNTAX, LESSON_RU_WORD_COMBINATION, LESSON_RU_SENTENCE_TYPES, LESSON_RU_MAIN_MEMBERS,
    LESSON_RU_TSYA_TSJA, LESSON_RU_VERB_ENDINGS, LESSON_RU_SECONDARY_MEMBERS, LESSON_RU_HOMOGENEOUS,
    LESSON_RU_ADDRESS, LESSON_RU_COMPLEX_SENTENCE, LESSON_RU_DIRECT_SPEECH,
)
from content.academy_content import SECTION_INTRO_ACADEMY_LOGIC, LESSON_ACADEMY_RIVER_CROSSING

DB_PATH    = os.getenv("DB_PATH",         "/app/data/eduquest.db")
SECRET_KEY = os.getenv("SECRET_KEY",      "eduquest-secret-key-2026")
UPLOAD_DIR = os.getenv("UPLOAD_DIR",      "/app/data/uploads")
TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "")

# Создаём папки сразу при импорте — до StaticFiles
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(f"{UPLOAD_DIR}/audio",  exist_ok=True)
os.makedirs(f"{UPLOAD_DIR}/images", exist_ok=True)
os.makedirs(f"{UPLOAD_DIR}/site",   exist_ok=True)

SUBJECT_LABELS = {
    "math":    "Математика",
    "russian": "Русский язык",
    "science": "Окружающий мир",
    "history": "История",
    "academy": "Академия Великих Исследователей",
}

DEFAULT_SETTINGS = {
    "site_name": "EduQuest",
    "logo_url": None,
    "logo_size": 28,
    "favicon_url": None,
    "bg_main": None,
    "bg_hero": None,
    "bg_lesson_of_day": None,
    "bg_subject_page": None,
    "sidebar_left_url": None,
    "sidebar_right_url": None,
    "subject_icons": {"math": None, "russian": None, "science": None, "history": None, "academy": None},
    "font_heading": "Nunito",
    "font_body": "Nunito",
    "color_accent": "#4da3ff",
    "color_accent2": "#22d38b",
    "sound_correct": None,
    "sound_wrong": None,
}

FONT_CHOICES = ["Nunito", "Rubik", "Montserrat", "PT Sans", "Comfortaa", "Ubuntu"]

def get_settings(conn):
    row = conn.execute("SELECT data FROM site_settings WHERE id=1").fetchone()
    stored = json.loads(row["data"]) if row and row["data"] else {}
    merged = {**DEFAULT_SETTINGS, **stored}
    merged["subject_icons"] = {**DEFAULT_SETTINGS["subject_icons"], **(stored.get("subject_icons") or {})}
    return merged

def save_settings(conn, data: dict):
    conn.execute("UPDATE site_settings SET data=? WHERE id=1", (json.dumps(data, ensure_ascii=False),))

# Интеграции (Telegram и т.п.) хранятся отдельно от site_settings, потому что
# /api/settings отдаётся без авторизации (используется для оформления интерфейса
# на странице логина) — токен бота там светить нельзя. Всё, что лежит в
# integrations, доступно только через parent-эндпоинты.
DEFAULT_INTEGRATIONS = {
    "tg_bot_token": "",
    "tg_chat_id": "",
    "site_url": "",
}

def get_integrations(conn):
    row = conn.execute("SELECT data FROM integrations WHERE id=1").fetchone()
    stored = json.loads(row["data"]) if row and row["data"] else {}
    return {**DEFAULT_INTEGRATIONS, **stored}

def save_integrations(conn, data: dict):
    conn.execute("UPDATE integrations SET data=? WHERE id=1", (json.dumps(data, ensure_ascii=False),))

def get_telegram_config(conn):
    """Токен/chat_id берутся из настроек (кабинет родителя → Настройки → Telegram),
    а если там пусто — из переменных окружения (старый способ, для обратной совместимости)."""
    integ = get_integrations(conn)
    return {
        "bot_token": integ.get("tg_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id":   integ.get("tg_chat_id")   or os.environ.get("TELEGRAM_CHAT_ID", ""),
        "site_url":  (integ.get("site_url") or os.environ.get("SITE_URL", "") or "http://147.45.42.169:8090").rstrip("/"),
    }

def parse_curriculum_text(text: str):
    """Разбирает текст вида:
       **1. Раздел**
       - **Тема:** описание...
       в список [{title, topics: [str, ...]}, ...]."""
    sections = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m_section = re.match(r'^\*{1,2}\s*\d+[\.\)]\s*(.+?)\*{1,2}$', line)
        if m_section:
            current = {"title": m_section.group(1).strip(), "topics": []}
            sections.append(current)
            continue
        m_topic = re.match(r'^[-•]\s*\*{1,2}([^*]+?):\*{1,2}', line)
        if m_topic and current is not None:
            current["topics"].append(m_topic.group(1).strip())
            continue
    return sections

def seed_section_if_missing(conn, grade: int, subject: str, title: str, intro: str = None):
    """Добавляет совершенно новый раздел в конец уже засеянной программы (когда
       seed_curriculum_if_empty больше не сработает, т.к. программа не пустая). В отличие от
       seed_topic_if_missing (добавляет тему в существующий раздел), эта функция создаёт сам
       раздел. Идемпотентна — если раздел с таким названием уже есть, ничего не делает."""
    existing = conn.execute(
        "SELECT id FROM sections WHERE grade=? AND subject=? AND title=?", (grade, subject, title)
    ).fetchone()
    if existing:
        return existing["id"]
    next_order = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) + 1 as n FROM sections WHERE grade=? AND subject=?",
        (grade, subject)
    ).fetchone()["n"]
    c = conn.cursor()
    c.execute("INSERT INTO sections (grade,subject,title,order_index,intro) VALUES (?,?,?,?,?)",
              (grade, subject, title, next_order, intro))
    return c.lastrowid

def seed_topic_if_missing(conn, grade: int, subject: str, section_title: str, topic_title: str):
    """Добавляет тему в конец уже существующего раздела, если такой темы там ещё нет.
       Используется, когда раздел уже засеян (seed_curriculum_if_empty больше не сработает)."""
    row = conn.execute(
        "SELECT id FROM sections WHERE grade=? AND subject=? AND title=?",
        (grade, subject, section_title)
    ).fetchone()
    if not row:
        return  # раздел ещё не создан — пропускаем, попробуем на следующем старте
    section_id = row["id"]
    existing = conn.execute(
        "SELECT id FROM topics WHERE section_id=? AND title=?", (section_id, topic_title)
    ).fetchone()
    if existing:
        return
    next_order = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) + 1 as n FROM topics WHERE section_id=?", (section_id,)
    ).fetchone()["n"]
    conn.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
                 (section_id, topic_title, next_order))

def seed_lesson_if_missing(conn, grade: int, subject: str, section_title: str, topic_title: str, lesson: dict):
    """Создаёт урок для темы (по названию раздела+темы), если у темы ещё нет ни одного активного урока.
       lesson["lesson_type"] может быть "quiz" (по умолчанию, с questions/boss_task) или "slideshow"
       (только lesson["slides"] — упорядоченный список названий слотов картинок, без вопросов и
       объяснений; questions/boss_task в этом случае не нужны)."""
    row = conn.execute("""
        SELECT t.id as topic_id FROM topics t
        JOIN sections s ON t.section_id = s.id
        WHERE s.grade=? AND s.subject=? AND s.title=? AND t.title=?
    """, (grade, subject, section_title, topic_title)).fetchone()
    if not row:
        return  # раздел/тема ещё не созданы — пропускаем, попробуем на следующем старте
    topic_id = row["topic_id"]
    existing = conn.execute(
        "SELECT COUNT(*) as n FROM lessons WHERE topic_id=? AND active=1", (topic_id,)
    ).fetchone()["n"]
    if existing > 0:
        return
    conn.execute("""INSERT INTO lessons
        (subject,grade,topic,topic_id,context_theme,explanation,explanation_game,questions,boss_task,coins_lesson,coins_boss,lesson_type,slides)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (subject, grade, lesson["topic"], topic_id, lesson.get("context_theme", "detective"),
         lesson.get("explanation", ""), lesson.get("explanation_game", ""),
         json.dumps(lesson.get("questions", []), ensure_ascii=False),
         json.dumps(lesson["boss_task"], ensure_ascii=False) if lesson.get("boss_task") else None,
         lesson.get("coins_lesson", 50), lesson.get("coins_boss", 30),
         lesson.get("lesson_type", "quiz"),
         json.dumps(lesson["slides"], ensure_ascii=False) if lesson.get("slides") else None))

def seed_lesson_regenerate(conn, grade: int, subject: str, section_title: str, topic_title: str, lesson: dict):
    """Как seed_lesson_if_missing, но если у темы уже есть активный урок — перезаписывает его содержимое
       (explanation/explanation_game/questions/boss_task/coins/lesson_type/slides), не трогая id урока и
       прогресс учеников по нему (progress ссылается на lesson_id). Используется для перегенерации
       существующего урока."""
    row = conn.execute("""
        SELECT t.id as topic_id FROM topics t
        JOIN sections s ON t.section_id = s.id
        WHERE s.grade=? AND s.subject=? AND s.title=? AND t.title=?
    """, (grade, subject, section_title, topic_title)).fetchone()
    if not row:
        return  # раздел/тема ещё не созданы — пропускаем, попробуем на следующем старте
    topic_id = row["topic_id"]
    existing = conn.execute(
        "SELECT id FROM lessons WHERE topic_id=? AND active=1", (topic_id,)
    ).fetchone()
    if not existing:
        seed_lesson_if_missing(conn, grade, subject, section_title, topic_title, lesson)
        return
    conn.execute("""UPDATE lessons SET
        context_theme=?, explanation=?, explanation_game=?, questions=?, boss_task=?, coins_lesson=?, coins_boss=?,
        lesson_type=?, slides=?
        WHERE id=?""",
        (lesson.get("context_theme", "detective"),
         lesson.get("explanation", ""), lesson.get("explanation_game", ""),
         json.dumps(lesson.get("questions", []), ensure_ascii=False),
         json.dumps(lesson["boss_task"], ensure_ascii=False) if lesson.get("boss_task") else None,
         lesson.get("coins_lesson", 50), lesson.get("coins_boss", 30),
         lesson.get("lesson_type", "quiz"),
         json.dumps(lesson["slides"], ensure_ascii=False) if lesson.get("slides") else None,
         existing["id"]))

def _lesson_answer_map():
    """Собирает {topic: answer} из всех LESSON_DICT-констант content-модулей, у которых
    задан boss_task.answer. Используется backfill_missing_boss_answers() как источник истины —
    "правильный" ответ для темы всегда тот, что сейчас записан в коде."""
    result = {}
    for module in (math_content, russian_content, academy_content, articles_content):
        for val in vars(module).values():
            if isinstance(val, dict) and isinstance(val.get("boss_task"), dict) and val.get("topic"):
                ans = val["boss_task"].get("answer")
                if ans:
                    result[val["topic"]] = ans
    return result

def backfill_missing_boss_answers(conn):
    """Чинит уроки, у которых boss_task в БД сохранён БЕЗ поля answer — это происходило у тем,
    засеянных ещё до того, как answer стало обязательной частью схемы boss_task (в текущем коде
    оно есть у всех уроков). Без этого поля _check_boss_answer() получает expected=None и
    засчитывает финальное задание как неверное при любом ответе ребёнка, независимо от того,
    что он ввёл — баг обнаружен и закрыт 2026-07 на уроке «Порядок действий» (ответ 37 не
    засчитывался). Патчит ТОЛЬКО ключ answer внутри уже существующего boss_task, не трогая
    text/solution/hint1/hint2 (могли быть намеренно другими) и не меняя id урока/прогресс.
    Идемпотентно — пропускает уроки, где answer уже есть."""
    answer_map = _lesson_answer_map()
    rows = conn.execute("SELECT id, topic, boss_task FROM lessons WHERE active=1 AND boss_task IS NOT NULL").fetchall()
    fixed = []
    for r in rows:
        try:
            bt = json.loads(r["boss_task"])
        except Exception:
            continue
        if not isinstance(bt, dict) or bt.get("answer"):
            continue
        correct = answer_map.get(r["topic"])
        if not correct:
            continue
        bt["answer"] = correct
        conn.execute("UPDATE lessons SET boss_task=? WHERE id=?", (json.dumps(bt, ensure_ascii=False), r["id"]))
        fixed.append(r["topic"])
    return fixed

def seed_article_if_missing(conn, subject: str, title: str, article: dict):
    """Создаёт познавательный материал (статья, без контроля знаний), если статьи с таким названием
       ещё не существует. Проверяем ЛЮБУЮ строку с этим subject+title, включая удалённые
       (active=0) — если родитель удалил материал, повторный деплой не должен его воскрешать."""
    existing = conn.execute(
        "SELECT id FROM articles WHERE subject=? AND title=?", (subject, title)
    ).fetchone()
    if existing:
        return
    conn.execute("""INSERT INTO articles (subject,grade,title,summary,cover_image,blocks) VALUES (?,?,?,?,?,?)""",
        (subject, article.get("grade"), title, article.get("summary", ""), article.get("cover_image"),
         json.dumps(article["blocks"], ensure_ascii=False)))

def seed_article_upsert(conn, subject: str, title: str, article: dict):
    """Как seed_article_if_missing, но обновляет содержимое, если статья уже есть — для материалов,
       которые мы дорабатываем итеративно (пока родитель ещё не редактировал их вручную).
       Если статью уже редактировали через панель (manually_edited=1) ИЛИ родитель её удалил
       (active=0), НЕ трогаем и НЕ пересоздаём её — иначе правки, картинки и сам факт удаления
       откатывались бы назад при каждом деплое."""
    existing = conn.execute(
        "SELECT id, active, manually_edited FROM articles WHERE subject=? AND title=?", (subject, title)
    ).fetchone()
    if existing:
        if not existing["active"] or existing["manually_edited"]:
            return  # удалено родителем или отредактировано вручную — не трогаем
        conn.execute("UPDATE articles SET summary=?,cover_image=?,blocks=? WHERE id=?",
            (article.get("summary", ""), article.get("cover_image"),
             json.dumps(article["blocks"], ensure_ascii=False), existing["id"]))
        return
    conn.execute("""INSERT INTO articles (subject,grade,title,summary,cover_image,blocks) VALUES (?,?,?,?,?,?)""",
        (subject, article.get("grade"), title, article.get("summary", ""), article.get("cover_image"),
         json.dumps(article["blocks"], ensure_ascii=False)))


def seed_section_intro_if_missing(conn, grade: int, subject: str, section_title: str, intro: str):
    row = conn.execute(
        "SELECT id, intro FROM sections WHERE grade=? AND subject=? AND title=?",
        (grade, subject, section_title)
    ).fetchone()
    if not row or (row["intro"] and row["intro"].strip()):
        return
    conn.execute("UPDATE sections SET intro=? WHERE id=?", (intro, row["id"]))

def seed_curriculum_if_empty(conn, grade: int, subject: str, raw_text: str):
    existing = conn.execute(
        "SELECT COUNT(*) as n FROM sections WHERE grade=? AND subject=?", (grade, subject)
    ).fetchone()["n"]
    if existing > 0:
        return
    parsed = parse_curriculum_text(raw_text)
    for i, sec in enumerate(parsed):
        c = conn.cursor()
        c.execute("INSERT INTO sections (grade,subject,title,order_index) VALUES (?,?,?,?)",
                  (grade, subject, sec["title"], i))
        sid = c.lastrowid
        for j, t_title in enumerate(sec["topics"]):
            conn.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
                         (sid, t_title, j))




# ── DB ────────────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_add_column(conn, table, col, coltype):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            grade        INTEGER NOT NULL,
            subject      TEXT NOT NULL,
            title        TEXT NOT NULL,
            order_index  INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS topics (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id   INTEGER NOT NULL,
            title        TEXT NOT NULL,
            order_index  INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(section_id) REFERENCES sections(id)
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            subject       TEXT NOT NULL,
            grade         INTEGER NOT NULL DEFAULT 4,
            topic         TEXT NOT NULL,
            context_theme TEXT DEFAULT 'minecraft',
            explanation   TEXT,
            explanation_game TEXT,
            audio_file    TEXT,
            infographic   TEXT,
            questions     TEXT,
            boss_task     TEXT,
            coins_lesson  INTEGER DEFAULT 50,
            coins_boss    INTEGER DEFAULT 30,
            created_at    TEXT DEFAULT (datetime('now')),
            active        INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS progress (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id    INTEGER NOT NULL,
            started_at   TEXT DEFAULT (datetime('now')),
            finished_at  TEXT,
            score        INTEGER DEFAULT 0,
            max_score    INTEGER DEFAULT 5,
            coins_earned INTEGER DEFAULT 0,
            boss_done    INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mistakes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id     INTEGER NOT NULL,
            question_text TEXT,
            chosen_text   TEXT,
            correct_text  TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS articles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            subject      TEXT NOT NULL,
            grade        INTEGER,
            title        TEXT NOT NULL,
            summary      TEXT,
            cover_image  TEXT,
            blocks       TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now')),
            active       INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS article_reads (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id   INTEGER NOT NULL,
            read_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS coins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            amount     INTEGER NOT NULL,
            type       TEXT NOT NULL,
            note       TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS rewards (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            cost_coins   INTEGER NOT NULL,
            status       TEXT DEFAULT 'pending',
            requested_at TEXT DEFAULT (datetime('now')),
            approved_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS streak (
            id       INTEGER PRIMARY KEY CHECK (id = 1),
            days     INTEGER DEFAULT 0,
            last_day TEXT
        );
        INSERT OR IGNORE INTO streak(id, days, last_day) VALUES (1, 0, NULL);
        CREATE TABLE IF NOT EXISTS site_settings (
            id   INTEGER PRIMARY KEY CHECK (id = 1),
            data TEXT NOT NULL DEFAULT '{}'
        );
        INSERT OR IGNORE INTO site_settings(id, data) VALUES (1, '{}');
        CREATE TABLE IF NOT EXISTS integrations (
            id   INTEGER PRIMARY KEY CHECK (id = 1),
            data TEXT NOT NULL DEFAULT '{}'
        );
        INSERT OR IGNORE INTO integrations(id, data) VALUES (1, '{}');
        CREATE TABLE IF NOT EXISTS material_assignments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            article_ids  TEXT NOT NULL,
            coins_reward INTEGER NOT NULL DEFAULT 0,
            sent_at      TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            telegram_ok  INTEGER DEFAULT 0,
            telegram_error TEXT
        );
        CREATE TABLE IF NOT EXISTS material_assignment_articles (
            assignment_id INTEGER NOT NULL,
            article_id    INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skill_categories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            order_index  INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now')),
            active       INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS skills (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id  INTEGER NOT NULL,
            image_url    TEXT,
            hint1        TEXT,
            hint2        TEXT,
            hint3        TEXT,
            answer       TEXT,
            order_index  INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now')),
            active       INTEGER DEFAULT 1
        );
    """)
    migrate_add_column(conn, "lessons", "topic_id", "INTEGER")
    migrate_add_column(conn, "lessons", "lesson_type", "TEXT DEFAULT 'quiz'")
    migrate_add_column(conn, "lessons", "slides", "TEXT")
    migrate_add_column(conn, "sections", "intro", "TEXT")
    migrate_add_column(conn, "sections", "intro_seen_at", "TEXT")
    migrate_add_column(conn, "articles", "cover_image", "TEXT")
    migrate_add_column(conn, "articles", "manually_edited", "INTEGER DEFAULT 0")
    migrate_add_column(conn, "skills", "answer", "TEXT")
    seed_curriculum_if_empty(conn, 5, "math", MATH_5_CURRICULUM)
    seed_curriculum_if_empty(conn, 5, "russian", RUSSIAN_5_CURRICULUM)
    seed_section_intro_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", SECTION_INTRO_RU_REVIEW)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 1. Текст", LESSON_RU_TEXT)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 2. Словосочетание. Предложение", LESSON_RU_PHRASE_SENTENCE)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 3. Состав слова. Орфограмма", LESSON_RU_WORD_STRUCTURE)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 4. Правописание", LESSON_RU_SPELLING_BASICS)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 5. Части речи", LESSON_RU_PARTS_OF_SPEECH)
    seed_section_intro_if_missing(conn, 5, "russian", "Культура устной и письменной речи", SECTION_INTRO_RU_CULTURE)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 6. Язык и речь", LESSON_RU_LANGUAGE_SPEECH)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 7. Культура устной и письменной речи. Нормы литературного языка", LESSON_RU_NORM_CONCEPT)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 8. Произносительная, орфографическая, словообразовательная нормы", LESSON_RU_ORTHOEPIC_NORMS)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 9. Морфологическая, синтаксическая, пунктуационная нормы", LESSON_RU_MORPH_SYNTAX_PUNCT_NORMS)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 10. Качества речи. Точность и логичность речи", LESSON_RU_PRECISION_LOGIC)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 11. Богатство, выразительность, чистота и уместность речи", LESSON_RU_RICHNESS_APPROPRIATENESS)
    seed_lesson_if_missing(conn, 5, "russian", "Культура устной и письменной речи", "§ 12. Диалог. Монолог", LESSON_RU_DIALOGUE_MONOLOGUE)
    seed_section_intro_if_missing(conn, 5, "russian", "Речевая ситуация. Стили речи", SECTION_INTRO_RU_STYLE)
    seed_lesson_if_missing(conn, 5, "russian", "Речевая ситуация. Стили речи", "§ 13. Признаки речевой ситуации", LESSON_RU_SPEECH_SITUATION)
    seed_lesson_if_missing(conn, 5, "russian", "Речевая ситуация. Стили речи", "§ 14. Разговорный, научный и художественный стили речи", LESSON_RU_THREE_STYLES)
    seed_lesson_if_missing(conn, 5, "russian", "Речевая ситуация. Стили речи", "§ 15. Официально-деловой, публицистический стили речи", LESSON_RU_OFFICIAL_PUBLICISTIC)
    seed_lesson_if_missing(conn, 5, "russian", "Речевая ситуация. Стили речи", "§ 16. Речевая норма", LESSON_RU_SPEECH_NORM)
    seed_section_intro_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", SECTION_INTRO_RU_SYNTAX)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 17. Словосочетание", LESSON_RU_WORD_COMBINATION)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 18. Предложение. Виды предложений по цели высказывания и интонации", LESSON_RU_SENTENCE_TYPES)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 19. Главные члены предложения", LESSON_RU_MAIN_MEMBERS)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 20. Правописание -тся и -ться в глаголах", LESSON_RU_TSYA_TSJA)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 21. Правописание личных окончаний глаголов", LESSON_RU_VERB_ENDINGS)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 22. Второстепенные члены предложения", LESSON_RU_SECONDARY_MEMBERS)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 23. Однородные члены предложения", LESSON_RU_HOMOGENEOUS)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 24. Обращение", LESSON_RU_ADDRESS)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 25. Строение сложного предложения", LESSON_RU_COMPLEX_SENTENCE)
    seed_lesson_if_missing(conn, 5, "russian", "Синтаксис и пунктуация", "§ 26. Предложения с прямой речью. Знаки препинания в предложениях с прямой речью", LESSON_RU_DIRECT_SPEECH)
    seed_section_intro_if_missing(conn, 5, "math", "Натуральные числа", SECTION_INTRO_NATURAL_NUMBERS)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Цифры и натуральные числа", LESSON_NATURAL_DIGITS)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Сравнение натуральных чисел", LESSON_NATURAL_COMPARE)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Округление чисел", LESSON_ROUNDING)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Делимость чисел", LESSON_DIVISIBILITY)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Простые и составные числа", LESSON_PRIME_COMPOSITE)
    seed_lesson_regenerate(conn, 5, "math", "Натуральные числа", "НОД и НОК", LESSON_GCD_LCM)
    seed_topic_if_missing(conn, 5, "math", "Натуральные числа", "Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Контрольная работа", LESSON_CONTROL_NATURAL_NUMBERS)
    seed_section_intro_if_missing(conn, 5, "math", "Действия с натуральными числами", SECTION_INTRO_NATURAL_OPERATIONS)
    seed_lesson_if_missing(conn, 5, "math", "Действия с натуральными числами", "Сложение и вычитание", LESSON_ADD_SUBTRACT)
    seed_lesson_if_missing(conn, 5, "math", "Действия с натуральными числами", "Умножение и деление", LESSON_MULT_DIVIDE)
    seed_lesson_if_missing(conn, 5, "math", "Действия с натуральными числами", "Степень числа", LESSON_POWER)
    seed_lesson_if_missing(conn, 5, "math", "Действия с натуральными числами", "Порядок действий", LESSON_ORDER_OPERATIONS)
    seed_topic_if_missing(conn, 5, "math", "Действия с натуральными числами", "Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Действия с натуральными числами", "Контрольная работа", LESSON_CONTROL_NATURAL_OPERATIONS)
    seed_section_intro_if_missing(conn, 5, "math", "Выражения и уравнения", SECTION_INTRO_EXPRESSIONS_EQUATIONS)
    seed_lesson_if_missing(conn, 5, "math", "Выражения и уравнения", "Числовые и буквенные выражения", LESSON_EXPRESSIONS)
    seed_lesson_if_missing(conn, 5, "math", "Выражения и уравнения", "Уравнения", LESSON_EQUATIONS)
    seed_lesson_if_missing(conn, 5, "math", "Выражения и уравнения", "Формулы", LESSON_FORMULAS)
    seed_topic_if_missing(conn, 5, "math", "Выражения и уравнения", "Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Выражения и уравнения", "Контрольная работа", LESSON_CONTROL_EXPRESSIONS_EQUATIONS)
    seed_section_intro_if_missing(conn, 5, "math", "Обыкновенные дроби", SECTION_INTRO_FRACTIONS)
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Понятие дроби", LESSON_FRACTION_CONCEPT)
    seed_lesson_regenerate(conn, 5, "math", "Обыкновенные дроби", "Виды дробей", LESSON_FRACTION_TYPES)
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Основное свойство дроби", LESSON_FRACTION_PROPERTY)
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Действия с дробями", LESSON_FRACTION_OPERATIONS)
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Задачи на дроби", LESSON_FRACTION_PROBLEMS)
    seed_topic_if_missing(conn, 5, "math", "Обыкновенные дроби", "Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Контрольная работа", LESSON_CONTROL_FRACTIONS)
    seed_topic_if_missing(conn, 5, "math", "Обыкновенные дроби", "Закрепление: Основное свойство дроби")
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Закрепление: Основное свойство дроби", LESSON_REINFORCE_FRACTION_PROPERTY)
    seed_topic_if_missing(conn, 5, "math", "Обыкновенные дроби", "Закрепление: Действия с дробями")
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Закрепление: Действия с дробями", LESSON_REINFORCE_FRACTION_OPERATIONS)
    seed_topic_if_missing(conn, 5, "math", "Обыкновенные дроби", "Закрепление: Задачи на дроби")
    seed_lesson_if_missing(conn, 5, "math", "Обыкновенные дроби", "Закрепление: Задачи на дроби", LESSON_REINFORCE_FRACTION_PROBLEMS)
    seed_section_intro_if_missing(conn, 5, "math", "Геометрические фигуры и величины", SECTION_INTRO_GEOMETRY)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Основные объекты", LESSON_GEOMETRY_BASICS)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Измерения", LESSON_GEOMETRY_MEASURE)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Ломаная и многоугольники", LESSON_GEOMETRY_POLYGON)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Углы", LESSON_GEOMETRY_ANGLES)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Взаимное расположение прямых", LESSON_GEOMETRY_LINES)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Площадь", LESSON_GEOMETRY_AREA)
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Объем", LESSON_GEOMETRY_VOLUME)
    seed_topic_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Контрольная работа", LESSON_CONTROL_GEOMETRY)
    seed_topic_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Закрепление: Объем")
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Закрепление: Объем", LESSON_REINFORCE_GEOMETRY_VOLUME)
    seed_topic_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Закрепление: Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Геометрические фигуры и величины", "Закрепление: Контрольная работа", LESSON_REINFORCE_CONTROL_GEOMETRY)
    seed_section_intro_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", SECTION_INTRO_DATA_ANALYSIS)
    seed_lesson_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Работа с информацией", LESSON_DATA_TABLES)
    seed_lesson_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Среднее арифметическое", LESSON_AVERAGE)
    seed_lesson_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Типовые задачи", LESSON_TYPICAL_PROBLEMS)
    seed_topic_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Контрольная работа")
    seed_lesson_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Контрольная работа", LESSON_CONTROL_DATA_ANALYSIS)
    seed_topic_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Итоговый экзамен")
    seed_lesson_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Итоговый экзамен", LESSON_FINAL_EXAM)
    seed_topic_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Закрепление: Типовые задачи")
    seed_lesson_if_missing(conn, 5, "math", "Анализ данных и текстовые задачи", "Закрепление: Типовые задачи", LESSON_REINFORCE_TYPICAL_PROBLEMS)
    seed_section_if_missing(conn, 5, "math", "Архитектура математики")
    seed_topic_if_missing(conn, 5, "math", "Архитектура математики", "Архитектура математики")
    seed_lesson_if_missing(conn, 5, "math", "Архитектура математики", "Архитектура математики", LESSON_ARCH_MATH_SLIDESHOW)
    # «Почему идёт дождь?» и «Почему птицы летают» родитель удалил навсегда (purge) — сидинг для
    # них убран, иначе они пересоздавались бы заново при каждом деплое (для «зашитых» материалов
    # обычное мягкое удаление respected, но purge стирает строку целиком, и seed-функция не может
    # отличить «удалено навсегда» от «ещё не создано»).
    seed_article_upsert(conn, "earth", "Как появилась Земля?", ARTICLE_HOW_EARTH_FORMED)
    seed_article_upsert(conn, "geography", "Материки Земли", ARTICLE_CONTINENTS)
    seed_article_upsert(conn, "space", "Что такое Вселенная?", ARTICLE_UNIVERSE)
    seed_article_upsert(conn, "plants", "Как растут растения", ARTICLE_PLANTS_GROW)
    seed_article_upsert(conn, "micro", "Что такое клетка", ARTICLE_CELL)
    seed_article_upsert(conn, "body", "Из чего состоит человек", ARTICLE_HUMAN_BODY)
    seed_article_upsert(conn, "senses", "Как работает глаз", ARTICLE_EYE)
    seed_article_upsert(conn, "health", "Почему нужно спать", ARTICLE_SLEEP)
    # Академия Великих Исследователей — пилотная миссия Мира 1 «Долина Логики»
    seed_section_if_missing(conn, 5, "academy", "Мир 1. Долина Логики")
    seed_section_intro_if_missing(conn, 5, "academy", "Мир 1. Долина Логики", SECTION_INTRO_ACADEMY_LOGIC)
    seed_topic_if_missing(conn, 5, "academy", "Мир 1. Долина Логики", "Испытание 1. Переправа через реку Тишины")
    seed_lesson_if_missing(conn, 5, "academy", "Мир 1. Долина Логики", "Испытание 1. Переправа через реку Тишины", LESSON_ACADEMY_RIVER_CROSSING)
    fixed_answers = backfill_missing_boss_answers(conn)
    if fixed_answers:
        print(f"[init_db] Восстановлено поле answer в boss_task для уроков: {fixed_answers}")
    conn.commit()
    conn.close()

# ── Telegram ──────────────────────────────────────────────────────────────────

async def tg_send_result(text: str):
    """Отправляет сообщение и возвращает (ok, error) — используется там, где нужно
    показать родителю результат сразу (тест интеграции, рассылка материалов)."""
    conn = get_conn()
    cfg = get_telegram_config(conn)
    conn.close()
    token, chat = cfg["bot_token"], cfg["chat_id"]
    if not token or not chat or token == "YOUR_BOT_TOKEN_HERE":
        return False, "Telegram не настроен — заполни токен бота и chat_id в Настройках"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            )
        if resp.status_code != 200:
            detail = None
            try: detail = resp.json().get("description")
            except Exception: pass
            return False, detail or f"Telegram вернул ошибку {resp.status_code}"
        return True, None
    except Exception as e:
        return False, str(e)

async def tg_send(text: str):
    """Отправка «в фоне», без ожидания результата — как и раньше, ошибки просто проглатываются."""
    try:
        await tg_send_result(text)
    except Exception:
        pass

# ── Auth ──────────────────────────────────────────────────────────────────────

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

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ── Health / Config ───────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    p = os.environ.get("PARENT_PASSWORD", "parent123")
    c = os.environ.get("CHILD_PASSWORD",  "child123")
    return {"ok": True, "parent_pass_len": len(p), "child_pass_len": len(c)}

@app.get("/api/config")
def config():
    return {
        "child_name": os.environ.get("CHILD_NAME", "Тимофей"),
        "child_grade": int(os.environ.get("CHILD_GRADE", "5")),
        "subjects": SUBJECT_LABELS,
    }

# ── Settings (тема/оформление интерфейса) ───────────────────────────────────────

@app.get("/api/settings")
def read_settings():
    conn = get_conn(); s = get_settings(conn); conn.close()
    return s

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

@app.put("/api/settings")
def update_settings(data: SettingsIn, role: str = Depends(require_parent)):
    conn = get_conn()
    current = get_settings(conn)
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if "subject_icons" in updates:
        current["subject_icons"] = {**current["subject_icons"], **updates.pop("subject_icons")}
    current.update(updates)
    save_settings(conn, current)
    conn.commit(); conn.close()
    return current

@app.post("/api/settings/reset")
def reset_settings(role: str = Depends(require_parent)):
    conn = get_conn()
    save_settings(conn, dict(DEFAULT_SETTINGS))
    conn.commit(); conn.close()
    return dict(DEFAULT_SETTINGS)

SOUND_SLOTS = ("sound_correct", "sound_wrong")

@app.post("/api/settings/upload")
async def upload_setting_asset(slot: str, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    safe_slot = re.sub(r"[^a-z0-9_]", "", slot.lower())
    if not safe_slot:
        raise HTTPException(400, "Bad slot")
    if safe_slot in SOUND_SLOTS:
        if ext not in ("mp3", "wav", "ogg", "m4a"):
            raise HTTPException(400, "Unsupported format")
    else:
        if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg", "ico"):
            raise HTTPException(400, "Unsupported format")
    fpath = f"{UPLOAD_DIR}/site/{safe_slot}.{ext}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    url = f"/uploads/site/{safe_slot}.{ext}?v={int(datetime.utcnow().timestamp())}"
    conn = get_conn()
    current = get_settings(conn)
    if safe_slot.startswith("subject_"):
        current["subject_icons"][safe_slot.replace("subject_", "")] = url
    else:
        current[safe_slot] = url
    save_settings(conn, current)
    conn.commit(); conn.close()
    return current

# ── Интеграции (Telegram) ────────────────────────────────────────────────────

class TelegramConfigIn(BaseModel):
    tg_bot_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    site_url: Optional[str] = None

@app.get("/api/integrations/telegram")
def get_telegram_settings(role: str = Depends(require_parent)):
    conn = get_conn()
    cfg = get_telegram_config(conn)
    conn.close()
    return cfg

@app.put("/api/integrations/telegram")
def update_telegram_settings(data: TelegramConfigIn, role: str = Depends(require_parent)):
    conn = get_conn()
    current = get_integrations(conn)
    updates = {k: v for k, v in data.dict().items() if v is not None}
    current.update(updates)
    save_integrations(conn, current)
    conn.commit()
    cfg = get_telegram_config(conn)
    conn.close()
    return cfg

@app.post("/api/integrations/telegram/test")
async def test_telegram(role: str = Depends(require_parent)):
    child = os.environ.get("CHILD_NAME", "Тимофей")
    ok, error = await tg_send_result(
        f"🔔 Тестовое сообщение от EduQuest.\nЕсли ты это видишь — интеграция с Telegram настроена верно! "
        f"Уведомления про {child} будут приходить сюда."
    )
    if not ok:
        raise HTTPException(400, error or "Не удалось отправить сообщение")
    return {"ok": True}

# ── Login ─────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    password: str
    role: str

@app.post("/api/login")
def login(data: LoginIn):
    parent_pass = os.environ.get("PARENT_PASSWORD", "parent123")
    child_pass  = os.environ.get("CHILD_PASSWORD",  "child123")
    expected = parent_pass if data.role == "parent" else child_pass
    if data.password.strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": make_token(data.role), "role": data.role}

# ── Curriculum: Класс → Предмет → Раздел → Тема ─────────────────────────────────

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

@app.get("/api/curriculum")
def get_curriculum(grade: int, subject: str, role: str = Depends(require_any)):
    """Полное дерево разделов и тем предмета — общая картина для планирования уроков."""
    conn = get_conn()
    sections = conn.execute(
        "SELECT * FROM sections WHERE grade=? AND subject=? ORDER BY order_index, id",
        (grade, subject)
    ).fetchall()
    result = []
    for s in sections:
        topics = conn.execute(
            "SELECT * FROM topics WHERE section_id=? ORDER BY order_index, id", (s["id"],)
        ).fetchall()
        topic_list = []
        for t in topics:
            t_lessons = conn.execute(
                "SELECT id, topic, infographic, lesson_type, slides FROM lessons WHERE topic_id=? AND active=1 ORDER BY created_at", (t["id"],)
            ).fetchall()
            lesson_ids = [l["id"] for l in t_lessons]
            completed = False
            stars = 0
            if lesson_ids:
                placeholders = ",".join("?" * len(lesson_ids))
                cnt = conn.execute(
                    f"SELECT COUNT(*) as n FROM progress WHERE lesson_id IN ({placeholders}) AND finished_at IS NOT NULL",
                    lesson_ids
                ).fetchone()["n"]
                completed = cnt > 0
                if completed:
                    best = conn.execute(
                        f"SELECT MAX(score*1.0/max_score) as pct FROM progress WHERE lesson_id IN ({placeholders}) AND finished_at IS NOT NULL AND max_score > 0",
                        lesson_ids
                    ).fetchone()["pct"]
                    pct = best or 0
                    stars = 3 if pct >= 0.9 else 2 if pct >= 0.6 else 1
            topic_list.append({
                **dict(t),
                "lessons": [dict(l) for l in t_lessons],
                "lesson_count": len(t_lessons),
                "completed": completed,
                "stars": stars,
            })
        result.append({**dict(s), "intro_done": bool(s["intro_seen_at"]), "topics": topic_list})
    conn.close()
    return {"grade": grade, "subject": subject, "sections": result}

@app.get("/api/sections/{section_id}")
def get_section(section_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    s = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
    conn.close()
    if not s:
        raise HTTPException(404, "Not found")
    return {**dict(s), "intro_done": bool(s["intro_seen_at"])}

@app.post("/api/sections/{section_id}/intro-done")
def complete_intro(section_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    conn.execute("UPDATE sections SET intro_seen_at=datetime('now') WHERE id=?", (section_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/sections")
def create_section(data: SectionIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO sections (grade,subject,title,order_index,intro) VALUES (?,?,?,?,?)",
              (data.grade, data.subject, data.title, data.order_index, data.intro))
    sid = c.lastrowid; conn.commit(); conn.close()
    return {"id": sid}

@app.put("/api/sections/{section_id}")
def update_section(section_id: int, data: SectionIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE sections SET grade=?,subject=?,title=?,order_index=?,intro=? WHERE id=?",
                 (data.grade, data.subject, data.title, data.order_index, data.intro, section_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/sections/{section_id}")
def delete_section(section_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    topic_ids = [r["id"] for r in conn.execute("SELECT id FROM topics WHERE section_id=?", (section_id,)).fetchall()]
    if topic_ids:
        conn.execute("UPDATE lessons SET topic_id=NULL WHERE topic_id IN (%s)" % ",".join("?"*len(topic_ids)), topic_ids)
        conn.execute("DELETE FROM topics WHERE section_id=?", (section_id,))
    conn.execute("DELETE FROM sections WHERE id=?", (section_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/topics")
def create_topic(data: TopicIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
              (data.section_id, data.title, data.order_index))
    tid = c.lastrowid; conn.commit(); conn.close()
    return {"id": tid}

@app.put("/api/topics/{topic_id}")
def update_topic(topic_id: int, data: TopicIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE topics SET section_id=?,title=?,order_index=? WHERE id=?",
                 (data.section_id, data.title, data.order_index, topic_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/topics/{topic_id}")
def delete_topic(topic_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET topic_id=NULL WHERE topic_id=?", (topic_id,))
    conn.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/topics/{topic_id}")
def get_topic(topic_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    t = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if not t:
        conn.close(); raise HTTPException(404, "Not found")
    s = conn.execute("SELECT * FROM sections WHERE id=?", (t["section_id"],)).fetchone()
    lessons = conn.execute("SELECT * FROM lessons WHERE topic_id=? AND active=1 ORDER BY created_at", (topic_id,)).fetchall()
    conn.close()
    return {**dict(t), "section": dict(s) if s else None, "lessons": [dict(l) for l in lessons]}

class ImportCurriculumIn(BaseModel):
    grade: int
    subject: str
    text: str

@app.post("/api/curriculum/import")
def import_curriculum(data: ImportCurriculumIn, role: str = Depends(require_parent)):
    """Импорт программы из текста в формате:
       **1. Раздел**
       - **Тема:** описание...
       Повторный импорт безопасен — существующие разделы/темы (по совпадению названия) не дублируются."""
    parsed = parse_curriculum_text(data.text)
    if not parsed:
        raise HTTPException(400, "Не удалось распознать структуру. Формат: **1. Раздел** и пункты - **Тема:** описание")
    conn = get_conn()
    existing_sections = {r["title"]: r["id"] for r in conn.execute(
        "SELECT id, title FROM sections WHERE grade=? AND subject=?", (data.grade, data.subject)).fetchall()}
    base_order = len(existing_sections)
    sections_created, topics_created = 0, 0
    for i, sec in enumerate(parsed):
        if sec["title"] in existing_sections:
            sid = existing_sections[sec["title"]]
        else:
            c = conn.cursor()
            c.execute("INSERT INTO sections (grade,subject,title,order_index) VALUES (?,?,?,?)",
                      (data.grade, data.subject, sec["title"], base_order + i))
            sid = c.lastrowid
            existing_sections[sec["title"]] = sid
            sections_created += 1
        existing_topics = {r["title"] for r in conn.execute(
            "SELECT title FROM topics WHERE section_id=?", (sid,)).fetchall()}
        topic_base = conn.execute("SELECT COUNT(*) as n FROM topics WHERE section_id=?", (sid,)).fetchone()["n"]
        added = 0
        for t_title in sec["topics"]:
            if t_title in existing_topics:
                continue
            conn.execute("INSERT INTO topics (section_id,title,order_index) VALUES (?,?,?)",
                         (sid, t_title, topic_base + added))
            added += 1
        topics_created += added
    conn.commit(); conn.close()
    return {"sections_found": len(parsed), "sections_created": sections_created, "topics_created": topics_created}

# ── Lessons ───────────────────────────────────────────────────────────────────

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

@app.get("/api/lessons")
def list_lessons(subject: Optional[str] = None, topic_id: Optional[int] = None, role: str = Depends(require_any)):
    conn = get_conn()
    q = """SELECT l.*,
                  s.id           AS section_id,
                  s.title        AS section_title,
                  s.order_index  AS section_order,
                  t.title        AS topic_title,
                  t.order_index  AS topic_order
           FROM lessons l
           LEFT JOIN topics t   ON t.id = l.topic_id
           LEFT JOIN sections s ON s.id = t.section_id
           WHERE l.active=1"""
    params = []
    if subject:
        q += " AND l.subject=?"; params.append(subject)
    if topic_id:
        q += " AND l.topic_id=?"; params.append(topic_id)
    rows = conn.execute(q + " ORDER BY l.subject, s.order_index, t.order_index, l.created_at", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/lessons/{lesson_id}")
def get_lesson(lesson_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@app.post("/api/lessons")
def create_lesson(data: LessonIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO lessons
        (subject,grade,topic,topic_id,context_theme,explanation,explanation_game,questions,boss_task,coins_lesson,coins_boss)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (data.subject, data.grade, data.topic, data.topic_id, data.context_theme,
         data.explanation, data.explanation_game,
         data.questions, data.boss_task, data.coins_lesson, data.coins_boss))
    lid = c.lastrowid; conn.commit(); conn.close()
    return {"id": lid}

@app.put("/api/lessons/{lesson_id}")
def update_lesson(lesson_id: int, data: LessonIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("""UPDATE lessons SET subject=?,grade=?,topic=?,topic_id=?,context_theme=?,
        explanation=?,explanation_game=?,questions=?,boss_task=?,coins_lesson=?,coins_boss=?
        WHERE id=?""",
        (data.subject, data.grade, data.topic, data.topic_id, data.context_theme,
         data.explanation, data.explanation_game,
         data.questions, data.boss_task, data.coins_lesson, data.coins_boss, lesson_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET active=0 WHERE id=?", (lesson_id,))
    conn.commit(); conn.close()
    return {"ok": True}

# ── Upload ────────────────────────────────────────────────────────────────────

@app.delete("/api/lessons/{lesson_id}/infographic")
def clear_infographic(lesson_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE lessons SET infographic=NULL WHERE id=?", (lesson_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/lessons/{lesson_id}/upload-audio")
async def upload_audio(lesson_id: int, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "ogg", "wav", "m4a"):
        raise HTTPException(400, "Unsupported format")
    fpath = f"{UPLOAD_DIR}/audio/lesson_{lesson_id}.{ext}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    conn = get_conn()
    conn.execute("UPDATE lessons SET audio_file=? WHERE id=?",
                 (f"/uploads/audio/lesson_{lesson_id}.{ext}", lesson_id))
    conn.commit(); conn.close()
    return {"audio_file": f"/uploads/audio/lesson_{lesson_id}.{ext}"}

@app.post("/api/lessons/{lesson_id}/upload-image")
async def upload_image(lesson_id: int, file: UploadFile = File(...), role: str = Depends(require_parent)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        raise HTTPException(400, "Unsupported format")
    fpath = f"{UPLOAD_DIR}/images/lesson_{lesson_id}.{ext}"
    with open(fpath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    conn = get_conn()
    conn.execute("UPDATE lessons SET infographic=? WHERE id=?",
                 (f"/uploads/images/lesson_{lesson_id}.{ext}", lesson_id))
    conn.commit(); conn.close()
    return {"infographic": f"/uploads/images/lesson_{lesson_id}.{ext}"}

# ── Articles (познавательные материалы — без контроля знаний) ────────────────────

MATERIAL_SUBJECTS = {
    "biology": "Биология", "chemistry": "Химия", "geography": "География",
    "informatics": "Компьютеры", "programming": "Программирование", "earth": "Планета Земля",
    "space": "Космос", "animals": "Животные", "plants": "Растения", "micro": "Микромир",
    "body": "Человек", "senses": "Органы чувств", "health": "Забота о здоровье",
    "physics": "Физика", "inventions": "Изобретения", "history": "История цивилизации",
    "economics": "Экономика детям", "ecology": "Экология", "food": "Еда", "art": "Искусство",
    "architecture": "Архитектура", "transport": "Транспорт", "why": "Почему?",
    "facts": "Интересные факты", "life": "Что попробовать в жизни",
}

class ArticleIn(BaseModel):
    subject: str
    grade: Optional[int] = None
    title: str
    summary: Optional[str] = None
    cover_image: Optional[str] = None
    blocks: list

@app.get("/api/materials/subjects")
def material_subjects(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT subject, COUNT(*) as cnt FROM articles WHERE active=1 GROUP BY subject"
    ).fetchall()
    counts = {r["subject"]: r["cnt"] for r in rows}
    conn.close()
    return [{"key": k, "label": v, "count": counts.get(k, 0)} for k, v in MATERIAL_SUBJECTS.items()]

@app.get("/api/articles")
def list_articles(subject: Optional[str] = None, role: str = Depends(require_any)):
    conn = get_conn()
    q = "SELECT id, subject, grade, title, summary, cover_image, created_at FROM articles WHERE active=1"
    params = []
    if subject:
        q += " AND subject=?"; params.append(subject)
    rows = conn.execute(q + " ORDER BY created_at DESC", params).fetchall()
    ids = [r["id"] for r in rows]
    read_ids = set()
    if ids:
        placeholders = ",".join("?" * len(ids))
        read_ids = {r["article_id"] for r in conn.execute(
            f"SELECT DISTINCT article_id FROM article_reads WHERE article_id IN ({placeholders})", ids
        ).fetchall()}
    conn.close()
    return [{**dict(r), "read": r["id"] in read_ids} for r in rows]

@app.get("/api/articles/{article_id}")
def get_article(article_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    d = dict(row)
    try: d["blocks"] = json.loads(d["blocks"])
    except Exception: d["blocks"] = []
    return d

@app.post("/api/articles")
def create_article(data: ArticleIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO articles (subject,grade,title,summary,cover_image,blocks,manually_edited) VALUES (?,?,?,?,?,?,1)",
              (data.subject, data.grade, data.title, data.summary, data.cover_image,
               json.dumps(data.blocks, ensure_ascii=False)))
    conn.commit(); aid = c.lastrowid; conn.close()
    return {"id": aid}

@app.put("/api/articles/{article_id}")
def update_article(article_id: int, data: ArticleIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET subject=?,grade=?,title=?,summary=?,cover_image=?,blocks=?,manually_edited=1 WHERE id=?",
                 (data.subject, data.grade, data.title, data.summary, data.cover_image,
                  json.dumps(data.blocks, ensure_ascii=False), article_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/articles/{article_id}")
def delete_article(article_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET active=0 WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/articles/deleted/list")
def list_deleted_articles(role: str = Depends(require_parent)):
    """Диагностика: показывает материалы, помеченные как удалённые (active=0), чтобы можно было
       убедиться, что материал действительно удалён, восстановить его или убрать навсегда."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, subject, grade, title, summary, cover_image, created_at FROM articles WHERE active=0 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/articles/{article_id}/restore")
def restore_article(article_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE articles SET active=1 WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/articles/{article_id}/purge")
def purge_article(article_id: int, role: str = Depends(require_parent)):
    """Безвозвратное удаление строки из БД (в отличие от обычного DELETE, который только
       помечает active=0). Используется, чтобы окончательно убрать дубликаты/мусорные записи."""
    conn = get_conn()
    conn.execute("DELETE FROM articles WHERE id=?", (article_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/articles/{article_id}/read")
def mark_article_read(article_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    already = conn.execute("SELECT id FROM article_reads WHERE article_id=?", (article_id,)).fetchone()
    if not already:
        conn.execute("INSERT INTO article_reads (article_id) VALUES (?)", (article_id,))
        conn.commit()
    conn.close()
    return {"ok": True}


# ── Рассылка материалов «на изучение» через Telegram ────────────────────────

import random as _random

def pick_next_articles(conn, n: int = 3):
    """Выбирает следующие n материалов для отправки так, чтобы они не повторялись,
    пока не будут отправлены все существующие материалы хотя бы по разу. Приоритет:
    сначала те, что ещё никогда не отправлялись (в случайном порядке), затем —
    отправленные раньше всех остальных (по дате последней отправки, от старых к новым)."""
    active_ids = [r["id"] for r in conn.execute("SELECT id FROM articles WHERE active=1").fetchall()]
    if not active_ids:
        return []
    rows = conn.execute("""
        SELECT maa.article_id as article_id, MAX(a.sent_at) as last_sent
        FROM material_assignment_articles maa
        JOIN material_assignments a ON a.id = maa.assignment_id
        GROUP BY maa.article_id
    """).fetchall()
    last_sent = {r["article_id"]: r["last_sent"] for r in rows}
    never_sent = [a for a in active_ids if a not in last_sent]
    _random.shuffle(never_sent)
    already_sent_sorted = sorted(
        (a for a in active_ids if a in last_sent),
        key=lambda a: last_sent[a]
    )
    ordered = never_sent + already_sent_sorted
    return ordered[:n]

class MaterialAssignmentIn(BaseModel):
    coins_reward: int = 30
    count: int = 3

@app.post("/api/materials/assignments")
async def create_material_assignment(data: MaterialAssignmentIn, role: str = Depends(require_parent)):
    conn = get_conn()
    article_ids = pick_next_articles(conn, max(1, min(data.count, 10)))
    if not article_ids:
        conn.close()
        raise HTTPException(400, "Нет ни одного материала, чтобы отправить")
    articles = conn.execute(
        f"SELECT id, title FROM articles WHERE id IN ({','.join('?' * len(article_ids))})", article_ids
    ).fetchall()
    titles_by_id = {r["id"]: r["title"] for r in articles}
    ordered_titles = [titles_by_id[a] for a in article_ids if a in titles_by_id]

    c = conn.cursor()
    c.execute(
        "INSERT INTO material_assignments (article_ids, coins_reward) VALUES (?,?)",
        (json.dumps(article_ids), data.coins_reward)
    )
    assignment_id = c.lastrowid
    for aid in article_ids:
        c.execute("INSERT INTO material_assignment_articles (assignment_id, article_id) VALUES (?,?)", (assignment_id, aid))
    conn.commit()

    cfg = get_telegram_config(conn)
    child = os.environ.get("CHILD_NAME", "Тимофей")
    link = f"{cfg['site_url']}/materials/assignment/{assignment_id}"
    topics_text = "\n".join(f"🔹 {t}" for t in ordered_titles)
    message = (
        f"Привет, {child}! 👋😊\n\n"
        f"📚✨ Сегодня тебе нужно узнать кое-что новое!\n"
        f"{topics_text}\n\n"
        f"🧐 Ознакомься и перескажи родителям, о чём ты узнал.\n"
        f"🏆 Награда: {data.coins_reward} 🪙 монет.\n\n"
        f"🔗 Вот ссылка на материалы: {link}"
    )
    ok, error = await tg_send_result(message)
    conn.execute("UPDATE material_assignments SET telegram_ok=?, telegram_error=? WHERE id=?",
                 (1 if ok else 0, error, assignment_id))
    conn.commit()
    conn.close()
    return {
        "id": assignment_id, "titles": ordered_titles, "coins_reward": data.coins_reward,
        "link": link, "telegram_ok": ok, "telegram_error": error,
    }

@app.get("/api/materials/assignments")
def list_material_assignments(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM material_assignments ORDER BY sent_at DESC LIMIT 60").fetchall()
    result = []
    for r in rows:
        ids = json.loads(r["article_ids"])
        titles = []
        if ids:
            arts = conn.execute(
                f"SELECT id, title FROM articles WHERE id IN ({','.join('?' * len(ids))})", ids
            ).fetchall()
            by_id = {a["id"]: a["title"] for a in arts}
            titles = [by_id.get(i, f"(материал {i} удалён)") for i in ids]
        result.append({
            "id": r["id"], "titles": titles, "coins_reward": r["coins_reward"],
            "sent_at": r["sent_at"], "completed_at": r["completed_at"],
            "telegram_ok": bool(r["telegram_ok"]), "telegram_error": r["telegram_error"],
        })
    conn.close()
    return result

@app.get("/api/materials/assignments/{assignment_id}")
def get_material_assignment(assignment_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    a = conn.execute("SELECT * FROM material_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not a:
        conn.close(); raise HTTPException(404, "Задание не найдено")
    ids = json.loads(a["article_ids"])
    articles = []
    for aid in ids:
        row = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        if not row:
            continue
        d = dict(row)
        try: d["blocks"] = json.loads(d["blocks"])
        except Exception: d["blocks"] = []
        articles.append(d)
    conn.close()
    return {
        "id": a["id"], "articles": articles, "coins_reward": a["coins_reward"],
        "sent_at": a["sent_at"], "completed_at": a["completed_at"],
    }

@app.post("/api/materials/assignments/{assignment_id}/complete")
async def complete_material_assignment(assignment_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    a = conn.execute("SELECT * FROM material_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not a:
        conn.close(); raise HTTPException(404, "Задание не найдено")
    if a["completed_at"]:
        conn.close()
        return {"ok": True, "already_completed": True, "coins_earned": 0}
    conn.execute("UPDATE material_assignments SET completed_at=datetime('now') WHERE id=?", (assignment_id,))
    coins = a["coins_reward"] or 0
    if coins > 0:
        conn.execute("INSERT INTO coins (amount,type,note) VALUES (?,?,?)",
                     (coins, "earned", "Изучение познавательных материалов"))
    conn.commit()
    ids = json.loads(a["article_ids"])
    titles = []
    if ids:
        arts = conn.execute(f"SELECT title FROM articles WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        titles = [r["title"] for r in arts]
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"📚✅ <b>{child} изучил материалы и рассказал о них!</b>\n"
        f"Темы: {', '.join(titles)}\n+{coins} 🪙 монет"
    ))
    return {"ok": True, "already_completed": False, "coins_earned": coins}



class StartLessonIn(BaseModel):
    lesson_id: int

def _number_group_pattern(digits: str) -> str:
    """Строит паттерн для целой части числа, где между группами по 3 цифры
    (справа налево) допускается необязательный пробел — обычный или
    неразрывный. Это нужно, чтобы «987650» засчитывался и как «987650»,
    и как «987 650» (привычная запись больших чисел с разделением разрядов
    пробелом), без чего верные ответы с пробелом ошибочно считались неверными."""
    rev = digits[::-1]
    chunks = [rev[i:i + 3][::-1] for i in range(0, len(rev), 3)]
    chunks = chunks[::-1]
    return r"[ \u00a0]?".join(re.escape(c) for c in chunks)


def _number_pattern(num: str) -> str:
    if "." in num:
        int_part, frac_part = num.split(".", 1)
        return _number_group_pattern(int_part) + r"[.,]" + re.escape(frac_part)
    return _number_group_pattern(num)


def _check_boss_answer(expected: str, given: str) -> bool:
    """Сверяет ответ ребёнка на финальное задание с эталонным ответом.
    Числа сверяются как отдельные "слова" (без ложных совпадений внутри
    других чисел), текстовые ответы — по вхождению как отдельного слова."""
    if not expected or not given:
        return False
    given_norm = given.strip().lower().replace(",", ".")
    numbers = re.findall(r"-?\d+(?:[.,]\d+)?", expected)
    if numbers:
        numbers_norm = [n.replace(",", ".") for n in numbers]

        def present(num: str) -> bool:
            pat = r"(?<!\d)" + _number_pattern(num) + r"(?!\d)"
            return bool(re.search(pat, given_norm))

        if all(present(n) for n in numbers_norm):
            return True
        # Иногда эталон формулируется как "промежуточный результат, итоговый код",
        # где итоговое число буквально составлено из цифр промежуточного
        # (например, "5 целых 1/6, код 516" — код 516 включает цифры 5, 1 и 6).
        # В этом случае ребёнок, назвавший только итоговое число, прав — но
        # проверка выше не засчитает это, так как цифры 5/1/6 внутри "516" не
        # являются отдельными "словами". Разрешаем такой ответ отдельно: если
        # самое длинное число эталона само присутствует в ответе как отдельное
        # число, а все остальные числа эталона целиком состоят из его цифр
        # (т.е. являются его частью), засчитываем ответ.
        longest = max(numbers_norm, key=len)
        others = [n for n in numbers_norm if n != longest]
        if others and all(n in longest for n in others) and present(longest):
            return True
        return False
    exp_norm = expected.strip().lower()
    pat = r"(?<!\w)" + re.escape(exp_norm) + r"(?!\w)"
    return bool(re.search(pat, given_norm, flags=re.UNICODE))


class FinishLessonIn(BaseModel):
    progress_id: int
    score: int
    total: int = 5
    boss_done: bool = False
    boss_answer: Optional[str] = None



@app.post("/api/progress/start")
async def start_lesson(data: StartLessonIn, role: str = Depends(require_any)):
    conn = get_conn()
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (data.lesson_id,)).fetchone()
    if not lesson:
        conn.close(); raise HTTPException(404, "Lesson not found")
    c = conn.cursor()
    c.execute("INSERT INTO progress (lesson_id) VALUES (?)", (data.lesson_id,))
    pid = c.lastrowid; conn.commit(); conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"📚 <b>{child} начал урок</b>\n"
        f"Предмет: {SUBJECT_LABELS.get(lesson['subject'], lesson['subject'])}\n"
        f"Тема: {lesson['topic']}"
    ))
    return {"progress_id": pid}

@app.post("/api/progress/finish")
async def finish_lesson(data: FinishLessonIn, role: str = Depends(require_any)):
    conn = get_conn()
    prog   = conn.execute("SELECT * FROM progress WHERE id=?", (data.progress_id,)).fetchone()
    if not prog:
        conn.close(); raise HTTPException(404)
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (prog["lesson_id"],)).fetchone()
    # Монеты за урок пропорциональны результату: score/total карточек.
    # Одна неверная карточка = минус (coins_lesson / total) монет — весомее, чем плоский штраф.
    max_score = data.total if data.total and data.total > 0 else 5
    ratio = max(data.score / max_score, 0.1) if max_score > 0 else 0.1
    base_coins = lesson["coins_lesson"] if lesson else 50
    lesson_coins = max(round(base_coins * ratio), 5)  # минимум 5 монет
    # Финальное задание: ответ ребёнка сверяется с эталонным на сервере —
    # клиенту нельзя доверять флаг "выполнено правильно"
    boss_correct = False
    if data.boss_done and lesson and lesson["boss_task"]:
        try:
            boss = json.loads(lesson["boss_task"])
        except Exception:
            boss = None
        expected = (boss or {}).get("answer")
        if expected:
            boss_correct = _check_boss_answer(expected, data.boss_answer or "")
    boss_coins = (lesson["coins_boss"] if lesson else 30) if boss_correct else 0
    coins = lesson_coins + boss_coins
    conn.execute("UPDATE progress SET finished_at=datetime('now'),score=?,max_score=?,boss_done=?,coins_earned=? WHERE id=?",
                 (data.score, max_score, 1 if boss_correct else 0, coins, data.progress_id))
    conn.execute("INSERT INTO coins (amount,type,note) VALUES (?,?,?)",
                 (coins, "earned", f"Урок: {lesson['topic'] if lesson else ''}"))
    _update_streak(conn); conn.commit()
    streak = conn.execute("SELECT days FROM streak WHERE id=1").fetchone()
    conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"✅ <b>{child} завершил урок!</b>\n"
        f"Тема: {lesson['topic'] if lesson else ''}\n"
        f"Результат: {data.score}/5 · +{coins} монет 🪙\n"
        f"Серия: {streak['days'] if streak else 0} дней 🔥"
    ))
    return {"coins_earned": coins, "boss_correct": boss_correct, "lesson_coins": lesson_coins, "boss_coins": boss_coins}

def _update_streak(conn):
    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
    if row["last_day"] == today:
        return
    new_days = (row["days"] + 1) if row["last_day"] == yesterday else 1
    conn.execute("UPDATE streak SET days=?,last_day=? WHERE id=1", (new_days, today))

@app.get("/api/progress")
def get_progress(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("""SELECT p.*, l.topic, l.subject FROM progress p
        LEFT JOIN lessons l ON p.lesson_id=l.id
        ORDER BY p.started_at DESC LIMIT 50""").fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Навыки (логические/классические задачи — картинка + до 3 подсказок) ────────

class SkillCategoryIn(BaseModel):
    title: str

class SkillIn(BaseModel):
    category_id: int
    image_url: Optional[str] = None
    hint1: Optional[str] = None
    hint2: Optional[str] = None
    hint3: Optional[str] = None
    answer: Optional[str] = None

@app.get("/api/skill-categories")
def list_skill_categories(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, order_index FROM skill_categories WHERE active=1 ORDER BY order_index, id"
    ).fetchall()
    counts_rows = conn.execute(
        "SELECT category_id, COUNT(*) as cnt FROM skills WHERE active=1 GROUP BY category_id"
    ).fetchall()
    conn.close()
    counts = {r["category_id"]: r["cnt"] for r in counts_rows}
    return [{**dict(r), "count": counts.get(r["id"], 0)} for r in rows]

@app.post("/api/skill-categories")
def create_skill_category(data: SkillCategoryIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    max_order = c.execute("SELECT MAX(order_index) as m FROM skill_categories").fetchone()["m"]
    c.execute("INSERT INTO skill_categories (title, order_index) VALUES (?,?)",
              (data.title, (max_order or 0) + 1))
    conn.commit(); cid = c.lastrowid; conn.close()
    return {"id": cid}

@app.put("/api/skill-categories/{category_id}")
def update_skill_category(category_id: int, data: SkillCategoryIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET title=? WHERE id=?", (data.title, category_id))
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/skill-categories/{category_id}")
def delete_skill_category(category_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET active=0 WHERE id=?", (category_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/skill-categories/{category_id}/restore")
def restore_skill_category(category_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skill_categories SET active=1 WHERE id=?", (category_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/skill-categories/deleted/list")
def list_deleted_skill_categories(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, order_index FROM skill_categories WHERE active=0 ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/skills")
def list_skills(category_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, category_id, image_url, hint1, hint2, hint3, answer, order_index FROM skills "
        "WHERE active=1 AND category_id=? ORDER BY order_index, id",
        (category_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/skills/all-active")
def list_all_active_skills(role: str = Depends(require_any)):
    """Все активные задания вместе с названием категории — для слайдшоу (перемешивание
       по категориям делается на фронтенде, как и в MaterialsSlideshowPage)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT sk.id, sk.category_id, sk.image_url, sk.hint1, sk.hint2, sk.hint3, sk.answer, sc.title as category_title
        FROM skills sk
        JOIN skill_categories sc ON sc.id = sk.category_id
        WHERE sk.active=1 AND sc.active=1
        ORDER BY sk.order_index, sk.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: int, role: str = Depends(require_any)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)

@app.post("/api/skills")
def create_skill(data: SkillIn, role: str = Depends(require_parent)):
    conn = get_conn()
    c = conn.cursor()
    max_order = c.execute(
        "SELECT MAX(order_index) as m FROM skills WHERE category_id=?", (data.category_id,)
    ).fetchone()["m"]
    c.execute(
        "INSERT INTO skills (category_id,image_url,hint1,hint2,hint3,answer,order_index) VALUES (?,?,?,?,?,?,?)",
        (data.category_id, data.image_url, data.hint1, data.hint2, data.hint3, data.answer, (max_order or 0) + 1)
    )
    conn.commit(); sid = c.lastrowid; conn.close()
    return {"id": sid}

@app.put("/api/skills/{skill_id}")
def update_skill(skill_id: int, data: SkillIn, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute(
        "UPDATE skills SET category_id=?,image_url=?,hint1=?,hint2=?,hint3=?,answer=? WHERE id=?",
        (data.category_id, data.image_url, data.hint1, data.hint2, data.hint3, data.answer, skill_id)
    )
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skills SET active=0 WHERE id=?", (skill_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/skills/{skill_id}/restore")
def restore_skill(skill_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE skills SET active=1 WHERE id=?", (skill_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/skills/deleted/list")
def list_deleted_skills(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT sk.id, sk.category_id, sk.image_url, sk.hint1, sk.hint2, sk.hint3, sc.title as category_title
        FROM skills sk
        LEFT JOIN skill_categories sc ON sc.id = sk.category_id
        WHERE sk.active=0
        ORDER BY sk.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(role: str = Depends(require_any)):
    conn = get_conn()
    total   = conn.execute("SELECT COUNT(*) as n FROM progress WHERE finished_at IS NOT NULL").fetchone()["n"]
    earned  = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent   = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    streak  = conn.execute("SELECT days FROM streak WHERE id=1").fetchone()
    avg_row = conn.execute("SELECT AVG(score*1.0/max_score) as a FROM progress WHERE finished_at IS NOT NULL").fetchone()
    by_subj = conn.execute("""SELECT l.subject, COUNT(*) as cnt, AVG(p.score*1.0/p.max_score) as avg
        FROM progress p JOIN lessons l ON p.lesson_id=l.id WHERE p.finished_at IS NOT NULL
        GROUP BY l.subject""").fetchall()
    week    = conn.execute("""SELECT date(started_at) as day, COUNT(*) as cnt
        FROM progress WHERE started_at >= date('now','-7 days')
        GROUP BY date(started_at) ORDER BY day""").fetchall()
    weak_from_mistakes = conn.execute("""
        SELECT l.id as lesson_id, l.topic, l.subject, COUNT(m.id) as mistake_count, MAX(m.created_at) as last_at
        FROM mistakes m JOIN lessons l ON m.lesson_id = l.id
        WHERE l.active=1
        GROUP BY l.id
        ORDER BY last_at DESC
        LIMIT 8
    """).fetchall()
    weak_from_score = conn.execute("""SELECT l.id as lesson_id, l.topic, l.subject, AVG(p.score*1.0/p.max_score) as avg, COUNT(*) as attempts
        FROM progress p JOIN lessons l ON p.lesson_id=l.id WHERE p.finished_at IS NOT NULL AND l.active=1
        GROUP BY l.id HAVING avg < 0.6 AND attempts >= 1 ORDER BY avg ASC LIMIT 5""").fetchall()
    seen, weak_topics = set(), []
    for r in weak_from_mistakes:
        if r["lesson_id"] in seen: continue
        seen.add(r["lesson_id"])
        weak_topics.append({
            "lesson_id": r["lesson_id"], "topic": r["topic"], "subject": r["subject"],
            "mistake_count": r["mistake_count"], "avg": None,
        })
    for r in weak_from_score:
        if r["lesson_id"] in seen: continue
        seen.add(r["lesson_id"])
        weak_topics.append({
            "lesson_id": r["lesson_id"], "topic": r["topic"], "subject": r["subject"],
            "mistake_count": None, "avg": r["avg"],
        })
    weak_topics = weak_topics[:6]
    conn.close()
    return {
        "total_lessons": total, "balance": earned - spent,
        "total_coins_earned": earned, "streak_days": streak["days"] if streak else 0,
        "avg_score": round(avg_row["a"] * 100) if avg_row["a"] else 0,
        "by_subject": [dict(r) for r in by_subj],
        "week_activity": [dict(r) for r in week],
        "weak_topics": weak_topics,
    }

# ── Coins & Rewards ───────────────────────────────────────────────────────────

@app.get("/api/coins/balance")
def get_balance(role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent  = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    conn.close()
    return {"balance": earned - spent, "earned": earned, "spent": spent}

class MistakeIn(BaseModel):
    lesson_id: int
    question_text: Optional[str] = None
    chosen_text: Optional[str] = None
    correct_text: Optional[str] = None

@app.post("/api/mistakes")
def log_mistake(data: MistakeIn, role: str = Depends(require_any)):
    """Фиксирует неверный ответ на карточке — без начисления/списания монет,
    только для сбора статистики по проблемным темам (родитель видит, что подтянуть)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO mistakes (lesson_id, question_text, chosen_text, correct_text) VALUES (?,?,?,?)",
        (data.lesson_id, data.question_text, data.chosen_text, data.correct_text)
    )
    conn.commit(); conn.close()
    return {"ok": True}

def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11: return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14): return few
    return many

@app.get("/api/lessons/{lesson_id}/reinforcement-prompt")
def reinforcement_prompt(lesson_id: int, role: str = Depends(require_parent)):
    """Собирает по уроку (тема, где ребёнок ошибается) готовый текстовый запрос, который родитель
    может скопировать и прислать Claude в чат, чтобы тот написал дополнительный урок-закрепление
    в код и задеплоил — контент уроков в проекте принципиально не редактируется через UI-формы
    (см. CONTEXT_FOR_CLAUDE.md), поэтому этот эндпоинт не создаёт урок сам, а только готовит
    контекст (тему, раздел, конкретные ошибки, статистику) для человека-в-цикле."""
    conn = get_conn()
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    if not lesson:
        conn.close(); raise HTTPException(404, "Урок не найден")

    section_title = None
    if lesson["topic_id"]:
        srow = conn.execute("""
            SELECT s.title as section_title FROM topics t JOIN sections s ON t.section_id = s.id
            WHERE t.id=?
        """, (lesson["topic_id"],)).fetchone()
        if srow:
            section_title = srow["section_title"]

    prog = conn.execute("""
        SELECT COUNT(*) as attempts, AVG(score*1.0/max_score) as avg
        FROM progress WHERE lesson_id=? AND finished_at IS NOT NULL
    """, (lesson_id,)).fetchone()

    mistakes = conn.execute("""
        SELECT question_text, chosen_text, correct_text FROM mistakes
        WHERE lesson_id=? ORDER BY created_at DESC LIMIT 15
    """, (lesson_id,)).fetchall()
    conn.close()

    lines = ["Материал для урока закрепления (на основе ошибок ребёнка)", ""]
    lines.append(f"Предмет: {SUBJECT_LABELS.get(lesson['subject'], lesson['subject'])} ({lesson['grade']} класс)")
    if section_title:
        lines.append(f"Раздел: {section_title}")
    lines.append(f"Тема: {lesson['topic']} (урок id {lesson_id})")

    if prog and prog["attempts"]:
        att = prog["attempts"]
        lines.append(f"Точность по теме: {round((prog['avg'] or 0) * 100)}% ({att} {_plural_ru(att, 'попытка', 'попытки', 'попыток')})")

    lines.append("")
    if mistakes:
        lines.append(f"Конкретные ошибки ({len(mistakes)}):")
        for i, m in enumerate(mistakes, 1):
            parts = []
            if m["question_text"]: parts.append(f"вопрос «{m['question_text']}»")
            if m["chosen_text"]:   parts.append(f"ответил «{m['chosen_text']}»")
            if m["correct_text"]:  parts.append(f"правильно «{m['correct_text']}»")
            lines.append(f"{i}. " + ", ".join(parts))
    else:
        lines.append("Отдельные вопросы с ошибками не зафиксированы — тема попала в слабые по среднему баллу за попытки.")

    lines.append("")
    lines.append(
        f"Задача: добавь дополнительный урок «Закрепление: {lesson['topic']}»"
        + (f" в раздел «{section_title}»" if section_title else "")
        + ", с другими конкретными числами/примерами, но тем же навыком — так, чтобы закрепить "
          "именно то, в чём были ошибки выше. Добавь через seed_topic_if_missing + "
          "seed_lesson_if_missing (в конец раздела), сохрани формат LESSON_DICT, сюжетную линию "
          "и общий тон уроков проекта (см. docs/CONTEXT_FOR_CLAUDE.md). После — задеплой."
    )
    return {"prompt": "\n".join(lines)}

@app.get("/api/mistakes")
def list_mistakes(role: str = Depends(require_parent)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.id, m.question_text, m.chosen_text, m.correct_text, m.created_at,
               l.id as lesson_id, l.topic, l.subject
        FROM mistakes m JOIN lessons l ON m.lesson_id = l.id
        ORDER BY m.created_at DESC LIMIT 200
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

class PenaltyIn(BaseModel):
    lesson_id: Optional[int] = None
    amount: int = 5
    note: Optional[str] = None

@app.post("/api/coins/penalty")
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

class RewardIn(BaseModel):
    name: str
    cost_coins: int

@app.post("/api/rewards/request")
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

@app.get("/api/rewards")
def get_rewards(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM rewards ORDER BY requested_at DESC LIMIT 30").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/rewards/{reward_id}/approve")
async def approve_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    r = conn.execute("SELECT * FROM rewards WHERE id=?", (reward_id,)).fetchone()
    if not r:
        conn.close(); raise HTTPException(404)
    conn.execute("UPDATE rewards SET status='approved',approved_at=datetime('now') WHERE id=?", (reward_id,))
    conn.commit(); conn.close()
    asyncio.create_task(tg_send(f"✅ Одобрено: <b>{r['name']}</b> ({r['cost_coins']} монет)"))
    return {"ok": True}

@app.post("/api/rewards/{reward_id}/reject")
def reject_reward(reward_id: int, role: str = Depends(require_parent)):
    conn = get_conn()
    conn.execute("UPDATE rewards SET status='rejected' WHERE id=?", (reward_id,))
    conn.commit(); conn.close()
    return {"ok": True}
