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
    "subject_icons": {"math": None, "russian": None, "science": None, "history": None},
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
    """Собирает {topic: answer} из всех LESSON_DICT-констант модуля верхнего уровня, у которых
    задан boss_task.answer. Используется backfill_missing_boss_answers() как источник истины —
    "правильный" ответ для темы всегда тот, что сейчас записан в коде."""
    result = {}
    for val in globals().values():
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

ARTICLE_WHY_RAIN = {
    "grade": 5,
    "summary": "Путешествие капли воды: испарение, облака, дождь, снег и круговорот воды в природе — с опытом и удивительными фактами.",
    "cover_image": "/content/rain-infographic.png",
    "blocks": [
        {"type": "heading", "text": "🌧️ Почему идёт дождь?"},
        {"type": "paragraph", "text": (
            "💧 Представь себе... Ты поставил на плиту кастрюлю с водой. Через некоторое время вода "
            "начинает исчезать. Но куда? Она не пропала. Она превратилась в невидимый водяной пар и "
            "поднялась вверх. Примерно то же самое происходит каждый день на нашей планете. Именно так "
            "начинается путешествие каждой дождевой капли."
        )},

        {"type": "heading", "text": "☀️ Шаг 1. Солнце нагревает воду"},
        {"type": "paragraph", "text": "Солнце постоянно согревает:"},
        {"type": "list", "items": ["🌊 океаны", "🏞️ реки", "🛶 озёра", "🌱 растения", "💧 даже лужи после дождя"]},
        {"type": "paragraph", "text": (
            "От тепла вода постепенно превращается в пар. Этот процесс называется испарением. "
            "Пар невидим, поэтому мы его почти не замечаем."
        )},
        {"type": "callout", "text": "💡 Интересный факт: за один солнечный день с поверхности океанов испаряются миллиарды тонн воды!"},

        {"type": "heading", "text": "☁️ Шаг 2. Пар превращается в облака"},
        {"type": "paragraph", "text": (
            "Чем выше поднимается водяной пар, тем холоднее становится воздух. Из-за холода пар начинает "
            "превращаться обратно в крошечные капельки воды. Этот процесс называется конденсацией. "
            "Миллиарды таких капелек собираются вместе. Так появляются облака."
        )},
        {"type": "callout", "text": "🔍 А знаешь ли ты? Одно большое облако может весить сотни тонн! Но капельки настолько маленькие, что воздух легко удерживает их."},

        {"type": "heading", "text": "💦 Шаг 3. Капельки растут"},
        {"type": "paragraph", "text": (
            "Внутри облака маленькие капельки постоянно сталкиваются друг с другом. Каждый раз они "
            "становятся чуть больше. Сначала они совсем крошечные. Потом размер увеличивается. "
            "Постепенно они становятся слишком тяжёлыми."
        )},

        {"type": "heading", "text": "🌧️ Шаг 4. Начинается дождь"},
        {"type": "paragraph", "text": (
            "Когда капли становятся достаточно тяжёлыми, воздух уже не может их удерживать. Они начинают "
            "падать на землю. Это и есть дождь. Пока капли летят вниз, некоторые становятся ещё больше, "
            "соединяясь с другими."
        )},

        {"type": "heading", "text": "❄️ Почему иногда идёт снег?"},
        {"type": "paragraph", "text": (
            "Если высоко в облаках очень холодно, вода превращается в маленькие ледяные кристаллы. "
            "Если по дороге к земле они не успевают растаять, мы видим снег. Если успевают растаять — "
            "идёт дождь."
        )},

        {"type": "heading", "text": "🌦️ Почему дождь бывает разным?"},
        {"type": "paragraph", "text": "Не каждый дождь одинаковый."},
        {"type": "subheading", "text": "🌦 Моросящий дождь"},
        {"type": "paragraph", "text": "Очень маленькие капли. Кажется, будто воздух стал влажным."},
        {"type": "subheading", "text": "🌧 Ливень"},
        {"type": "paragraph", "text": "Очень крупные капли падают быстро. Такой дождь может идти всего несколько минут, но воды выпадает очень много."},
        {"type": "subheading", "text": "⛈ Гроза"},
        {"type": "paragraph", "text": "Во время сильного дождя в облаках возникает электричество. Появляются молнии и гром."},
        {"type": "subheading", "text": "🌈 Грибной дождь"},
        {"type": "paragraph", "text": "Иногда дождь идёт, хотя солнце продолжает светить. После такого дождя часто появляется радуга."},

        {"type": "heading", "text": "🔄 Круговорот воды"},
        {"type": "paragraph", "text": "Дождь — это часть большого путешествия воды. Вот как оно происходит:"},
        {"type": "flow", "text": "🌊 Океан → ☀️ Испарение → ☁️ Облако → 🌧️ Дождь → 🏞️ Река → 🌊 Океан"},
        {"type": "paragraph", "text": (
            "Этот круговорот повторяется снова и снова уже миллиарды лет. Получается, что вода, которая "
            "сегодня падает тебе на ладонь, когда-то могла быть частью океана, ледника или даже каплей, "
            "которую «видели» динозавры!"
        )},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "💧 Самая большая известная дождевая капля была почти 8 миллиметров в диаметре.",
            "☁️ Одно большое облако может содержать миллионы литров воды.",
            "🌍 В среднем за год на Землю выпадает около 500 тысяч кубических километров осадков.",
            "🐸 В некоторых местах из-за сильных вихрей вместе с водой иногда падают рыбы или лягушки! Их поднимают смерчи над озёрами и реками.",
            "🌱 Без дождя на Земле почти не было бы растений, животных и людей.",
        ]},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Солнце нагревает воду.",
            "Вода испаряется и превращается в пар.",
            "Пар поднимается вверх и охлаждается.",
            "Появляются облака.",
            "Капли становятся всё больше.",
            "Когда они становятся тяжёлыми, начинается дождь.",
        ]},

        {"type": "heading", "text": "🧪 Попробуй провести опыт"},
        {"type": "experiment", "title": "Мини-круговорот воды дома",
         "materials": ["прозрачный стакан", "горячая вода (с помощью взрослых)", "тарелка", "несколько кубиков льда"],
         "steps": [
             "Налей в стакан немного горячей воды.",
             "Накрой стакан тарелкой.",
             "Положи на тарелку лёд.",
             "Подожди 3–5 минут.",
         ],
         "result": (
             "Внутри стакана образуются маленькие капельки, которые начнут стекать вниз, словно настоящий "
             "дождь. Так ты увидишь своими глазами, как водяной пар превращается в воду!"
         )},

        {"type": "question", "text": (
            "Если бы на Земле совсем перестали идти дожди, что произошло бы через неделю, через месяц и "
            "через год? Как изменилась бы жизнь растений, животных и людей? Попробуй представить и "
            "объяснить свои мысли."
        )},
    ],
}

ARTICLE_HOW_EARTH_FORMED = {
    "grade": 5,
    "summary": "Путешествие на 4,5 миллиарда лет назад: как из облака пыли и камней родилась наша планета, откуда взялись океаны и когда появилась жизнь.",
    "blocks": [
        {"type": "heading", "text": "🌍 Как появилась Земля?"},
        {"type": "paragraph", "text": (
            "🚀 Представь невероятное путешествие... Представь, что ты сел в машину времени и отправился "
            "на 4,5 миллиарда лет назад. Ты не увидишь ни деревьев, ни животных, ни людей. Не будет даже "
            "океанов! Вокруг — огромное облако из газа, пыли и раскалённых камней, которое медленно "
            "кружится вокруг молодого Солнца. Именно из этого облака однажды появилась наша планета."
        )},

        {"type": "heading", "text": "☀️ Всё началось с рождения Солнца"},
        {"type": "paragraph", "text": (
            "Около 4,6 миллиарда лет назад огромное облако газа и космической пыли начало сжиматься под "
            "действием собственной силы притяжения. Чем сильнее оно сжималось, тем горячее становилось. "
            "В самом центре температура стала настолько высокой, что вспыхнуло новое Солнце. Но вокруг "
            "него осталось огромное количество пыли и камней. Именно они стали строительным материалом "
            "для планет."
        )},
        {"type": "callout", "text": "🌟 Интересный факт: почти всё вещество, из которого состоишь ты, когда-то находилось внутри древних звёзд!"},

        {"type": "heading", "text": "🪨 Космический конструктор"},
        {"type": "paragraph", "text": (
            "Представь огромную строительную площадку. Миллиарды камней летали вокруг Солнца. Они "
            "постоянно сталкивались. Иногда разбивались. Но чаще — слипались! Сначала появились "
            "маленькие камушки. Потом — валуны. Затем — огромные космические глыбы размером с горы. "
            "Прошли миллионы лет. Так постепенно выросла будущая Земля."
        )},
        {"type": "callout", "text": "💡 Представь себе: если взять снежок и катить его по снегу, он становится всё больше. Так же росла и Земля. Только вместо снега она собирала космические камни."},

        {"type": "heading", "text": "🔥 Земля была огненным шаром"},
        {"type": "paragraph", "text": (
            "Когда планета стала большой, столкновения продолжались. Каждый удар выделял огромное "
            "количество тепла. Кроме этого, внутри Земли распадались радиоактивные элементы. В результате "
            "молодая Земля была похожа на гигантский раскалённый шар лавы. Температура достигала "
            "нескольких тысяч градусов. На поверхности не существовало ничего живого."
        )},

        {"type": "heading", "text": "⚙️ Почему внутри Земли железо?"},
        {"type": "paragraph", "text": (
            "Когда Земля была жидкой, вещества начали разделяться. Тяжёлые материалы медленно опускались "
            "вниз. Лёгкие оставались сверху. Так появились слои Земли."
        )},
        {"type": "list", "items": [
            "🟡 В центре оказалось железное ядро.",
            "🟠 Вокруг него — раскалённая мантия.",
            "🟤 Снаружи образовалась твёрдая земная кора.",
        ]},
        {"type": "paragraph", "text": "Именно на ней сегодня стоят города, леса и горы."},

        {"type": "heading", "text": "🌋 Земля постепенно остывала"},
        {"type": "paragraph", "text": (
            "Прошли миллионы лет. Поверхность начала охлаждаться. Появилась первая твёрдая кора. Но "
            "вулканов было очень много. Они постоянно выбрасывали:"
        )},
        {"type": "list", "items": ["горячий пар", "углекислый газ", "азот", "другие газы"]},
        {"type": "paragraph", "text": "Так постепенно появилась первая атмосфера. Но дышать ей человек не смог бы. Кислорода почти не было."},

        {"type": "heading", "text": "🌧️ Откуда взялись океаны?"},
        {"type": "paragraph", "text": (
            "Из вулканов в воздух попадало огромное количество водяного пара. Когда Земля остыла "
            "достаточно сильно, пар начал превращаться в дождь. Но это был необычный дождь. Он шёл "
            "тысячи и даже миллионы лет! Вода заполняла огромные впадины. Так появились первые океаны."
        )},
        {"type": "callout", "text": "🌊 Интересный факт: некоторая часть воды могла прилететь на Землю вместе с ледяными кометами и астероидами. Учёные до сих пор исследуют, сколько воды пришло из космоса."},

        {"type": "heading", "text": "🌍 Когда появилась жизнь?"},
        {"type": "paragraph", "text": (
            "Когда Земля остыла и появились океаны, прошло ещё очень много времени. Первые живые "
            "организмы были совсем маленькими. Это были микроскопические бактерии. Они появились "
            "примерно 3,8–4 миллиарда лет назад. Потом возникли водоросли. Затем — рыбы. Позже — "
            "динозавры. После них — млекопитающие. И только совсем недавно по космическим меркам "
            "появились люди."
        )},
        {"type": "callout", "text": "⏳ Если представить всю историю Земли как 24 часа, то люди появились всего за последние несколько секунд перед полуночью."},

        {"type": "heading", "text": "🔍 Почему Земля особенная?"},
        {"type": "paragraph", "text": "Пока учёные не нашли другую планету, на которой точно есть жизнь. Земля оказалась удивительно удачной. У неё есть:"},
        {"type": "list", "items": [
            "🌞 подходящее расстояние до Солнца",
            "💧 жидкая вода",
            "🌍 атмосфера",
            "🧲 магнитное поле, защищающее от опасного космического излучения",
            "🌙 большая Луна, которая помогает стабилизировать наклон Земли и влияет на приливы и отливы",
        ]},
        {"type": "paragraph", "text": "Все эти условия сделали жизнь возможной."},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Земля появилась около 4,54 миллиарда лет назад.",
            "Она образовалась из космической пыли и камней, вращавшихся вокруг молодого Солнца.",
            "Сначала Земля была раскалённым шаром.",
            "Затем она постепенно остыла.",
            "Появились атмосфера и океаны.",
            "Позже возникла жизнь.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🌍 Если бы история Земли длилась один календарный год, то динозавры исчезли бы только 26 декабря, а первые люди появились бы вечером 31 декабря.",
            "☄️ Земля до сих пор каждый день становится немного тяжелее — на неё падают десятки тонн космической пыли.",
            "🌋 Внутри нашей планеты до сих пор очень горячо: температура ядра достигает примерно 5 000–6 000 °C, почти как на поверхности Солнца.",
            "💎 Некоторые кристаллы циркона возрастом более 4,3 миллиарда лет — это самые древние известные кусочки земной коры.",
        ]},

        {"type": "question", "text": (
            "Если бы ты оказался на Земле сразу после её образования, что бы ты увидел вокруг? Почему на "
            "такой планете не смог бы выжить ни один человек? Попробуй представить это и нарисовать "
            "молодую Землю такой, какой она была миллиарды лет назад."
        )},
    ],
}

ARTICLE_CONTINENTS = {
    "grade": 5,
    "summary": "Большое путешествие вокруг света: семь материков Земли, их природа и животные, суперконтинент Пангея и почему материки медленно движутся.",
    "blocks": [
        {"type": "heading", "text": "🌍 Материки Земли"},
        {"type": "paragraph", "text": (
            "🧭 Большое путешествие вокруг света. Представь, что ты поднялся высоко-высоко в космос и "
            "смотришь на нашу планету. Ты увидишь огромные синие океаны и большие участки суши. Эти "
            "огромные куски суши называются материками. Их всего 7, и каждый из них по-своему удивителен."
        )},

        {"type": "heading", "text": "🗺 Что такое материк?"},
        {"type": "paragraph", "text": "Материк — это очень большой участок суши, который со всех сторон или почти со всех сторон окружён водой. На материках находятся:"},
        {"type": "list", "items": ["🏙️ города", "🌳 леса", "🏔️ горы", "🏜️ пустыни", "🌊 реки и озёра", "👨‍👩‍👧‍👦 люди и животные"]},
        {"type": "paragraph", "text": "Материки настолько большие, что некоторые страны занимают лишь крошечную часть одного материка."},

        {"type": "heading", "text": "🌏 Какие материки есть на Земле?"},
        {"type": "list", "items": [
            "🌍 Евразия", "🌍 Африка", "🌍 Северная Америка", "🌍 Южная Америка",
            "🌍 Антарктида", "🌍 Австралия", "🌍 Зеландия (не всегда считается материком)",
        ]},

        {"type": "heading", "text": "🌍 1. Евразия"},
        {"type": "paragraph", "text": (
            "Самый большой материк на планете. Здесь находятся сразу две части света — Европа и Азия. "
            "Именно здесь живёт большая часть населения Земли. Здесь можно увидеть:"
        )},
        {"type": "list", "items": [
            "🏔️ самые высокие горы — Гималаи", "🌊 самое глубокое озеро — Байкал", "🏜️ огромные пустыни",
            "🌳 бескрайние леса", "🏙️ тысячи больших городов",
        ]},
        {"type": "callout", "text": "🌟 Интересный факт: на Евразии расположено более 90 государств!"},

        {"type": "heading", "text": "🌍 2. Африка"},
        {"type": "paragraph", "text": "Самый жаркий материк. Здесь почти круглый год светит яркое солнце. Именно в Африке появились первые люди. Здесь живут:"},
        {"type": "list", "items": ["🦁 львы", "🐘 слоны", "🦒 жирафы", "🦛 бегемоты", "🦓 зебры", "🐆 леопарды"]},
        {"type": "callout", "text": "🌟 Интересный факт: через Африку проходит экватор, поэтому здесь почти всегда тепло."},

        {"type": "heading", "text": "🌍 3. Северная Америка"},
        {"type": "paragraph", "text": "Здесь находятся огромные леса, горы, озёра и знаменитый Ниагарский водопад. На материке можно встретить:"},
        {"type": "list", "items": ["🦬 бизонов", "🐻 медведей", "🦅 белоголовых орланов", "🦫 бобров"]},
        {"type": "callout", "text": "🌟 Интересный факт: в Северной Америке расположено одно из крупнейших пресноводных озёр мира — Верхнее."},

        {"type": "heading", "text": "🌍 4. Южная Америка"},
        {"type": "paragraph", "text": "Самый зелёный материк. Именно здесь находится самый большой тропический лес Земли — Амазония. Здесь живут:"},
        {"type": "list", "items": ["🦜 попугаи", "🦥 ленивцы", "🐒 обезьяны", "🐍 анаконды", "🐆 ягуары", "🦙 ламы"]},
        {"type": "callout", "text": "🌟 Интересный факт: река Амазонка — одна из самых длинных и самых полноводных рек на Земле."},

        {"type": "heading", "text": "🌍 5. Антарктида"},
        {"type": "paragraph", "text": "Самый холодный материк. Здесь нет постоянных городов. Большая часть материка покрыта толстым слоем льда. Здесь можно встретить:"},
        {"type": "list", "items": ["🐧 пингвинов", "🦭 тюленей", "🐋 китов"]},
        {"type": "callout", "text": "🌟 Интересный факт: в некоторых местах толщина льда достигает 4 километров!"},

        {"type": "heading", "text": "🌍 6. Австралия"},
        {"type": "paragraph", "text": "Самый маленький материк. Он полностью расположен в Южном полушарии. Здесь живут удивительные животные, которых почти нигде больше нет. Например:"},
        {"type": "list", "items": ["🦘 кенгуру", "🐨 коалы", "🦆 утконосы", "🦘 вомбаты", "🦎 большие ящерицы"]},
        {"type": "callout", "text": "🌟 Интересный факт: Австралию иногда называют самым большим островом и самым маленьким материком одновременно."},

        {"type": "heading", "text": "🌍 7. (Некоторые учёные выделяют) Зеландию"},
        {"type": "paragraph", "text": (
            "Под водой рядом с Австралией находится почти полностью затопленная древняя суша — Зеландия. "
            "Большинство школьных учебников считают, что материков семь, и Зеландию обычно не включают в "
            "этот список. Но геологи продолжают её изучать."
        )},

        {"type": "heading", "text": "🌊 Почему материки не стоят на месте?"},
        {"type": "paragraph", "text": (
            "Кажется, что материки совершенно неподвижны. Но это не так. Они медленно «плывут» по "
            "огромным каменным плитам. Эти плиты движутся со скоростью примерно такой же, как растут "
            "наши ногти — всего несколько сантиметров в год. За миллионы лет материки могут сильно "
            "изменить своё положение."
        )},

        {"type": "heading", "text": "🧩 Когда-то материк был один"},
        {"type": "paragraph", "text": (
            "Очень давно все материки были соединены. Учёные называют этот древний суперконтинент "
            "Пангея. Представь огромный пазл из одного кусочка. Потом он начал раскалываться. Части "
            "медленно разошлись в разные стороны. Так появились современные материки."
        )},
        {"type": "callout", "text": "💡 Представь: если взять большое печенье и аккуратно разломить его на кусочки, а затем медленно раздвигать их по столу, получится что-то похожее на историю материков."},

        {"type": "heading", "text": "🐾 Почему на разных материках разные животные?"},
        {"type": "paragraph", "text": "Когда материки разделились, животные больше не могли свободно переходить с одного материка на другой. Поэтому они постепенно стали развиваться по-разному. Вот почему:"},
        {"type": "list", "items": [
            "🦘 кенгуру живут в Австралии", "🐧 большинство пингвинов — возле Антарктиды",
            "🦒 жирафы — в Африке", "🦬 бизоны — в Северной Америке",
        ]},

        {"type": "heading", "text": "🌎 Материки и океаны"},
        {"type": "paragraph", "text": "Материки окружены пятью океанами:"},
        {"type": "list", "items": ["🌊 Тихий", "🌊 Атлантический", "🌊 Индийский", "🌊 Северный Ледовитый", "🌊 Южный"]},
        {"type": "paragraph", "text": "Вместе океаны занимают около 71% поверхности Земли, а суша — только 29%. Это значит, что наша планета больше похожа на огромный водный мир."},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "На Земле 7 материков.",
            "Самый большой — Евразия.",
            "Самый маленький — Австралия.",
            "Самый холодный — Антарктида.",
            "Самый жаркий — Африка.",
            "Когда-то все материки были соединены в один огромный суперконтинент — Пангею.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🌍 Если сложить современные материки как детали пазла, многие их берега удивительно хорошо совпадут.",
            "🦘 В Австралии кенгуру живёт больше, чем людей.",
            "🧊 В Антарктиде находится около 70% всей пресной воды Земли, но почти вся она замёрзла в виде льда.",
            "🌳 Леса Амазонии в Южной Америке производят огромное количество кислорода и помогают поддерживать климат всей планеты.",
            "🏔️ Самая высокая гора мира — Эверест — находится в Евразии и поднимается почти на 8 850 метров над уровнем моря.",
        ]},

        {"type": "question", "text": (
            "Если бы ты мог отправиться в путешествие на любой материк, какой бы ты выбрал? Хотел бы ты "
            "увидеть льды Антарктиды, пустыни Африки, джунгли Южной Америки или встретить кенгуру в "
            "Австралии? Почему именно этот материк кажется тебе самым интересным?"
        )},
    ],
}

ARTICLE_UNIVERSE = {
    "grade": 5,
    "summary": "Самое большое путешествие: звёзды, планеты, галактики и наш космический адрес во Вселенной.",
    "blocks": [
        {"type": "heading", "text": "🌌 Что такое Вселенная?"},
        {"type": "paragraph", "text": (
            "🚀 Представь самое большое путешествие. Закрой глаза и представь. Ты стоишь на Земле. "
            "Поднимаешься на самолёте. Потом — ещё выше, на ракете. Ты пролетаешь облака, Луну, планеты, "
            "Солнце… Но путешествие только начинается! Впереди миллиарды звёзд, огромные галактики и "
            "необъятные просторы космоса. Всё это вместе называется Вселенной."
        )},

        {"type": "heading", "text": "🌌 Что такое Вселенная?"},
        {"type": "paragraph", "text": "Вселенная — это абсолютно всё, что существует. В неё входят:"},
        {"type": "list", "items": [
            "⭐ все звёзды", "🪐 все планеты", "🌙 все спутники", "☄️ кометы", "🪨 астероиды",
            "🌌 галактики", "🌫️ облака газа и пыли", "⚫ чёрные дыры", "✨ даже пространство между ними",
        ]},
        {"type": "paragraph", "text": "И конечно же… 🌍 наша Земля тоже является частью Вселенной."},

        {"type": "heading", "text": "🤔 Насколько она большая?"},
        {"type": "paragraph", "text": (
            "Ответ очень простой… Мы пока не знаем. Учёные считают, что Вселенная настолько огромна, что "
            "её размеры трудно даже представить. Даже свет — самое быстрое, что существует в природе, — "
            "не успел пересечь всю наблюдаемую Вселенную с момента её рождения."
        )},
        {"type": "callout", "text": "💡 Представь: песчинку на огромном пляже. Теперь представь, что эта песчинка — Земля. А весь пляж — Вселенная. И даже такое сравнение делает Вселенную слишком маленькой!"},

        {"type": "heading", "text": "⭐ Из чего состоит Вселенная?"},
        {"type": "paragraph", "text": "Во Вселенной находится огромное количество самых разных объектов."},
        {"type": "subheading", "text": "🌟 Звёзды"},
        {"type": "paragraph", "text": "Это гигантские раскалённые шары газа. Они сами излучают свет и тепло. Наше Солнце — тоже звезда."},
        {"type": "subheading", "text": "🪐 Планеты"},
        {"type": "paragraph", "text": "Планеты не светятся сами. Они вращаются вокруг звёзд. Например:"},
        {"type": "list", "items": ["🌍 Земля", "🪐 Сатурн", "🔴 Марс", "🟠 Юпитер"]},
        {"type": "subheading", "text": "🌙 Спутники"},
        {"type": "paragraph", "text": "Это небесные тела, которые вращаются вокруг планет. У Земли есть один естественный спутник — Луна. У Юпитера и Сатурна их десятки."},
        {"type": "subheading", "text": "🌌 Галактики"},
        {"type": "paragraph", "text": "Звёзды не разбросаны по космосу случайно. Они собираются в огромные семьи. Такие семьи называются галактиками. В каждой галактике могут находиться миллиарды или даже триллионы звёзд."},

        {"type": "heading", "text": "🌌 Где находится Земля?"},
        {"type": "paragraph", "text": "Наша планета находится в галактике Млечный Путь. Она похожа на огромную спираль. В ней находится более 100 миллиардов звёзд. Солнце — всего лишь одна из них."},

        {"type": "heading", "text": "📍 Наш адрес во Вселенной"},
        {"type": "paragraph", "text": "Представь, что нужно написать космический адрес:"},
        {"type": "flow", "text": "🏠 Земля → 🪐 Солнечная система → 🌌 Галактика Млечный Путь → 🌠 Вселенная"},

        {"type": "heading", "text": "🌞 Что такое Солнечная система?"},
        {"type": "paragraph", "text": "Солнце находится в центре. Вокруг него вращаются восемь планет. Земля — третья по счёту. Кроме планет здесь есть:"},
        {"type": "list", "items": ["☄️ кометы", "🪨 астероиды", "🌑 карликовые планеты", "🌙 спутники"]},
        {"type": "paragraph", "text": "Но Солнечная система — лишь маленький уголок огромной Вселенной."},

        {"type": "heading", "text": "🚀 Можно ли долететь до конца Вселенной?"},
        {"type": "paragraph", "text": (
            "Пока никто не знает. Даже самые быстрые космические аппараты летели бы миллионы лет до "
            "ближайших звёзд. А до других галактик — ещё гораздо дольше. Учёные продолжают исследовать "
            "космос с помощью мощных телескопов и космических станций."
        )},

        {"type": "heading", "text": "🔭 Как изучают Вселенную?"},
        {"type": "paragraph", "text": "Люди используют специальные приборы."},
        {"type": "list", "items": [
            "🔭 Телескопы позволяют увидеть далёкие звёзды и галактики.",
            "🛰️ Космические спутники наблюдают за космосом без помех земной атмосферы.",
            "🚀 Автоматические станции исследуют планеты и астероиды.",
        ]},
        {"type": "paragraph", "text": "Иногда они присылают на Землю удивительные фотографии."},

        {"type": "heading", "text": "👽 Есть ли жизнь где-то ещё?"},
        {"type": "paragraph", "text": (
            "Это один из самых интересных вопросов науки. Пока учёные не нашли убедительных доказательств "
            "существования жизни за пределами Земли. Но во Вселенной существуют миллиарды планет. Поэтому "
            "многие учёные считают, что где-то жизнь может существовать. Исследования продолжаются."
        )},

        {"type": "heading", "text": "🌠 Вселенная постоянно меняется"},
        {"type": "paragraph", "text": "Может показаться, что космос неподвижен. На самом деле всё движется."},
        {"type": "list", "items": [
            "⭐ звёзды вращаются вокруг центра галактик", "🪐 планеты движутся вокруг звёзд",
            "🌙 спутники вращаются вокруг планет", "🌌 сами галактики тоже движутся",
        ]},
        {"type": "paragraph", "text": "Вселенная похожа на огромный космический танец, который продолжается уже миллиарды лет."},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Вселенная — это всё, что существует.",
            "Земля — лишь маленькая часть Вселенной.",
            "Солнце — это звезда.",
            "Земля находится в Солнечной системе.",
            "Солнечная система входит в галактику Млечный Путь.",
            "Во Вселенной существуют миллиарды галактик.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🌌 Свет от некоторых галактик летит к нам более 13 миллиардов лет.",
            "⭐ Во Вселенной звёзд гораздо больше, чем песчинок на всех пляжах Земли.",
            "🪐 На некоторых планетах год длится всего несколько земных дней, а на других — десятки земных лет.",
            "🌠 Если смотреть на ночное небо, многие звёзды, которые ты видишь, находятся так далеко, что их свет начал своё путешествие ещё до рождения твоих прапрапрадедушек.",
            "🚀 Международная космическая станция облетает Землю примерно 16 раз за сутки.",
        ]},

        {"type": "question", "text": (
            "Если бы ты оказался на космическом корабле и смог покинуть нашу галактику, что бы ты хотел "
            "увидеть первым: огромную туманность, другую галактику, необычную планету или новую звезду? "
            "Как ты думаешь, какие удивительные открытия ещё ждут человечество во Вселенной?"
        )},
    ],
}

ARTICLE_BIRDS_FLY = {
    "grade": 5,
    "summary": "Крылья, перья, лёгкие кости и сильные мышцы — из чего складывается способность птиц летать, и почему не все они это умеют.",
    "blocks": [
        {"type": "heading", "text": "🐦 Почему птицы летают?"},
        {"type": "paragraph", "text": (
            "✈️ Представь себя птицей. Закрой глаза и представь. Ты стоишь на высокой ветке дерева. "
            "Ветер слегка шевелит перья. Ты расправляешь крылья… Несколько сильных взмахов… И вдруг "
            "земля остаётся далеко внизу! Как же птицам удаётся делать то, о чём человек мечтал тысячи "
            "лет? Давай разберёмся."
        )},

        {"type": "heading", "text": "🪶 Что помогает птицам летать?"},
        {"type": "paragraph", "text": "Птицы умеют летать не благодаря какой-то одной особенности. Им помогает сразу несколько «секретов природы». Самые главные из них:"},
        {"type": "list", "items": ["🪽 крылья", "🪶 перья", "💪 сильные мышцы", "🦴 лёгкие кости", "❤️ мощное сердце", "🌬️ особая форма тела"]},
        {"type": "paragraph", "text": "Все эти части работают вместе, словно детали одного удивительного механизма."},

        {"type": "heading", "text": "🪽 Крылья — главный помощник"},
        {"type": "paragraph", "text": "Крылья — это передние конечности птицы, которые со временем изменились. Когда птица машет крыльями:"},
        {"type": "list", "items": ["⬇️ вниз она отталкивает воздух", "⬆️ воздух помогает удерживать её в небе"]},
        {"type": "paragraph", "text": "Чем сильнее птица машет крыльями, тем легче ей подняться."},
        {"type": "callout", "text": "💡 Представь: высуни ладонь в окно медленно едущей машины (только вместе со взрослым!). Если немного наклонить ладонь, воздух начнёт её поднимать. С крыльями птицы происходит похожее."},

        {"type": "heading", "text": "🪶 Почему перья такие важные?"},
        {"type": "paragraph", "text": "Без перьев птица не смогла бы летать. Перья:"},
        {"type": "list", "items": ["✅ делают крыло шире", "✅ помогают ловить воздух", "✅ уменьшают сопротивление", "✅ сохраняют тепло", "✅ защищают тело"]},
        {"type": "paragraph", "text": "Большие перья на концах крыльев работают почти как лопасти самолёта."},

        {"type": "heading", "text": "🦴 Лёгкие кости"},
        {"type": "paragraph", "text": (
            "Если бы птица весила слишком много, подняться в воздух было бы очень трудно. Поэтому многие "
            "её кости внутри полые. Это значит, что внутри есть маленькие воздушные полости. Такие кости "
            "очень лёгкие, но при этом достаточно прочные."
        )},
        {"type": "callout", "text": "🔍 Интересный факт: скелет голубя весит меньше, чем многие думают. Благодаря лёгким костям птице проще взлетать и дольше оставаться в воздухе."},

        {"type": "heading", "text": "💪 Очень сильные мышцы"},
        {"type": "paragraph", "text": (
            "У птиц особенно хорошо развиты грудные мышцы. Именно они двигают крылья. У некоторых "
            "летающих птиц грудные мышцы составляют почти четверть массы всего тела! Представь, если бы "
            "у человека мышцы рук были такими же сильными."
        )},

        {"type": "heading", "text": "❤️ Сердце работает очень быстро"},
        {"type": "paragraph", "text": (
            "Во время полёта организму нужно много энергии. Поэтому сердце птицы бьётся очень быстро. "
            "Например: у маленькой птицы оно может делать более 500 ударов в минуту. Кровь быстро "
            "приносит кислород к мышцам, чтобы они не уставали."
        )},

        {"type": "heading", "text": "🌬️ Особое дыхание"},
        {"type": "paragraph", "text": (
            "Когда человек быстро бежит, ему становится трудно дышать. Птицы устроены иначе. Их "
            "дыхательная система очень эффективно снабжает организм кислородом. Это помогает долго "
            "летать без остановки."
        )},

        {"type": "heading", "text": "🛫 Почему самолёты похожи на птиц?"},
        {"type": "paragraph", "text": "Когда люди мечтали научиться летать, они внимательно наблюдали за птицами. Они заметили:"},
        {"type": "list", "items": ["✈️ гладкую форму тела", "🪽 широкие крылья", "🌬️ как воздух обтекает крыло"]},
        {"type": "paragraph", "text": "Поэтому современные самолёты тоже имеют крылья особой формы. Хотя самолёт машет не крыльями, а летит благодаря двигателям, принципы взаимодействия с воздухом очень похожи."},

        {"type": "heading", "text": "🦅 Все ли птицы умеют летать?"},
        {"type": "paragraph", "text": "Нет. Некоторые птицы почти совсем потеряли способность летать. Например:"},
        {"type": "list", "items": ["🐧 пингвины отлично плавают", "🪶 страусы быстро бегают", "🥝 киви живут на земле", "🐦 эму тоже предпочитают бег"]},
        {"type": "paragraph", "text": "За миллионы лет этим птицам полёт стал не нужен."},

        {"type": "heading", "text": "🌍 Почему птицы вообще научились летать?"},
        {"type": "paragraph", "text": "Полёт даёт много преимуществ. Он помогает:"},
        {"type": "list", "items": ["🍓 быстрее находить еду", "🦊 спасаться от хищников", "🌳 строить гнёзда в безопасных местах", "🛫 улетать туда, где теплее зимой"]},
        {"type": "paragraph", "text": "Поэтому способность летать оказалась очень полезной."},

        {"type": "heading", "text": "🕊️ Самые удивительные лётчики"},
        {"type": "list", "items": [
            "🦅 Орлы могут парить в небе почти без взмахов крыльев.",
            "🐦 Колибри способны зависать на одном месте и даже летать назад.",
            "🦢 Лебеди совершают перелёты длиной в тысячи километров.",
            "🦅 Сапсан — самая быстрая птица в мире. Во время пикирования он может развивать скорость более 300 км/ч.",
        ]},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Птицы летают благодаря крыльям.", "Перья помогают удерживаться в воздухе.",
            "Лёгкие полые кости уменьшают вес.", "Сильные грудные мышцы двигают крылья.",
            "Быстрое сердце и особое дыхание дают много энергии.", "Не все птицы умеют летать.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🐦 Колибри машет крыльями до 80 раз в секунду.",
            "🪶 У крупных птиц на одном крыле может быть несколько тысяч перьев.",
            "🦅 Некоторые орлы поднимаются выше облаков — на высоту более 7 километров.",
            "🦢 Многие перелётные птицы ежегодно преодолевают тысячи километров и удивительно точно находят дорогу без карт и навигаторов.",
            "🌬️ Во время полёта птицы постоянно используют потоки воздуха, чтобы тратить меньше сил.",
        ]},

        {"type": "question", "text": (
            "Если бы у человека вдруг появились настоящие крылья, смог бы он сразу взлететь? Почему "
            "одних крыльев было бы недостаточно? Какие ещё изменения понадобились бы нашему телу, чтобы "
            "летать так же легко, как птицы?"
        )},
    ],
}

ARTICLE_PLANTS_GROW = {
    "grade": 5,
    "summary": "От маленького семечка до огромного дерева: как растения растут, едят солнечный свет и путешествуют семенами.",
    "blocks": [
        {"type": "heading", "text": "🌱 Как растут растения?"},
        {"type": "paragraph", "text": (
            "🌿 Представь настоящее чудо. Представь, что у тебя в ладони лежит маленькое семечко. Оно "
            "кажется совсем обычным. Но внутри него спрятано целое будущее растение! Из такого "
            "маленького семечка может вырасти огромный дуб высотой с десятиэтажный дом или высокий "
            "подсолнух, который будет выше человека. Как это возможно? Давай разберёмся."
        )},

        {"type": "heading", "text": "🌰 Всё начинается с семени"},
        {"type": "paragraph", "text": "Семя — это маленькая «капсула жизни». Внутри него находятся:"},
        {"type": "list", "items": ["🌱 крошечный зародыш будущего растения", "🥣 запас питательных веществ", "🛡️ прочная оболочка, которая защищает семя"]},
        {"type": "paragraph", "text": "Пока вокруг холодно или сухо, семя словно спит. Но стоит появиться подходящим условиям — оно просыпается."},

        {"type": "heading", "text": "💧 Что нужно семени?"},
        {"type": "paragraph", "text": "Чтобы начать расти, семени нужны четыре вещи:"},
        {"type": "list", "items": ["💧 Вода", "🌞 Тепло", "🌬️ Воздух", "🌱 Подходящая почва (для большинства растений)"]},
        {"type": "paragraph", "text": "Когда семя впитывает воду, оно увеличивается в размерах, оболочка размягчается, и начинается рост."},
        {"type": "callout", "text": "💡 Представь: это похоже на губку. Пока она сухая — маленькая и твёрдая. Но стоит опустить её в воду — она становится мягкой и увеличивается. Так же «просыпается» и семечко."},

        {"type": "heading", "text": "🌱 Кто появляется первым?"},
        {"type": "paragraph", "text": (
            "Первым из семени появляется... корешок! Почему не листья? Потому что растению сначала нужно "
            "крепко закрепиться в земле и начать добывать воду. Корень растёт вниз. Он словно якорь "
            "удерживает растение."
        )},

        {"type": "heading", "text": "🌿 Потом появляется росток"},
        {"type": "paragraph", "text": (
            "После корня вверх начинает расти зелёный росток. Он пробивается через почву навстречу "
            "солнцу. Через несколько дней появляются первые листочки. Теперь растение может само "
            "производить себе пищу."
        )},

        {"type": "heading", "text": "☀️ Как растения «едят»?"},
        {"type": "paragraph", "text": "Растения не ходят в магазин и не готовят обед. Они сами создают себе пищу! Для этого им нужны:"},
        {"type": "list", "items": ["☀️ солнечный свет", "💧 вода", "🌬️ углекислый газ из воздуха"]},
        {"type": "paragraph", "text": "В листьях происходит удивительный процесс — фотосинтез. Во время фотосинтеза растение создаёт сахар — свою пищу — и выделяет кислород, которым дышат люди и животные."},

        {"type": "heading", "text": "🍃 Почему листья зелёные?"},
        {"type": "paragraph", "text": (
            "В листьях находится особое вещество — хлорофилл. Именно он придаёт растениям зелёный цвет. "
            "Хлорофилл помогает ловить солнечный свет и превращать его энергию в питание для растения. "
            "Без него растения не смогли бы расти."
        )},

        {"type": "heading", "text": "💧 Как вода поднимается вверх?"},
        {"type": "paragraph", "text": (
            "Корни впитывают воду из почвы. Затем она путешествует по тонким трубочкам внутри стебля. "
            "Так вода попадает к каждому листочку. Даже в самое высокое дерево вода поднимается почти "
            "до самой вершины!"
        )},
        {"type": "callout", "text": "🌳 Интересный факт: высота некоторых деревьев превышает 100 метров — это примерно как дом в 30 этажей. И вода всё равно поднимается к самым верхним листьям."},

        {"type": "heading", "text": "🌸 Когда появляются цветы?"},
        {"type": "paragraph", "text": "Когда растение становится достаточно взрослым, оно начинает цвести. Цветы нужны не только для красоты. Они помогают растениям образовывать семена. Многие цветы привлекают:"},
        {"type": "list", "items": ["🐝 пчёл", "🦋 бабочек", "🐞 других насекомых"]},
        {"type": "paragraph", "text": "Они переносят пыльцу с одного цветка на другой. Так растения могут размножаться."},

        {"type": "heading", "text": "🍎 Откуда берутся плоды?"},
        {"type": "paragraph", "text": (
            "После опыления цветок постепенно меняется. На его месте начинает расти плод. Внутри плода "
            "созревают новые семена. Когда плод становится спелым, семена готовы отправиться в новое "
            "путешествие."
        )},

        {"type": "heading", "text": "🌬️ Как семена путешествуют?"},
        {"type": "paragraph", "text": "Растения придумали много способов расселяться."},
        {"type": "list", "items": [
            "🌬️ Ветер переносит лёгкие семена одуванчика.",
            "🐦 Птицы съедают ягоды, а затем разносят семена далеко от материнского растения.",
            "🐿️ Белки прячут жёлуди и иногда забывают о них.",
            "🌊 Некоторые семена путешествуют по воде.",
            "👕 Другие цепляются за шерсть животных или одежду людей.",
        ]},
        {"type": "paragraph", "text": "Так растения появляются в новых местах."},

        {"type": "heading", "text": "🌳 Почему деревья растут так долго?"},
        {"type": "paragraph", "text": (
            "Трава может вырасти за несколько недель. А деревья растут десятки и даже сотни лет. Каждый "
            "год ствол становится немного толще. Если спилить старое дерево, можно увидеть годичные "
            "кольца. По ним учёные определяют возраст дерева."
        )},

        {"type": "heading", "text": "🌎 Почему растения так важны?"},
        {"type": "paragraph", "text": "Без растений жизнь на Земле была бы невозможна. Они:"},
        {"type": "list", "items": ["🌬️ выделяют кислород", "🍎 дают нам пищу", "🏡 становятся домом для животных", "🌳 охлаждают воздух в жаркие дни", "🌧️ помогают сохранять воду в почве", "🌍 делают нашу планету зелёной и красивой"]},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Растение начинается с маленького семени.",
            "Сначала появляется корень, затем росток и листья.",
            "Для роста нужны вода, воздух, тепло и солнечный свет.",
            "В листьях происходит фотосинтез — растение создаёт себе пищу.",
            "Цветы превращаются в плоды с новыми семенами.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🌻 Подсолнухи в молодом возрасте поворачиваются вслед за Солнцем.",
            "🌳 Самым высоким деревьям на Земле больше 100 метров в высоту.",
            "🌱 Некоторые семена могут «спать» десятки лет, а затем прорасти, когда условия станут подходящими.",
            "🌵 Кактусы научились запасать воду, поэтому могут долго жить в пустыне без дождя.",
            "🍀 Одно большое дерево за день может испарить в воздух сотни литров воды через свои листья.",
        ]},

        {"type": "question", "text": (
            "Если посадить два одинаковых семечка, но одно поставить на солнечный подоконник и регулярно "
            "поливать, а другое оставить в тёмном шкафу без воды, что с ними произойдёт? Почему растениям "
            "так важно одновременно получать и свет, и воду?"
        )},
    ],
}

ARTICLE_CELL = {
    "grade": 5,
    "summary": "Клетка — самый маленький «живой город»: из чего она состоит, сколько их в человеке и как из одной клетки вырастает целый организм.",
    "blocks": [
        {"type": "heading", "text": "🔬 Что такое клетка?"},
        {"type": "paragraph", "text": "👀 Представь город, которого не видно. Представь огромный современный город. В нём есть:"},
        {"type": "list", "items": ["🏠 дома", "⚡ электростанции", "🚛 дороги", "🏭 фабрики", "🗑️ службы уборки", "📦 склады", "👷 рабочие"]},
        {"type": "paragraph", "text": "Теперь представь, что такой город очень-очень маленький. Настолько маленький, что его невозможно увидеть без микроскопа. Так устроена клетка — самый маленький «живой город», из которого построены все живые организмы."},

        {"type": "heading", "text": "🧬 Что такое клетка?"},
        {"type": "paragraph", "text": "Клетка — это самая маленькая живая часть любого организма. Из клеток состоят:"},
        {"type": "list", "items": ["👦 люди", "🐶 животные", "🌳 деревья", "🌼 цветы", "🍄 грибы", "🦠 многие микроскопические организмы"]},
        {"type": "paragraph", "text": "Клетки настолько малы, что большинство из них можно увидеть только под микроскопом."},
        {"type": "callout", "text": "💡 Представь: если увеличить одну клетку человека до размера футбольного поля, внутри неё можно было бы рассмотреть множество удивительных «машин» и «фабрик», которые непрерывно работают."},

        {"type": "heading", "text": "🔎 Насколько маленькая клетка?"},
        {"type": "paragraph", "text": "Клетка человека обычно имеет размер около 0,01–0,05 миллиметра. Это значит, что на кончике иголки могут поместиться сотни клеток. А в твоём организме их невероятно много."},

        {"type": "heading", "text": "🤯 Сколько клеток в человеке?"},
        {"type": "paragraph", "text": "Учёные подсчитали, что тело взрослого человека состоит примерно из 37 триллионов клеток. Это число настолько огромное, что его трудно представить. Если считать по одной клетке каждую секунду, на подсчёт ушёл бы не один миллион лет!"},

        {"type": "heading", "text": "🏠 Из чего состоит клетка?"},
        {"type": "paragraph", "text": "Хотя клетки бывают разными, многие из них имеют похожее строение."},
        {"type": "subheading", "text": "🛡️ Клеточная оболочка"},
        {"type": "paragraph", "text": "Это прочная внешняя граница клетки. Она защищает клетку и решает, что может попасть внутрь, а что — выйти наружу. Похоже на стены и двери дома."},
        {"type": "subheading", "text": "💧 Цитоплазма"},
        {"type": "paragraph", "text": "Внутри клетки находится густая жидкость. В ней расположены все маленькие «рабочие станции» клетки. Это похоже на улицы и помещения большого города."},
        {"type": "subheading", "text": "🧠 Ядро"},
        {"type": "paragraph", "text": "В центре многих клеток находится ядро. Это главный «командный центр». Именно здесь хранится инструкция по работе клетки — ДНК. Можно сказать, что ядро — это директор огромной фабрики."},

        {"type": "heading", "text": "🏭 Внутри клетки кипит работа"},
        {"type": "paragraph", "text": "Клетка никогда не отдыхает. Каждую секунду она:"},
        {"type": "list", "items": ["⚡ получает энергию", "🍎 перерабатывает питательные вещества", "🧱 строит новые части", "🗑️ убирает отходы", "🛡️ защищается", "📦 передаёт вещества другим клеткам"]},
        {"type": "paragraph", "text": "Даже когда ты спишь, миллиарды клеток продолжают работать."},

        {"type": "heading", "text": "🧩 Все клетки одинаковые?"},
        {"type": "paragraph", "text": "Нет! Хотя все клетки похожи, у каждой есть своя работа. Например:"},
        {"type": "list", "items": ["🧠 нервные клетки передают сигналы", "💪 мышечные клетки сокращаются", "🩸 клетки крови разносят кислород", "🦴 костные клетки делают кости прочными", "🧴 клетки кожи защищают тело"]},
        {"type": "paragraph", "text": "Каждая клетка похожа на специалиста в большой команде."},

        {"type": "heading", "text": "🌳 Клетки растений отличаются"},
        {"type": "paragraph", "text": "У растений клетки немного другие. Кроме оболочки и ядра, у них есть особые части:"},
        {"type": "list", "items": ["🍃 Хлоропласты помогают получать энергию солнечного света.", "💧 Большая вакуоль хранит воду.", "🧱 Прочная клеточная стенка делает растение крепким."]},
        {"type": "paragraph", "text": "Именно благодаря хлоропластам растения зелёные."},

        {"type": "heading", "text": "🌱 Как из одной клетки вырастает человек?"},
        {"type": "paragraph", "text": "Каждый человек начинает свою жизнь всего с одной клетки. Потом эта клетка делится:"},
        {"type": "list", "items": ["1️⃣ одна становится двумя", "2️⃣ две превращаются в четыре", "3️⃣ четыре — в восемь", "и так снова и снова"]},
        {"type": "paragraph", "text": "Через некоторое время появляются миллионы, затем миллиарды клеток. Так постепенно развивается весь организм."},

        {"type": "heading", "text": "🔧 Клетки умеют чинить организм"},
        {"type": "paragraph", "text": "Если ты поцарапал колено, клетки сразу начинают работать. Они:"},
        {"type": "list", "items": ["🩹 закрывают ранку", "🩸 останавливают кровь", "🧱 строят новую кожу"]},
        {"type": "paragraph", "text": "Благодаря клеткам наше тело умеет восстанавливаться."},

        {"type": "heading", "text": "🔬 Как люди узнали о клетках?"},
        {"type": "paragraph", "text": (
            "Долгое время никто даже не подозревал об их существовании. В XVII веке учёные изобрели "
            "первые микроскопы. Однажды английский учёный Роберт Гук посмотрел через микроскоп на тонкий "
            "кусочек пробки. Он увидел множество маленьких «комнаток». Они напомнили ему монашеские "
            "кельи, поэтому он назвал их клетками. Так появилось это слово."
        )},

        {"type": "heading", "text": "🌍 Почему клетки так важны?"},
        {"type": "paragraph", "text": "Без клеток не существовало бы жизни. Именно клетки:"},
        {"type": "list", "items": ["❤️ заставляют биться сердце", "🫁 помогают нам дышать", "🧠 позволяют думать", "🏃 помогают бегать", "👀 дают возможность видеть", "🌱 позволяют растениям расти", "🐶 делают живыми животных"]},
        {"type": "paragraph", "text": "Все живые организмы состоят из клеток."},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Клетка — самая маленькая живая часть организма.",
            "Все люди, животные и растения состоят из клеток.",
            "Внутри клетки находится ядро с ДНК — инструкцией для работы.",
            "Разные клетки выполняют разные задачи.",
            "Из одной клетки может вырасти целый организм.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🧬 В организме человека около 37 триллионов клеток.",
            "🩸 Каждую секунду в твоём теле рождаются миллионы новых клеток.",
            "🧠 Некоторые нервные клетки могут жить столько же, сколько и человек.",
            "🌳 Самые большие клетки растений иногда достигают нескольких сантиметров в длину.",
            "🦠 Самые маленькие бактерии состоят всего из одной клетки, но умеют самостоятельно жить, питаться и размножаться.",
        ]},

        {"type": "question", "text": (
            "Представь, что ты уменьшился до размеров клетки и оказался внутри собственного организма. "
            "Что бы ты увидел вокруг? На какую часть клетки тебе было бы интереснее всего посмотреть — "
            "на ядро, которое хранит ДНК, или на крошечные «фабрики», которые непрерывно производят всё "
            "необходимое для жизни?"
        )},
    ],
}

ARTICLE_HUMAN_BODY = {
    "grade": 5,
    "summary": "От клетки до целого организма: пять уровней устройства человека — клетки, ткани, органы, системы органов и весь организм.",
    "blocks": [
        {"type": "heading", "text": "👦 Из чего состоит человек?"},
        {"type": "paragraph", "text": (
            "🧩 Представь огромный конструктор. Ты наверняка собирал конструктор. Сначала есть отдельные "
            "маленькие детали. Из них собираются большие части. Потом получается целая машина, робот или "
            "замок. Человеческий организм устроен очень похоже. Только вместо пластиковых деталей у нас "
            "есть живые клетки. Именно из них постепенно строится всё наше тело."
        )},

        {"type": "heading", "text": "👶 Человек — это удивительная система"},
        {"type": "paragraph", "text": (
            "Когда мы смотрим на человека, кажется, что это одно целое. Но на самом деле внутри нас "
            "работают триллионы маленьких помощников. Все вместе они образуют сложную и удивительную "
            "систему, где каждая часть выполняет свою работу."
        )},

        {"type": "heading", "text": "🔬 Первый уровень — клетки"},
        {"type": "paragraph", "text": "Самые маленькие живые «кирпичики» организма называются клетками. Из клеток состоят:"},
        {"type": "list", "items": ["👀 глаза", "❤️ сердце", "🧠 мозг", "🦴 кости", "💪 мышцы", "🩸 кровь", "🌿 даже кожа"]},
        {"type": "paragraph", "text": "Клетки бывают разных видов, и каждая выполняет свою задачу."},
        {"type": "callout", "text": "💡 Представь: если бы клетки были размером с кирпич, человек оказался бы выше самой высокой горы на Земле!"},

        {"type": "heading", "text": "🧵 Второй уровень — ткани"},
        {"type": "paragraph", "text": "Когда много одинаковых клеток работают вместе, получается ткань. Это похоже на команду специалистов. Есть несколько основных видов тканей."},
        {"type": "subheading", "text": "💪 Мышечная ткань"},
        {"type": "paragraph", "text": "Позволяет двигаться, бегать, прыгать и улыбаться."},
        {"type": "subheading", "text": "🧠 Нервная ткань"},
        {"type": "paragraph", "text": "Передаёт сигналы по всему телу. Именно благодаря ей ты чувствуешь прикосновения, тепло и холод."},
        {"type": "subheading", "text": "🩸 Соединительная ткань"},
        {"type": "paragraph", "text": "Образует кости, хрящи, кровь и помогает соединять разные части организма."},
        {"type": "subheading", "text": "🧴 Покровная ткань"},
        {"type": "paragraph", "text": "Образует кожу и защищает организм от повреждений и микробов."},

        {"type": "heading", "text": "🏗️ Третий уровень — органы"},
        {"type": "paragraph", "text": "Из нескольких тканей строятся органы. Каждый орган выполняет важную работу. Например:"},
        {"type": "list", "items": ["❤️ сердце качает кровь", "🫁 лёгкие помогают дышать", "🧠 мозг управляет всем организмом", "🍎 желудок переваривает пищу", "🫘 почки очищают кровь", "👀 глаза позволяют видеть", "👂 уши помогают слышать"]},

        {"type": "heading", "text": "🤝 Четвёртый уровень — системы органов"},
        {"type": "paragraph", "text": "Органы тоже работают не поодиночке. Они объединяются в команды — системы органов."},
        {"type": "subheading", "text": "❤️ Кровеносная система"},
        {"type": "paragraph", "text": "Главный орган — сердце. Она переносит кровь, кислород и питательные вещества ко всем клеткам."},
        {"type": "subheading", "text": "🌬️ Дыхательная система"},
        {"type": "paragraph", "text": "Позволяет нам получать кислород. Главные органы — лёгкие."},
        {"type": "subheading", "text": "🍽️ Пищеварительная система"},
        {"type": "paragraph", "text": "Помогает превращать пищу в энергию. В неё входят:"},
        {"type": "list", "items": ["👄 рот", "🥣 желудок", "🌀 кишечник", "🫘 печень и другие органы"]},
        {"type": "subheading", "text": "🧠 Нервная система"},
        {"type": "paragraph", "text": "Состоит из мозга, спинного мозга и нервов. Она управляет всеми движениями, мыслями и чувствами."},
        {"type": "subheading", "text": "💪 Опорно-двигательная система"},
        {"type": "paragraph", "text": "Скелет и мышцы помогают стоять, ходить, бегать и прыгать."},

        {"type": "heading", "text": "🌍 Пятый уровень — целый организм"},
        {"type": "paragraph", "text": "Когда все системы работают вместе, получается человек. Это невероятно сложный механизм. Каждую секунду одновременно происходят тысячи процессов:"},
        {"type": "list", "items": ["❤️ Сердце качает кровь.", "🫁 Лёгкие получают кислород.", "🧠 Мозг думает.", "💪 Мышцы двигаются.", "👀 Глаза видят.", "👂 Уши слышат."]},
        {"type": "paragraph", "text": "И всё это происходит одновременно."},

        {"type": "heading", "text": "⚡ Как органы помогают друг другу?"},
        {"type": "paragraph", "text": "Представь футбольную команду. Если один игрок перестанет играть, всей команде станет труднее победить. Так же работают органы. Например:"},
        {"type": "flow", "text": "🍎 Желудок получает пищу → 🩸 Кровь переносит вещества → ❤️ Сердце разносит их по телу → 💪 Мышцы получают энергию → 🧠 Мозг управляет движениями"},
        {"type": "paragraph", "text": "Все органы постоянно помогают друг другу."},

        {"type": "heading", "text": "🌱 Организм постоянно обновляется"},
        {"type": "paragraph", "text": "Кажется, что тело всегда одинаковое. Но это не так. Каждый день:"},
        {"type": "list", "items": ["🩸 появляются новые клетки крови", "🧴 обновляется кожа", "💇 растут волосы", "💅 растут ногти", "🦴 восстанавливаются кости"]},
        {"type": "paragraph", "text": "Организм постоянно ремонтирует сам себя."},

        {"type": "heading", "text": "🌟 Почему человек такой сильный?"},
        {"type": "paragraph", "text": "Не потому, что у него самые большие мышцы. А потому, что миллиарды клеток умеют работать вместе. Каждая знает своё дело. Именно поэтому человек может:"},
        {"type": "list", "items": ["🎨 рисовать", "📚 читать", "🚴 кататься на велосипеде", "🏊 плавать", "🎵 играть на музыкальных инструментах", "🚀 строить космические корабли"]},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Человек состоит из клеток.", "Клетки образуют ткани.", "Ткани образуют органы.",
            "Органы объединяются в системы.", "Все системы вместе образуют организм.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🧬 В организме человека около 37 триллионов клеток.",
            "❤️ Сердце взрослого человека делает примерно 100 тысяч ударов каждый день.",
            "🩸 Общая длина всех кровеносных сосудов человека — около 100 тысяч километров. Этого хватило бы, чтобы почти 2,5 раза обогнуть Землю по экватору!",
            "🦴 У новорождённого около 270 костей, а у взрослого человека — 206. Некоторые кости срастаются по мере роста.",
            "🧠 Мозг человека содержит около 86 миллиардов нервных клеток, которые помогают нам думать, запоминать, мечтать и управлять движениями.",
        ]},

        {"type": "question", "text": (
            "Представь, что ты смог уменьшиться до размеров клетки и отправиться в путешествие по своему "
            "организму. Куда бы ты отправился сначала: в сердце, чтобы увидеть, как оно качает кровь, в "
            "лёгкие, где кислород попадает в организм, или в мозг, который управляет всем телом? Какие "
            "удивительные процессы ты смог бы увидеть своими глазами?"
        )},
    ],
}

ARTICLE_EYE = {
    "grade": 5,
    "summary": "Как устроен глаз — от зрачка и радужки до сетчатки, и почему на самом деле мы «видим» мозгом, а не глазами.",
    "blocks": [
        {"type": "heading", "text": "👁️ Как работает глаз?"},
        {"type": "paragraph", "text": (
            "🌈 Представь удивительную камеру. Ты наверняка фотографировал на телефон. Когда нажимаешь "
            "кнопку, камера ловит свет и превращает его в фотографию. Наш глаз работает похоже. Только "
            "он намного сложнее любой камеры. Каждую секунду глаза помогают нам видеть мир вокруг: "
            "людей, животных, книги, деревья, звёзды и даже самые маленькие детали."
        )},

        {"type": "heading", "text": "👀 Что такое глаз?"},
        {"type": "paragraph", "text": "Глаз — это орган зрения. Он помогает нам:"},
        {"type": "list", "items": ["🌈 различать цвета", "📏 видеть форму предметов", "📍 замечать, где находятся вещи", "🏃 следить за движением", "😊 узнавать лица людей"]},
        {"type": "paragraph", "text": "Но сам глаз не «понимает» то, что видит. Этим занимается мозг."},

        {"type": "heading", "text": "☀️ Всё начинается со света"},
        {"type": "paragraph", "text": "Чтобы что-то увидеть, нужен свет. Например:"},
        {"type": "list", "items": ["☀️ солнечный свет", "💡 свет лампы", "🔥 пламя свечи"]},
        {"type": "paragraph", "text": "Свет отражается от предметов и попадает в наши глаза. Если света нет совсем, увидеть ничего невозможно."},
        {"type": "callout", "text": "💡 Представь: ты оказался в совершенно тёмной комнате. Даже если рядом стоит стол, ты его не увидишь. Почему? Потому что без света глазам нечего «поймать»."},

        {"type": "heading", "text": "⚫ Зрачок — маленькая дверь"},
        {"type": "paragraph", "text": (
            "В центре глаза находится чёрный кружок — зрачок. На самом деле он не чёрный. Это отверстие, "
            "через которое внутрь попадает свет. Когда света мало, зрачок становится больше. Когда света "
            "очень много — сужается. Так глаз защищает себя от слишком яркого света."
        )},

        {"type": "heading", "text": "🎨 Радужка — цветная часть глаза"},
        {"type": "paragraph", "text": "Вокруг зрачка находится радужка. Она может быть:"},
        {"type": "list", "items": ["🟤 карей", "🔵 голубой", "🟢 зелёной", "🩶 серой"]},
        {"type": "paragraph", "text": "Именно радужка управляет размером зрачка, словно автоматически открывает и закрывает «дверцу» для света."},

        {"type": "heading", "text": "🔍 Хрусталик — природная линза"},
        {"type": "paragraph", "text": (
            "За зрачком находится прозрачный хрусталик. Он работает почти как линза фотоаппарата. Если "
            "предмет далеко, хрусталик становится более плоским. Если предмет близко — более выпуклым. "
            "Благодаря этому изображение остаётся чётким."
        )},

        {"type": "heading", "text": "🖼️ Сетчатка — экран внутри глаза"},
        {"type": "paragraph", "text": (
            "На задней стенке глаза находится сетчатка. Именно сюда попадает изображение. На сетчатке "
            "расположены миллионы особых клеток, чувствительных к свету. Они превращают свет в "
            "электрические сигналы. Можно представить, что сетчатка — это экран и датчик одновременно."
        )},

        {"type": "heading", "text": "🧠 Почему мы видим мозгом?"},
        {"type": "paragraph", "text": "После того как сетчатка получила изображение, начинается самое интересное. По зрительному нерву сигналы отправляются в мозг. Именно мозг:"},
        {"type": "list", "items": ["🧩 собирает изображение", "🎨 определяет цвета", "📏 понимает размеры", "😊 узнаёт лица", "📖 помогает читать"]},
        {"type": "paragraph", "text": "Получается, что глаза только собирают информацию, а настоящий «просмотр фильма» происходит в мозге."},

        {"type": "heading", "text": "🙃 Почему изображение сначала перевёрнуто?"},
        {"type": "paragraph", "text": (
            "Это удивительно, но хрусталик создаёт на сетчатке перевёрнутую картинку. Верх оказывается "
            "внизу, а низ — наверху. Но мозг настолько быстро обрабатывает информацию, что мы видим всё "
            "правильно и даже не замечаем этого."
        )},

        {"type": "heading", "text": "👀 Почему у нас два глаза?"},
        {"type": "paragraph", "text": "Два глаза нужны не только «для запаса». Они помогают:"},
        {"type": "list", "items": ["📐 точно определять расстояние", "⚽ ловить мяч", "🚲 кататься на велосипеде", "🏃 обходить препятствия", "🌍 видеть мир объёмным"]},
        {"type": "paragraph", "text": "Если закрыть один глаз и попробовать поймать небольшой предмет, сделать это станет сложнее."},

        {"type": "heading", "text": "👁️ Почему мы моргаем?"},
        {"type": "paragraph", "text": "Каждый человек моргает примерно 15–20 раз в минуту. Во время моргания происходит сразу несколько важных вещей:"},
        {"type": "list", "items": ["💧 глаз увлажняется слезой", "🧹 смываются пыль и грязь", "🛡️ поверхность глаза защищается от высыхания"]},
        {"type": "paragraph", "text": "Большинство людей даже не замечает, как часто моргает."},

        {"type": "heading", "text": "🌈 Как мы различаем цвета?"},
        {"type": "paragraph", "text": "На сетчатке есть особые клетки двух видов:"},
        {"type": "list", "items": ["🌙 Палочки помогают видеть в темноте.", "🌈 Колбочки помогают различать цвета."]},
        {"type": "paragraph", "text": "Именно благодаря колбочкам мы видим:"},
        {"type": "list", "items": ["🍎 красное яблоко", "🌿 зелёную траву", "🌊 синее море", "🌻 жёлтый подсолнух"]},

        {"type": "heading", "text": "🌙 Почему ночью видно хуже?"},
        {"type": "paragraph", "text": (
            "Когда становится темно, света попадает очень мало. Колбочки работают хуже. Зато начинают "
            "активнее работать палочки. Поэтому ночью мы хорошо замечаем движение и очертания предметов, "
            "но цвета становятся менее яркими."
        )},

        {"type": "heading", "text": "🛡️ Как защитить глаза?"},
        {"type": "paragraph", "text": "Чтобы глаза оставались здоровыми:"},
        {"type": "list", "items": ["📚 читай при хорошем освещении", "💻 делай перерывы при работе за компьютером или планшетом", "🥕 ешь продукты с витаминами, например морковь, тыкву, шпинат и рыбу", "😴 достаточно спи", "🕶️ защищай глаза от слишком яркого солнца"]},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Свет отражается от предметов и попадает в глаз.", "Зрачок регулирует количество света.",
            "Хрусталик фокусирует изображение.", "Сетчатка превращает свет в сигналы.",
            "Мозг получает сигналы и создаёт картину окружающего мира.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "👁️ Глаз человека способен различать миллионы оттенков цветов.",
            "⚡ Свет проходит путь от глаза до мозга всего за доли секунды.",
            "👶 Новорождённые дети сначала видят мир не так чётко, как взрослые. По мере роста зрение развивается.",
            "💧 Слёзы нужны не только тогда, когда мы плачем. Они постоянно увлажняют и защищают глаза.",
            "🦅 Некоторые птицы, например орлы, видят в несколько раз острее человека и могут заметить небольшую добычу с очень большой высоты.",
        ]},

        {"type": "question", "text": (
            "Представь, что люди могли бы видеть так же далеко, как орлы, или различать ещё больше "
            "цветов, чем сейчас. Каким стал бы мир? Какие новые детали природы, городов или звёздного "
            "неба мы смогли бы заметить?"
        )},
    ],
}

ARTICLE_SLEEP = {
    "grade": 5,
    "summary": "Пока ты спишь, организм не отдыхает, а работает: мозг наводит порядок в воспоминаниях, тело растёт, а иммунитет борется с микробами.",
    "blocks": [
        {"type": "heading", "text": "😴 Почему нужно спать?"},
        {"type": "paragraph", "text": "🌙 Представь удивительную мастерскую. Представь, что ночью твой организм превращается в огромную мастерскую. Пока ты спокойно спишь, внутри идёт большая работа:"},
        {"type": "list", "items": ["🧠 Мозг сортирует воспоминания.", "💪 Мышцы восстанавливаются после игр и спорта.", "❤️ Сердце продолжает качать кровь.", "🛡️ Иммунная система борется с микробами.", "🌱 Организм растёт."]},
        {"type": "paragraph", "text": "Кажется, что во сне ничего не происходит. На самом деле именно ночью тело становится особенно занятым."},

        {"type": "heading", "text": "💤 Что такое сон?"},
        {"type": "paragraph", "text": "Сон — это особое состояние, когда тело отдыхает, а мозг продолжает работать. Во время сна мы не перестаём жить. Мы продолжаем:"},
        {"type": "list", "items": ["❤️ дышать", "🫀 качать кровь", "🧠 думать", "🌡️ поддерживать температуру тела"]},
        {"type": "paragraph", "text": "Только всё происходит немного по-другому, чем днём."},

        {"type": "heading", "text": "🧠 Зачем спит мозг?"},
        {"type": "paragraph", "text": "За день мозг получает огромное количество информации. Например:"},
        {"type": "list", "items": ["📚 новые знания", "😊 эмоции", "👋 лица людей", "🎮 игры", "🎵 музыку", "🏃 движения"]},
        {"type": "paragraph", "text": "Ночью мозг словно наводит порядок. Он решает:"},
        {"type": "list", "items": ["📦 что запомнить надолго", "🗑️ что можно забыть", "🧩 какие знания связать между собой"]},
        {"type": "paragraph", "text": "Поэтому после хорошего сна учиться становится легче."},
        {"type": "callout", "text": "💡 Представь: школьный рюкзак. Если никогда не разбирать его, внутри быстро станет беспорядок. Сон похож на вечернюю уборку: всё раскладывается по своим местам."},

        {"type": "heading", "text": "🌱 Во сне мы растём"},
        {"type": "paragraph", "text": "Когда дети спят, организм выделяет особый гормон роста. Он помогает:"},
        {"type": "list", "items": ["🦴 костям становиться длиннее", "💪 мышцам крепнуть", "🧴 коже обновляться", "🦷 правильно развиваться всему организму"]},
        {"type": "paragraph", "text": "Поэтому детям особенно важно высыпаться."},

        {"type": "heading", "text": "💪 Мышцы тоже отдыхают"},
        {"type": "paragraph", "text": "После активного дня мышцы немного устают. Во сне организм:"},
        {"type": "list", "items": ["🔧 ремонтирует маленькие повреждения", "⚡ восполняет запасы энергии", "💪 делает мышцы сильнее"]},
        {"type": "paragraph", "text": "Именно поэтому после хорошего сна спортсмены чувствуют себя лучше."},

        {"type": "heading", "text": "🛡️ Сон помогает не болеть"},
        {"type": "paragraph", "text": "Во время сна иммунная система становится очень активной. Она:"},
        {"type": "list", "items": ["🦠 ищет микробов", "🛡️ уничтожает вирусы и бактерии", "🔧 помогает организму быстрее выздоравливать"]},
        {"type": "paragraph", "text": "Вот почему во время болезни врачи советуют больше отдыхать и спать."},

        {"type": "heading", "text": "❤️ Сердце тоже отдыхает"},
        {"type": "paragraph", "text": "Сердце работает всю жизнь без остановки. Во сне оно бьётся немного медленнее. Это помогает организму экономить силы и восстанавливаться."},

        {"type": "heading", "text": "🌙 Почему мы видим сны?"},
        {"type": "paragraph", "text": "Во время сна мозг продолжает работать. Иногда он создаёт удивительные истории — сны. Во сне можно:"},
        {"type": "list", "items": ["🚀 полететь в космос", "🦖 встретить динозавра", "🏰 попасть в волшебный замок", "🐬 плавать вместе с дельфинами"]},
        {"type": "paragraph", "text": "Учёные до сих пор изучают, зачем именно нам снятся сны, но считают, что они могут быть связаны с обработкой воспоминаний и эмоций."},

        {"type": "heading", "text": "😵 Что происходит, если мало спать?"},
        {"type": "paragraph", "text": "Если человек долго не высыпается, ему становится труднее:"},
        {"type": "list", "items": ["😴 сосредоточиться", "📚 запоминать новую информацию", "🏃 быстро бегать", "😊 сохранять хорошее настроение", "⚡ чувствовать себя бодрым"]},
        {"type": "paragraph", "text": "Поэтому сон так же важен, как правильное питание и движение."},

        {"type": "heading", "text": "⏰ Сколько нужно спать?"},
        {"type": "paragraph", "text": (
            "Детям около 10 лет обычно рекомендуется спать примерно 9–11 часов в сутки. Каждый человек "
            "немного отличается, но большинству школьников нужен именно такой отдых, чтобы хорошо расти, "
            "учиться и чувствовать себя бодро."
        )},

        {"type": "heading", "text": "🌟 Как сделать сон крепче?"},
        {"type": "paragraph", "text": "Вот несколько полезных привычек:"},
        {"type": "list", "items": ["📴 за час до сна меньше пользоваться телефоном и планшетом", "📖 почитать книгу или спокойно поговорить с родными", "🦷 почистить зубы", "🌬️ проветрить комнату", "🕗 ложиться спать примерно в одно и то же время"]},
        {"type": "paragraph", "text": "Организм любит режим и быстрее засыпает, когда привыкает к нему."},

        {"type": "heading", "text": "🌍 Сон нужен почти всем животным"},
        {"type": "paragraph", "text": "Не только люди спят."},
        {"type": "list", "items": ["🐱 Кошки могут спать до 16 часов в сутки.", "🦁 Львы отдыхают большую часть дня.", "🦒 Жирафы спят совсем немного — иногда всего несколько часов.", "🐬 Дельфины умеют спать необычным способом: по очереди отдыхает только одна половина мозга, а другая следит за окружающей обстановкой и помогает дышать."]},
        {"type": "paragraph", "text": "Каждое животное приспособилось к своему образу жизни."},

        {"type": "heading", "text": "🧠 Запомни самое главное"},
        {"type": "checklist", "items": [
            "Во сне организм восстанавливается.", "Мозг сортирует и запоминает новую информацию.",
            "Во время сна дети растут.", "Сон помогает иммунной системе бороться с болезнями.",
            "Хороший сон делает нас внимательнее, сильнее и бодрее.",
        ]},

        {"type": "heading", "text": "🤯 Удивительные факты"},
        {"type": "list", "items": [
            "🌙 За треть своей жизни человек проводит во сне.",
            "🧠 Даже во сне мозг продолжает активно работать.",
            "💤 Во время сна организм вырабатывает гормоны, которые помогают детям расти.",
            "😴 Большинство людей видит несколько снов за одну ночь, хотя утром помнит не все.",
            "🐨 Коалы — одни из самых сонливых животных. Они могут спать до 20 часов в сутки!",
        ]},

        {"type": "question", "text": (
            "Представь, что люди вообще перестали бы спать. Смогли бы они хорошо учиться, играть, "
            "заниматься спортом и быстро выздоравливать? Какие важные процессы перестали бы происходить "
            "в организме, если бы у него совсем не было времени на отдых?"
        )},
    ],
}

LESSON_NATURAL_DIGITS = {
    "topic": "Цифры и натуральные числа",
    "context_theme": "detective",
    "explanation": (
        "Натуральные числа — это числа, которыми считают предметы: 1, 2, 3, 4 и так далее без конца. "
        "К любому натуральному числу всегда можно прибавить единицу и получить следующее — поэтому "
        "самого большого натурального числа не существует. Отдельно от них стоит число 0 — оно обозначает "
        "отсутствие предметов, «пусто». Цифры — это десять знаков (0,1,2,3,4,5,6,7,8,9), из которых "
        "составляются все числа: цифр всего десять, а чисел из них можно построить бесконечно много. "
        "Многозначные числа читаются по классам — единицы, тысячи, миллионы, — каждый класс состоит из "
        "трёх разрядов: сотни, десятки, единицы."
    ),
    "explanation_game": (
        "Ночью в Музей математики пробрался загадочный вор и украл цифры со всех экспонатов. Чтобы найти "
        "его, тебе нужно стать детективом чисел и разобраться, как устроены числа на самом деле. Первая улика: "
        "цифра и число — это не одно и то же. Цифр всего десять — они как десять букв в особом алфавите, а "
        "чисел из них можно составить бесконечно много, как слов из букв. Вторая улика: место цифры в записи "
        "числа решает всё — в числе 5824 цифра 5 стоит в разряде тысяч и означает 5 тысяч, а если её "
        "переставить в конец, получится совсем другое число. Третья улика: у чисел нет потолка — к любому, "
        "даже самому огромному числу всегда можно прибавить единицу, поэтому вору никогда не удастся украсть "
        "«последнее» число — его просто не существует. И главная тайна дела — число 0: это не «ничего не "
        "значащая» цифра, а важный знак, обозначающий пустоту, отсутствие предметов."
    ),
    "questions": [
        {
            "text": "Детектив нашёл на месте преступления цифру и число. Сколько всего цифр существует?",
            "options": ["9", "10", "100", "Бесконечно много"],
            "correct": 1,
            "hint": "Вспомни: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 — посчитай их.",
            "explanation": "Цифр ровно 10 (от 0 до 9). А вот чисел, которые из них можно составить, — бесконечно много."
        },
        {
            "text": "Сколько цифр использовано в записи числа 5824?",
            "options": ["3", "4", "5", "8"],
            "correct": 1,
            "hint": "Посчитай все знаки подряд: 5, 8, 2, 4.",
            "explanation": "В числе 5824 четыре цифры: 5, 8, 2 и 4 — они стоят в разрядах тысяч, сотен, десятков и единиц."
        },
        {
            "text": "Какое число идёт сразу после 999 999?",
            "options": ["9 999 991", "1 000 000", "999 991", "100 000"],
            "correct": 1,
            "hint": "Когда все девятки заканчиваются, появляется новый, более старший разряд.",
            "explanation": "После 999 999 идёт 1 000 000 — миллион. Это как одометр, где все девятки одновременно превращаются в нули, а спереди добавляется единица."
        },
        {
            "text": "Что означает число 0 в математике?",
            "options": ["Самое маленькое натуральное число", "Отсутствие предметов, «пусто»", "Ошибку в счёте", "Бесконечность"],
            "correct": 1,
            "hint": "Представь пустую коробку — сколько в ней предметов?",
            "explanation": "Ноль обозначает отсутствие предметов, «пусто». Это не ошибка и не пустое место — это полноценное число со своим смыслом."
        },
        {
            "text": "В числе 3 452 810 какая цифра стоит в самом старшем классе — классе миллионов?",
            "options": ["3", "4", "5", "8"],
            "correct": 0,
            "hint": "Раздели число на классы по три цифры справа налево: 3 | 452 | 810.",
            "explanation": "3 452 810 делится на классы так: 3 — класс миллионов, 452 — класс тысяч, 810 — класс единиц. В классе миллионов стоит цифра 3."
        }
    ],
    "boss_task": {
        "answer": "987650",
        "text": (
            "Вор оставил зашифрованное послание с кодом от сейфа: «Мой код — самое большое шестизначное число, "
            "в котором все цифры разные и оно заканчивается на 0». Реши, какой код у сейфа."
        ),
        "solution": (
            "Ответ: 987650. Раз число должно заканчиваться на 0, эта цифра уже занимает последнее место. "
            "Чтобы число получилось максимально большим, на оставшиеся пять мест ставим самые большие из "
            "неповторяющихся цифр по убыванию: 9, 8, 7, 6, 5. Получаем 987650."
        ),
        "hint1": "Чтобы число было как можно больше, самые большие цифры нужно ставить в начале, слева направо.",
        "hint2": "Раз число обязательно заканчивается на 0, эта цифра уже стоит на своём месте — какие цифры остались для остальных пяти позиций?",
    },
    "coins_lesson": 60,
    "coins_boss": 40,
}

LESSON_NATURAL_COMPARE = {
    "topic": "Сравнение натуральных чисел",
    "context_theme": "detective",
    "explanation": (
        "Чтобы сравнить два натуральных числа, сначала смотрят на количество цифр в каждом из них "
        "(у натуральных чисел не бывает лишних нулей в начале записи): число с бо́льшим количеством цифр "
        "всегда больше. Если количество цифр одинаковое, числа сравнивают разряд за разрядом слева направо, "
        "начиная со старшего разряда: как только в одном и том же разряде цифры отличаются, число с бо́льшей "
        "цифрой в этом разряде и оказывается больше, а все разряды правее уже не важны. Если во всех разрядах "
        "цифры совпали, числа равны. Для записи сравнения используют знаки > (больше), < (меньше) и = (равно)."
    ),
    "explanation_game": (
        "Дело №2 начинается там же, где закончилось первое: сейф с кодом 987650 оказался пуст, но рядом с ним "
        "вор обронил ворох перепутанных бирок от старинных экспонатов, и смотритель музея никак не может "
        "понять, какие числа на них больше. Первая улика лежит на поверхности: бирка с числом 4820 и бирка с "
        "числом 758 — вчитываться не нужно, достаточно посчитать цифры: у 4820 их четыре, у 758 — три, и раз "
        "лишних нулей спереди у натуральных чисел не бывает, число с бо́льшим количеством цифр и оказывается "
        "больше. Вторая пара бирок хитрее: 5391 и 5289 — цифр поровну, четыре и четыре, так что придётся идти "
        "по разрядам слева направо, как по следу: тысячи совпадают, 5 и 5, а вот в разряде сотен уже видна "
        "разница — 3 против 2, и на этом расследование можно останавливать, всё, что правее, уже не влияет на "
        "ответ, 5391 больше. Третья улика оказалась ловушкой смотрителя: он был уверен, что бирка «099» "
        "больше бирки «85», ведь на ней «целых три символа» — но детектив быстро объяснил, что у настоящих "
        "натуральных чисел нули спереди не пишут, «099» — это просто 99, и оно, конечно, больше 85, но совсем "
        "не потому, что в записи было три знака. Расставив все бирки по возрастанию, ты замечаешь: вор "
        "действительно охотился именно за экспонатом с самым большим числом в зале — а значит, следующий сейф "
        "должен открыть число ещё крупнее, чем прежний код."
    ),
    "questions": [
        {
            "text": "Какое из чисел больше: 3208 или 875?",
            "options": ["3208, потому что у него больше цифр", "875, потому что там восьмёрка в начале",
                        "Числа равны", "Сравнить нельзя без разрядной таблицы"],
            "correct": 0,
            "hint": "Посчитай, сколько цифр в каждом числе — не читая их полностью.",
            "explanation": "У 3208 четыре цифры, у 875 — три. У натуральных чисел без лишних нулей спереди число с бо́льшим количеством цифр всегда больше."
        },
        {
            "text": "Сравни числа 6152 и 6149. Какое из них больше?",
            "options": ["6152", "6149", "Они равны", "Нельзя определить без вычитания"],
            "correct": 0,
            "hint": "Цифры тысяч и сотен у обоих чисел совпадают — сравнивай дальше, разряд за разрядом.",
            "explanation": "Тысячи (6) и сотни (1) у чисел совпадают. В разряде десятков у 6152 стоит 5, а у 6149 — 4. Так как 5>4, число 6152 больше — единицы уже можно не смотреть."
        },
        {
            "text": "На бирке написано число 099. Какое число здесь на самом деле записано?",
            "options": ["99", "990", "9", "У натуральных чисел так не пишут, значит определить нельзя"],
            "correct": 0,
            "hint": "У натуральных чисел не бывает нулей в начале записи — они просто «лишние».",
            "explanation": "Ноль впереди ничего не меняет: 099 — это то же самое, что 99. Значащими являются только цифры после ведущих нулей."
        },
        {
            "text": "Расставь числа по возрастанию: 340, 3400, 43.",
            "options": ["43, 340, 3400", "3400, 340, 43", "340, 43, 3400", "43, 3400, 340"],
            "correct": 0,
            "hint": "Сначала отсортируй числа по количеству цифр, а уже потом сравнивай числа с одинаковым числом цифр.",
            "explanation": "43 — двузначное, 340 — трёхзначное, 3400 — четырёхзначное. Чем больше цифр, тем больше число, поэтому по возрастанию: 43, 340, 3400."
        },
        {
            "text": "Сравни числа 47328 и 47528. В каком разряде впервые видна разница, и какое число больше?",
            "options": ["В разряде сотен, 47528 больше", "В разряде десятков, 47328 больше",
                        "В разряде тысяч, 47528 больше", "Числа равны"],
            "correct": 0,
            "hint": "Иди по разрядам слева направо: десятки тысяч, тысячи, сотни...",
            "explanation": "Десятки тысяч (4) и тысячи (7) совпадают. Первое отличие — в разряде сотен: 3 у первого числа против 5 у второго. Значит 47528 больше, а разряды десятков и единиц уже роли не играют."
        }
    ],
    "boss_task": {
        "answer": "5371",
        "text": (
            "Второй сейф откликнется на число, о котором вор оставил подсказку: «Моё число четырёхзначное, "
            "оно меньше, чем 5372, но больше, чем 5290, а все его цифры различны — и это самое большое "
            "число, которое подходит под все условия». Найди это число."
        ),
        "solution": (
            "Ответ: 5371. Раз число должно быть меньше 5372, самый большой возможный кандидат — число прямо "
            "под ним, 5371. Проверяем: 5371 меньше 5372 — подходит. Сравниваем 5371 и 5290 по разрядам: "
            "тысячи совпадают (5 и 5), а в разряде сотен у 5371 стоит 3, у 5290 — 2, значит 5371 больше 5290 "
            "— тоже подходит. Остаётся проверить цифры: 5, 3, 7, 1 — все разные. Все условия выполнены, "
            "значит код — 5371."
        ),
        "hint1": "Раз число должно быть меньше 5372, попробуй начать с числа прямо под ним — 5371 — и проверь, подходит ли оно под все условия.",
        "hint2": "Не забудь проверить оба условия по отдельности: сначала сравнение по разрядам с 5290, а потом — что все четыре цифры разные.",
    },
    "coins_lesson": 65,
    "coins_boss": 40,
}

LESSON_ROUNDING = {
    "topic": "Округление чисел",
    "context_theme": "detective",
    "explanation": (
        "Округление — это замена числа на близкое к нему, но более простое, которое оканчивается нулями "
        "начиная с нужного разряда. Чтобы округлить число до заданного разряда, смотрят на цифру, стоящую "
        "сразу справа от него: если эта цифра 5 или больше, цифру округляемого разряда увеличивают на 1 "
        "(при необходимости с переносом в старшие разряды), а если она меньше 5 — цифру округляемого разряда "
        "оставляют без изменений. Все цифры правее округляемого разряда заменяют нулями. Результат округления "
        "записывают со знаком ≈ (приближённо равно)."
    ),
    "explanation_game": (
        "Дело №3 начинается сразу после разгадки сейфа 5371: стало ясно, что вор охотится за самыми крупными "
        "числами в музее, а в третьем зале он оставил смятую записку с суммой ущерба, где чернила размыты и "
        "видно только «примерно 47 000» — точных цифр не разобрать, и тебе придётся научиться подгонять числа "
        "под круглые, как это делает сам вор. Первая улика — ценник экспоната 3782: чтобы округлить его до "
        "сотен, смотрят не на сотни, а на цифру сразу справа, на десятки — там стоит 8, а это больше пяти, "
        "значит сотни увеличиваются на единицу и получается 3800. Вторая улика хитрее: число 6500 нужно "
        "округлить до тысяч — цифра сотен ровно 5, а по правилу «пять и больше — округляем вверх» ответ "
        "оказывается 7000, а не 6000, как поспешил решить растерянный смотритель. Третья улика — настоящая "
        "ловушка: экспонат «49999» округляют до тысяч, а справа от тысяч стоит девятка — округление вверх "
        "заставляет всю запись «покатиться» слева направо, как одометр, и в итоге получается ровно 50000. "
        "Сложив все округлённые суммы ущерба, ты выходишь на итоговое число — и оно подозрительно похоже на "
        "код от следующего сейфа."
    ),
    "questions": [
        {
            "text": "Округли число 273 до десятков.",
            "options": ["270", "280", "200", "300"],
            "correct": 0,
            "hint": "Посмотри на цифру единиц — она решает, округлять вверх или вниз.",
            "explanation": "Цифра единиц у числа 273 — это 3, а 3 меньше 5, поэтому десятки не увеличиваются и получается 270."
        },
        {
            "text": "Округли число 6500 до тысяч.",
            "options": ["7000", "6000", "6500", "6900"],
            "correct": 0,
            "hint": "Посмотри на цифру сотен: если она 5 или больше, тысячи увеличиваются.",
            "explanation": "Цифра сотен у числа 6500 — это 5, а по правилу «5 и больше — округляем вверх» тысячи увеличиваются на 1: получается 7000."
        },
        {
            "text": "Округли число 49999 до тысяч.",
            "options": ["50000", "49000", "40000", "49900"],
            "correct": 0,
            "hint": "Цифра сотен здесь 9 — округление идёт вверх и «прокатывается» через все девятки.",
            "explanation": "Цифра сотен — 9, значит округляем вверх. Все девятки в старших разрядах превращаются в нули, а впереди появляется новый разряд: получается 50000, как в примере с одометром."
        },
        {
            "text": "После округления числа 3782 до сотен получили 3800. Какая цифра «решила» округлить в бо́льшую сторону?",
            "options": ["8 — цифра десятков", "7 — цифра сотен", "2 — цифра единиц", "3 — цифра тысяч"],
            "correct": 0,
            "hint": "Округляемый разряд — сотни. Смотреть нужно на цифру сразу справа от него.",
            "explanation": "При округлении до сотен смотрят на цифру десятков — она стоит сразу справа от округляемого разряда. У числа 3782 это 8, а 8 больше 5, поэтому сотни увеличились с 7 до 8."
        },
        {
            "text": "Товар стоит 18 470 рублей. Округли эту сумму до тысяч.",
            "options": ["18000", "19000", "18500", "18400"],
            "correct": 0,
            "hint": "Посмотри на цифру сотен — 4 или больше 5?",
            "explanation": "Цифра сотен у числа 18470 — это 4, а 4 меньше 5, поэтому тысячи не увеличиваются и результат округления — 18000."
        }
    ],
    "boss_task": {
        "answer": "4650",
        "text": (
            "Третий сейф откликнется на число, которое обладает двумя свойствами сразу: при округлении до "
            "сотен оно даёт 4700, а при округлении до тысяч — 5000. Найди наименьшее число, которое подходит "
            "под оба условия."
        ),
        "solution": (
            "Ответ: 4650. Чтобы округление до сотен дало 4700, цифра десятков должна быть 5 или больше, а "
            "значит подходят числа от 4650 до 4749. Чтобы округление этого же числа до тысяч дало 5000, "
            "нужно, чтобы цифра сотен была 5 или больше при тысячах 4 (тогда округление идёт вверх до 5000) — "
            "этому условию из диапазона 4650–4749 отвечают все числа, ведь цифра сотен у них 6 или 7. Значит "
            "весь диапазон 4650–4749 подходит под оба условия, а наименьшее число в нём — 4650."
        ),
        "hint1": "Сначала подбери диапазон чисел, которые при округлении до сотен дают 4700 — вспомни, что решает цифра десятков.",
        "hint2": "Затем проверь, какие числа из этого диапазона при округлении до тысяч дают 5000, и выбери наименьшее из них.",
    },
    "coins_lesson": 60,
    "coins_boss": 35,
}

LESSON_DIVISIBILITY = {
    "topic": "Делимость чисел",
    "context_theme": "detective",
    "explanation": (
        "Число a делится на число b без остатка, если существует такое натуральное число c, что a = b × c; "
        "тогда b называют делителем числа a, а a — кратным числу b. Есть удобные признаки делимости, которые "
        "позволяют узнать, делится ли число, не выполняя само деление: на 2 делятся числа, оканчивающиеся на "
        "0, 2, 4, 6 или 8 (чётные); на 5 делятся числа, оканчивающиеся на 0 или 5; на 10 делятся числа, "
        "оканчивающиеся на 0; на 3 делятся числа, у которых сумма цифр делится на 3; на 9 делятся числа, у "
        "которых сумма цифр делится на 9."
    ),
    "explanation_game": (
        "Дело №4 стартует от найденного кода 4650: проверив бирки, ты замечаешь, что вор не просто искал "
        "самые большие числа — он ещё и раскладывал украденные монеты ровными рядами, а те, что не влезали "
        "без остатка, оставлял на месте преступления. Первая улика: 48 монет он разложил по 6 в ряд без "
        "остатка — значит 6 является делителем числа 48, а 48, в свою очередь, кратно шести. Вторая улика — "
        "витрина с ценником 372: чтобы понять, делится ли он на 3, не нужно делить в столбик, достаточно "
        "сложить цифры — 3+7+2=12, а 12 делится на 3, значит и само число 372 делится на 3. Третья улика — "
        "сравнение похожих цифровых замков: замок «4815» оканчивается на 5, значит он открывается признаком "
        "делимости на 5, а вот замок «4810» оканчивается на 0 и поэтому открывается сразу тремя признаками — "
        "на 2, на 5 и на 10. Собрав все совпадения, ты понимаешь: настоящий код следующего сейфа должен "
        "делиться сразу и на 2, и на 3, и на 5 одновременно — и это резко сужает круг подозреваемых чисел."
    ),
    "questions": [
        {
            "text": "48 делится на 6 без остатка (48 = 6×8). Как называют число 6 по отношению к 48?",
            "options": ["Делитель", "Остаток", "Частное", "Ни один из вариантов"],
            "correct": 0,
            "hint": "Делитель — это число, на которое делят.",
            "explanation": "6 — делитель числа 48, потому что 48 делится на 6 без остатка. А 48, в свою очередь, называют кратным числу 6."
        },
        {
            "text": "Какое из чисел делится на 2 без остатка?",
            "options": ["4 371", "5 928", "8 013", "2 227"],
            "correct": 1,
            "hint": "Посмотри на последнюю цифру каждого числа — она должна быть чётной.",
            "explanation": "5 928 оканчивается на 8 — это чётная цифра, значит число делится на 2. Остальные числа оканчиваются на нечётные цифры (1, 3, 7)."
        },
        {
            "text": "Сумма цифр числа 5 481 равна 5+4+8+1=18. Делится ли число 5481 на 9?",
            "options": ["Да, делится, потому что 18 делится на 9", "Нет, не делится",
                        "Да, но только на 3, а не на 9", "Нельзя определить без деления в столбик"],
            "correct": 0,
            "hint": "Признак делимости на 9: сумма цифр должна делиться на 9.",
            "explanation": "18 делится на 9 (18=9×2), значит по признаку делимости и само число 5481 делится на 9 без остатка."
        },
        {
            "text": "Число оканчивается на 0. На какие из чисел оно точно делится?",
            "options": ["На 2, 5 и 10 одновременно", "Только на 2", "Только на 5", "Ни на одно из них"],
            "correct": 0,
            "hint": "Ноль в конце — самый «щедрый» признак делимости.",
            "explanation": "Если число оканчивается нулём, оно делится сразу и на 2, и на 5, и на 10 — это самый сильный из простых признаков делимости."
        },
        {
            "text": "Число 7 236 — сумма цифр 7+2+3+6=18. Верно ли, что оно делится и на 3, и на 9?",
            "options": ["Да, оба признака выполняются, ведь 18 делится и на 3, и на 9", "Только на 3",
                        "Только на 9", "Ни на одно из чисел"],
            "correct": 0,
            "hint": "Проверь: делится ли 18 на 3? А на 9?",
            "explanation": "18 делится и на 3 (18=3×6), и на 9 (18=9×2), значит число 7236 делится и на 3, и на 9 одновременно."
        }
    ],
    "boss_task": {
        "answer": "4680",
        "text": (
            "Четвёртый сейф откроет число, которое одновременно делится и на 2, и на 3, и на 5, при этом оно "
            "наименьшее из всех чисел, которые больше 4650. Найди этот код."
        ),
        "solution": (
            "Ответ: 4680. Число, которое делится сразу на 2, 3 и 5, обязательно делится на их произведение — "
            "30 (это НОК этих трёх чисел). Проверяем сам код предыдущего сейфа: 4650 ÷ 30 = 155 — делится "
            "ровно, без остатка. Значит следующее подходящее число — это 4650 + 30 = 4680. Проверка: 4680 "
            "оканчивается на 0 (делится на 2 и на 5), а сумма цифр 4+6+8+0=18 делится на 3 — все условия "
            "выполнены."
        ),
        "hint1": "Число, которое делится и на 2, и на 3, и на 5 одновременно, обязательно делится на их произведение — какое это число?",
        "hint2": "Проверь, делится ли сам код от прошлого сейфа (4650) на это произведение — если да, следующее подходящее число получится, если прибавить это произведение ещё раз.",
    },
    "coins_lesson": 60,
    "coins_boss": 35,
}

LESSON_PRIME_COMPOSITE = {
    "topic": "Простые и составные числа",
    "context_theme": "detective",
    "explanation": (
        "Натуральное число, у которого ровно два делителя — единица и само число, называют простым "
        "(например, 2, 3, 5, 7, 11...). Число 1 не относится ни к простым, ни к составным — у него всего "
        "один делитель. Число, у которого делителей больше двух, называют составным — его всегда можно "
        "представить в виде произведения простых чисел; такое представление называют разложением числа на "
        "простые множители, и для каждого числа оно единственно (с точностью до порядка множителей)."
    ),
    "explanation_game": (
        "Дело №5 продолжается от кода 4680: открыв сейф, ты находишь не число, а связку из карточек с "
        "числами на цепочках и записку вора: «Раздели их на два лагеря». Первая улика — число 17: у него "
        "ровно два делителя, 1 и само 17, а значит оно простое, как настоящий детектив-одиночка. Вторая "
        "улика — число 21: у него делители 1, 3, 7 и 21 — уже четыре, а значит оно составное и раскладывается "
        "в произведение простых: 21 = 3 × 7. Третья улика оказалась ловушкой: кто-то был уверен, что число 1 "
        "тоже простое, ведь оно «делится само на себя» — но у простых чисел должно быть ровно два разных "
        "делителя, а у единицы делитель всего один, она сама, поэтому 1 не относится ни к простым, ни к "
        "составным. Разложив все составные числа на цепочках на простые множители, ты собираешь из них "
        "финальную комбинацию — самое маленькое составное число ровно с шестью делителями, у которого в "
        "разложении встречаются и двойка, и тройка."
    ),
    "questions": [
        {
            "text": "У числа 17 всего два делителя — 1 и 17. Как называют такие числа?",
            "options": ["Простые", "Составные", "Чётные", "Круглые"],
            "correct": 0,
            "hint": "У простого числа делителей ровно два.",
            "explanation": "Число, у которого только два делителя — единица и само число, называется простым. У числа 17 делителей действительно ровно два."
        },
        {
            "text": "У числа 21 есть делители 1, 3, 7 и 21. Как называют такие числа?",
            "options": ["Составные", "Простые", "Нечётные", "Кратные"],
            "correct": 0,
            "hint": "У составного числа делителей больше двух.",
            "explanation": "У числа 21 четыре делителя (1, 3, 7, 21) — больше двух, значит оно составное и раскладывается в произведение простых: 21 = 3 × 7."
        },
        {
            "text": "Число 1 является...",
            "options": ["Ни простым, ни составным", "Простым", "Составным", "И простым, и составным одновременно"],
            "correct": 0,
            "hint": "У простых чисел должно быть ровно два разных делителя. Сколько делителей у единицы?",
            "explanation": "У числа 1 всего один делитель — оно само, поэтому оно не подходит ни под определение простого (нужно два делителя), ни под определение составного."
        },
        {
            "text": "Разложи число 36 на простые множители.",
            "options": ["2 × 2 × 3 × 3", "2 × 18", "4 × 9", "6 × 6"],
            "correct": 0,
            "hint": "Раскладывай, пока все множители не станут простыми числами (2, 3, 5, 7...).",
            "explanation": "36 = 4×9 = (2×2)×(3×3) = 2×2×3×3 — все четыре множителя простые, дальше раскладывать некуда."
        },
        {
            "text": "Число 84 раскладывается как 84 = 2 × 2 × 3 × 7. Сколько различных простых чисел входит в это разложение?",
            "options": ["3 (2, 3 и 7)", "4", "2", "84"],
            "correct": 0,
            "hint": "Считай не количество множителей, а количество разных простых чисел среди них.",
            "explanation": "В разложении 2 × 2 × 3 × 7 повторяется только двойка, а различных простых чисел три: 2, 3 и 7."
        }
    ],
    "boss_task": {
        "answer": "12",
        "text": (
            "Пятый сейф откроет наименьшее составное число, у которого ровно 6 делителей, а в разложении на "
            "простые множители встречаются и 2, и 3 (и никакие другие простые числа). Найди этот код."
        ),
        "solution": (
            "Ответ: 12. Если число равно 2^a × 3^b, то у него ровно (a+1)×(b+1) делителей. Нужно, чтобы "
            "(a+1)×(b+1)=6, а множители 2 и 3 присутствовали оба. Подходят пары: a=2,b=1 → 2²×3=12, делителей "
            "(2+1)(1+1)=6; и a=1,b=2 → 2×3²=18, делителей тоже 6. Из двух подходящих чисел, 12 и 18, "
            "наименьшее — 12."
        ),
        "hint1": "Вспомни: если число равно p^a × q^b (p и q — разные простые), то у него (a+1)×(b+1) делителей. Какие пары показателей дают 6?",
        "hint2": "Проверь оба варианта разложения — 2²×3 и 2×3² — и сравни, какое из получившихся чисел меньше.",
    },
    "coins_lesson": 60,
    "coins_boss": 35,
}

LESSON_GCD_LCM = {
    "topic": "НОД и НОК",
    "context_theme": "detective",
    "explanation": (
        "Наибольший общий делитель (НОД) двух чисел — это самое большое число, на которое оба числа делятся "
        "без остатка; его находят, раскладывая оба числа на простые множители и перемножая только общие "
        "множители, каждый в наименьшей из двух встретившихся степеней. Наименьшее общее кратное (НОК) — это "
        "самое маленькое число, которое делится сразу на оба исходных числа; его находят, перемножая все "
        "встречающиеся простые множители, каждый в наибольшей из степеней (а также по формуле "
        "НОК(a,b) = (a×b) ÷ НОД(a,b)). Если у чисел нет общих простых множителей, их НОД равен 1 — такие "
        "числа называют взаимно простыми."
    ),
    "explanation_game": (
        "Дело №6 — последнее в этом расследовании. Вор наконец пойман с поличным у главного зала, но "
        "сигнализация рассинхронизирована: он специально настроил два механизма так, чтобы один тикал каждые "
        "18 секунд, а другой — каждые 24, и щёлкали они почти всегда не совпадая. Чтобы понять, когда оба "
        "механизма щёлкнут одновременно и дверь музея захлопнется за вором окончательно, нужно найти "
        "наименьшее общее кратное 18 и 24 — самое маленькое число секунд, которое делится и на 18, и на 24. "
        "Раскладываем оба числа на простые множители: 18 = 2 × 3², 24 = 2³ × 3. НОК берёт каждый множитель в "
        "наибольшей из встретившихся степеней — 2³ и 3², то есть 8 × 9 = 72. Пока ты считаешь, инспектор "
        "напоминает и про обратную задачу: если бы понадобилось разложить украденные экспонаты поровну в "
        "витрины на 18 и на 24 полки без остатка, самое большое возможное число экспонатов в ряду — это "
        "НОД(18,24), наибольший общий делитель. Он берёт только общие множители в наименьшей степени: у 2×3² "
        "и 2³×3 общими являются лишь 2¹ и 3¹, значит НОД(18,24) = 6. Ровно через 72 секунды сигнализация "
        "срабатывает одновременно, дверь музея захлопывается за вором навсегда — дело о краже чисел закрыто."
    ),
    "questions": [
        {
            "text": "Найди НОД чисел 12 и 18, перечислив их делители.",
            "options": ["6", "3", "36", "2"],
            "correct": 0,
            "hint": "Делители 12: 1,2,3,4,6,12. Делители 18: 1,2,3,6,9,18. Какой из общих — самый большой?",
            "explanation": "Общие делители 12 и 18 — это 1, 2, 3 и 6. Самый большой из них — 6, значит НОД(12,18) = 6."
        },
        {
            "text": "Найди НОК чисел 4 и 6.",
            "options": ["12", "24", "10", "2"],
            "correct": 0,
            "hint": "Выпиши кратные каждого числа по порядку и найди первое общее: 4,8,12... и 6,12...",
            "explanation": "Кратные 4: 4,8,12,16... Кратные 6: 6,12,18... Первое общее число — 12, значит НОК(4,6)=12."
        },
        {
            "text": "Один фонарик мигает каждые 5 секунд, другой — каждые 8 секунд. Оба мигнули одновременно. Через сколько секунд они снова мигнут одновременно?",
            "options": ["Через 40 секунд (НОК(5,8))", "Через 13 секунд (сумма)",
                        "Через 1 секунду (НОД(5,8))", "Через 3 секунды (разность)"],
            "correct": 0,
            "hint": "Момент одновременного мигания — это наименьшее общее кратное двух промежутков.",
            "explanation": "5 и 8 не имеют общих простых множителей, поэтому НОК(5,8) = 5×8 = 40. Фонарики снова мигнут одновременно через 40 секунд."
        },
        {
            "text": "У чисел 9 и 16 нет ни одного общего делителя, кроме 1. Чему равен их НОД?",
            "options": ["1", "0", "9", "16"],
            "correct": 0,
            "hint": "Такие числа называют взаимно простыми — их наибольший общий делитель самый маленький из возможных.",
            "explanation": "Если у чисел нет общих простых множителей, их НОД всегда равен 1 — такие числа называют взаимно простыми."
        },
        {
            "text": "Известно, что 12 × 18 = 216, а НОД(12,18) = 6. Чему равен НОК(12,18) по формуле НОК = (a×b) ÷ НОД?",
            "options": ["36", "216", "6", "12"],
            "correct": 0,
            "hint": "Подставь числа в формулу: 216 ÷ 6.",
            "explanation": "НОК(12,18) = 216 ÷ 6 = 36. Проверка: 36 действительно делится и на 12, и на 18, и меньше него нет ни одного общего кратного."
        }
    ],
    "boss_task": {
        "answer": "72",
        "text": (
            "Финальный сейф связан с той самой сигнализацией: один механизм тикает каждые 18 секунд, другой — "
            "каждые 24 секунды, и оба сработали одновременно в момент поимки вора. Через сколько секунд они "
            "снова сработают одновременно — это и есть последний код дела?"
        ),
        "solution": (
            "Ответ: 72. Раскладываем оба числа на простые множители: 18 = 2 × 3², 24 = 2³ × 3. Наименьшее "
            "общее кратное берёт каждый простой множитель в наибольшей из встретившихся степеней: 2³ и 3², "
            "то есть 8 × 9 = 72. Значит, оба механизма снова сработают одновременно через 72 секунды."
        ),
        "hint1": "Разложи оба числа на простые множители: 18 и 24.",
        "hint2": "НОК — это произведение всех встречающихся множителей в наибольшей из степеней: сравни степени 2 и степени 3 в обоих разложениях.",
    },
    "coins_lesson": 70,
    "coins_boss": 45,
}

LESSON_CONTROL_NATURAL_NUMBERS = {
    "topic": "Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Это итоговая проверка по всем темам раздела «Натуральные числа»: чтение и запись "
        "многозначных чисел, разряды, сравнение чисел, округление, признаки делимости, "
        "разложение числа на простые множители, а также нахождение наибольшего общего делителя "
        "(НОД) и наименьшего общего кратного (НОК). Каждое задание проверяет отдельное умение из "
        "шести пройденных уроков раздела."
    ),
    "explanation_game": (
        "Дверь музея захлопнулась за вором, дело о краже чисел закрыто — но прежде чем оно "
        "отправится в архив, старший инспектор требует итоговый отчёт по всем шести делам: если "
        "хоть один факт не сойдётся, преступника придётся отпустить из-за процессуальной ошибки. "
        "Тебе нужно ещё раз пройтись по каждой улике — от того, что ноль не входит в натуральный "
        "ряд, а у самого ряда нет последнего числа, до кода 72, которым захлопнулась сигнализация "
        "в последнем деле. Инспектор придирчиво сверяет разряды в записях чисел, проверяет, "
        "правильно ли расставлены знаки сравнения и округления, требует ещё раз показать признаки "
        "делимости и разложение на простые множители — и напоследок просит найти НОД и НОК пары "
        "чисел, чтобы окончательно убедиться, что ты усвоил все шесть уроков. Только когда все "
        "ответы сходятся, инспектор ставит печать «дело закрыто» — и дело действительно уходит в "
        "архив, где, как ты вскоре узнаешь, вора ждёт куда более интересный сюрприз."
    ),
    "questions": [
        {
            "text": "Какое из утверждений о натуральных числах верно?",
            "options": [
                "У натурального ряда нет последнего (самого большого) числа",
                "Число 0 — это натуральное число",
                "Между двумя соседними натуральными числами всегда есть ещё одно натуральное число",
                "Натуральных чисел конечное количество"
            ],
            "correct": 0,
            "hint": "К любому натуральному числу всегда можно прибавить единицу.",
            "explanation": "К любому, даже самому большому натуральному числу всегда можно прибавить единицу и получить следующее — поэтому самого большого числа не существует."
        },
        {
            "text": "Запиши цифрами число «два миллиона пятьдесят тысяч триста».",
            "options": ["2 050 300", "2 500 300", "2 050 030", "20 050 300"],
            "correct": 0,
            "hint": "Миллионы — 2, тысячи — 050, единицы — 300.",
            "explanation": "2 миллиона — 2 000 000, 50 тысяч — 050 000, и ещё 300: вместе 2 050 300."
        },
        {
            "text": "Какой знак нужно поставить между числами 45 908 и 45 890?",
            "options": [">", "<", "=", "нельзя сравнить"],
            "correct": 0,
            "hint": "Числа с одинаковым количеством цифр сравнивают по разрядам слева направо, начиная с первого несовпадающего.",
            "explanation": "Оба числа пятизначные, первые два разряда совпадают (45), а дальше у первого числа разряд сотен — 9, у второго — 8. Так как 9 > 8, то 45 908 > 45 890."
        },
        {
            "text": "Округли число 6 748 до сотен.",
            "options": ["6 700", "6 800", "6 750", "7 000"],
            "correct": 0,
            "hint": "Смотри на цифру десятков — она решает, округлять вниз или вверх.",
            "explanation": "Цифра десятков — 4, это меньше 5, значит округляем вниз: 6 748 → 6 700."
        },
        {
            "text": "Какое из чисел делится и на 3, и на 9: 189, 245, 372, 501?",
            "options": ["189", "245", "372", "501"],
            "correct": 0,
            "hint": "Число делится на 9, если сумма его цифр делится на 9.",
            "explanation": "Сумма цифр 189: 1+8+9=18, а 18 делится на 9 — значит и 189 делится на 9 (а значит, и на 3). У остальных чисел сумма цифр на 9 не делится."
        },
        {
            "text": "Разложи число 84 на простые множители.",
            "options": ["2×2×3×7", "2×3×3×7", "2×2×3×5", "2×2×7×7"],
            "correct": 0,
            "hint": "Дели число 84 последовательно на простые числа: сначала на 2, потом ещё раз, потом на следующие простые.",
            "explanation": "84 = 2×42 = 2×2×21 = 2×2×3×7. Проверка: 2×2×3×7 = 84."
        },
        {
            "text": "Найди НОД чисел 28 и 42.",
            "options": ["14", "7", "4", "28"],
            "correct": 0,
            "hint": "Выпиши все делители обоих чисел и найди самый большой общий.",
            "explanation": "Делители 28: 1,2,4,7,14,28. Делители 42: 1,2,3,6,7,14,21,42. Самый большой общий делитель — 14."
        },
        {
            "text": "Найди НОК чисел 9 и 12.",
            "options": ["36", "3", "108", "18"],
            "correct": 0,
            "hint": "Разложи оба числа на простые множители и возьми каждый множитель в наибольшей степени.",
            "explanation": "9 = 3², 12 = 2²×3. НОК = 2²×3² = 4×9 = 36."
        }
    ],
    "boss_task": {
        "answer": "36",
        "text": (
            "Инспектор просит подготовить сувенирные наборы для закрытия дела: на складе музея "
            "108 значков «Детектив чисел» и 144 карточки-подсказки. Собери наибольшее возможное "
            "количество одинаковых наборов без остатка. Сколько получится наборов и сколько "
            "значков и карточек будет в каждом?"
        ),
        "solution": (
            "Ответ: 36 наборов, по 3 значка и 4 карточки в каждом. Наибольшее количество "
            "одинаковых наборов без остатка — это НОД(108,144). Разложим числа: 108 = 2²×3³, "
            "144 = 2⁴×3². Общие множители в наименьшей степени: 2²×3² = 4×9 = 36 — это и есть НОД, "
            "то есть количество наборов. Значков в наборе: 108 ÷ 36 = 3. Карточек в наборе: "
            "144 ÷ 36 = 4."
        ),
        "hint1": "Наибольшее количество одинаковых наборов без остатка — это НОД количества значков и карточек.",
        "hint2": "Найди НОД(108, 144), разложив оба числа на простые множители, а затем раздели каждое число на найденный НОД.",
    },
    "coins_lesson": 80,
    "coins_boss": 50,
}

LESSON_ADD_SUBTRACT = {
    "topic": "Сложение и вычитание",
    "context_theme": "detective",
    "explanation": (
        "Сложение натуральных чисел подчиняется двум свойствам: переместительному (от перестановки "
        "слагаемых сумма не меняется: a + b = b + a) и сочетательному (слагаемые можно группировать "
        "любым способом: (a + b) + c = a + (b + c)). Эти свойства позволяют считать в уме быстрее — "
        "например, объединять числа так, чтобы получалась круглая сумма. Вычитание — действие, "
        "обратное сложению: чтобы найти неизвестное слагаемое, из суммы вычитают известное. При "
        "вычитании числа из суммы его можно вычесть только из одного слагаемого: (a + b) − c = "
        "a + (b − c), если c ≤ b, — это тоже упрощает вычисления."
    ),
    "explanation_game": (
        "Вор пойман, но расследование не закончено: в кармане у него нашёлся потрёпанный гроссбух с "
        "записями о десятках прошлых краж за много лет — суммы похищенного, зачёркивания, поправки "
        "чернилами. Это архив всех его старых дел, и в нём наверняка спрятаны другие улики. Первая "
        "страница — длинная колонка сумм, которую вор явно складывал в уме: считать длинным столбиком "
        "у него не было времени. Ты замечаешь его приём — переместительное свойство сложения "
        "позволяет складывать числа в любом порядке, поэтому вор группировал слагаемые так, чтобы "
        "получались круглые десятки и сотни: вместо 47 + 26 + 13 он сначала складывал 47 + 13 = 60, а "
        "потом прибавлял 26. Сочетательное свойство подтверждает: группировать можно как угодно — "
        "результат не изменится. Внизу страницы — итоговая сумма, а рядом с ней чернильное пятно "
        "скрывает одно из слагаемых. Чтобы восстановить его, нужно вычесть из итога все слагаемые, "
        "которые видно. Найденное число оказывается номером страницы гроссбуха, к которой приколот "
        "ключ от потайного ящика в столе смотрителя музея — расследование архива вора только "
        "начинается."
    ),
    "questions": [
        {
            "text": "Какое равенство иллюстрирует переместительное свойство сложения?",
            "options": ["34 + 18 = 18 + 34", "34 + 18 = 34 − 18", "34 + 0 = 34", "34 + 18 > 34"],
            "correct": 0,
            "hint": "Переместительное свойство говорит о перестановке слагаемых местами.",
            "explanation": "Переместительное свойство сложения означает, что от перестановки слагаемых сумма не меняется: 34 + 18 = 18 + 34."
        },
        {
            "text": "Как удобнее всего посчитать 23 + 7 + 40, используя сочетательное свойство?",
            "options": [
                "Сначала сложить 23 и 7, получив круглое число 30, потом прибавить 40",
                "Сначала сложить 7 и 40, потом прибавить 23",
                "Обязательно считать строго по порядку слева направо",
                "Умножить все числа между собой"
            ],
            "correct": 0,
            "hint": "Ищи пару чисел, которая в сумме даёт круглое число.",
            "explanation": "23 + 7 = 30 — круглое число, с которым легко работать дальше: 30 + 40 = 70. Сочетательное свойство разрешает группировать слагаемые в любом порядке."
        },
        {
            "text": "Найди сумму 38 + 45 + 62, удобно сгруппировав слагаемые.",
            "options": ["145", "150", "135", "140"],
            "correct": 0,
            "hint": "Найди среди чисел пару, которая в сумме даёт круглое число: 38 и 62.",
            "explanation": "38 + 62 = 100 (круглое число), а затем 100 + 45 = 145."
        },
        {
            "text": "Вычисли (56 + 24) − 6 самым быстрым способом.",
            "options": ["74", "68", "80", "70"],
            "correct": 0,
            "hint": "Число 6 можно вычесть только из одного слагаемого — из 24, ведь 6 ≤ 24.",
            "explanation": "(56 + 24) − 6 = 56 + (24 − 6) = 56 + 18 = 74."
        },
        {
            "text": "В понедельник в музее было 275 экспонатов, во вторник добавили 138, а в среду убрали 96. Сколько экспонатов стало в музее в среду?",
            "options": ["317", "413", "301", "329"],
            "correct": 0,
            "hint": "Сначала прибавь то, что добавили, а затем вычти то, что убрали.",
            "explanation": "275 + 138 = 413, затем 413 − 96 = 317 экспонатов."
        }
    ],
    "boss_task": {
        "answer": "113",
        "text": (
            "Итоговая сумма в колонке гроссбуха — 500. Из слагаемых видно только три числа: 128, 165 и "
            "94, а четвёртое залито чернилами. Найди пропавшее число — это номер страницы, к которой "
            "приколот ключ."
        ),
        "solution": (
            "Ответ: 113. Сложи видимые слагаемые: 128 + 165 + 94 = 387. Вычти эту сумму из итога: "
            "500 − 387 = 113 — это и есть пропавшее слагаемое и номер нужной страницы."
        ),
        "hint1": "Сначала сложи все видимые слагаемые: 128, 165 и 94.",
        "hint2": "Затем вычти получившуюся сумму из общего итога 500 — останется искомое число.",
    },
    "coins_lesson": 55,
    "coins_boss": 32,
}

LESSON_MULT_DIVIDE = {
    "topic": "Умножение и деление",
    "context_theme": "detective",
    "explanation": (
        "Умножение натуральных чисел обладает переместительным свойством (a × b = b × a) и "
        "сочетательным ((a × b) × c = a × (b × c)) — они позволяют менять порядок множителей ради "
        "удобства вычислений. Распределительное свойство умножения относительно сложения "
        "(a × (b + c) = a×b + a×c) позволяет раскладывать одно из чисел на удобные слагаемые и "
        "упрощать умножение в уме. Деление бывает двух видов: деление нацело, когда число делится "
        "без остатка, и деление с остатком, когда после деления остаётся число меньше делителя — его "
        "записывают в виде a = b × q + r, где остаток r меньше делителя b."
    ),
    "explanation_game": (
        "Ключ из гроссбуха подходит к потайному ящику в столе смотрителя музея — внутри план склада, "
        "расчерченный на прямоугольную сетку из полок: 24 ряда по 18 полок в каждом. Чтобы быстро "
        "прикинуть, сколько всего полок на складе, не пересчитывая их по одной, ты применяешь "
        "распределительное свойство умножения: 24 × 18 = 24 × (20 − 2) = 24×20 − 24×2 = 480 − 48 = 432 "
        "полки. На плане отмечен ряд, где нужно разложить 250 экспонатов поровну по 9 полкам, но 250 "
        "на 9 не делится нацело: 250 = 9 × 27 + 7, значит на 27 полок положат по 9 экспонатов, а "
        "последние 7 останутся лишними — похоже, вор останавливался именно здесь, потому что остаток "
        "не сходился с описью. Чтобы найти номер отмеченного вором ряда, нужно ещё одно вычисление: "
        "45 × 16, разложив 16 на 10 + 6, даёт 450 + 270 = 720, а разделив 720 на 120 нацело, получаем "
        "6 — номер ряда, где спрятана каменная шкатулка."
    ),
    "questions": [
        {
            "text": "Какое равенство иллюстрирует распределительное свойство умножения?",
            "options": [
                "6 × (10 + 3) = 6×10 + 6×3",
                "6 × 10 = 10 × 6",
                "(6 × 10) × 3 = 6 × (10 × 3)",
                "6 × 0 = 0"
            ],
            "correct": 0,
            "hint": "Распределительное свойство связывает умножение и сложение внутри скобок.",
            "explanation": "Распределительное свойство: чтобы умножить число на сумму, можно умножить его на каждое слагаемое отдельно и сложить результаты: 6 × (10 + 3) = 6×10 + 6×3."
        },
        {
            "text": "Вычисли 15 × 23 удобным способом, представив 23 = 20 + 3.",
            "options": ["345", "335", "350", "360"],
            "correct": 0,
            "hint": "Отдельно посчитай 15×20 и 15×3, а потом сложи результаты.",
            "explanation": "15 × 23 = 15×20 + 15×3 = 300 + 45 = 345."
        },
        {
            "text": "При делении 47 на 6 неполное частное равно 7. Чему равен остаток?",
            "options": ["5", "6", "1", "7"],
            "correct": 0,
            "hint": "Умножь делитель на неполное частное и вычти результат из делимого: 47 − 6×7.",
            "explanation": "6 × 7 = 42, а 47 − 42 = 5. Остаток должен быть меньше делителя, и 5 меньше 6 — всё верно."
        },
        {
            "text": "Число 84 при делении на 7 даёт остаток 0. Как называется такое деление?",
            "options": ["Деление нацело", "Деление с остатком", "Умножение", "Деление невозможно"],
            "correct": 0,
            "hint": "Если остатка нет вообще, деление называют особым словом.",
            "explanation": "Если число делится без остатка (остаток равен 0), такое деление называют делением нацело."
        },
        {
            "text": "132 экспоната разложили поровну по 8 витринам. Сколько экспонатов оказалось в каждой витрине и сколько осталось лишних?",
            "options": [
                "16 в каждой витрине, 4 лишних",
                "15 в каждой витрине, 12 лишних",
                "17 в каждой витрине, 0 лишних",
                "16 в каждой витрине, 0 лишних"
            ],
            "correct": 0,
            "hint": "8 × 16 = 128 — сравни это с 132.",
            "explanation": "8 × 16 = 128, а 132 − 128 = 4. Значит, в каждой витрине по 16 экспонатов, и 4 остаются лишними."
        }
    ],
    "boss_task": {
        "answer": "6",
        "text": (
            "Отмеченный вором ряд склада найден по формуле: вычисли 45 × 16 удобным способом, разложив "
            "16 на 10 + 6 (распределительное свойство), а затем раздели результат на 120 и найди "
            "неполное частное — это и есть номер ряда со шкатулкой."
        ),
        "solution": (
            "Ответ: 6-й ряд. 45 × 16 = 45×10 + 45×6 = 450 + 270 = 720. Далее 720 ÷ 120 = 6, причём "
            "делится нацело, без остатка — это и есть номер ряда, где спрятана каменная шкатулка."
        ),
        "hint1": "Сначала посчитай 45 × 16, разложив 16 на 10 + 6.",
        "hint2": "Затем раздели получившееся число на 120 — оно делится без остатка.",
    },
    "coins_lesson": 60,
    "coins_boss": 35,
}

LESSON_POWER = {
    "topic": "Степень числа",
    "context_theme": "detective",
    "explanation": (
        "Степень числа с натуральным показателем — это сокращённая запись многократного умножения "
        "одинаковых множителей: aⁿ означает, что число a умножается само на себя n раз (a — основание "
        "степени, n — показатель степени). Квадрат числа — это степень с показателем 2 (a² = a × a), "
        "куб числа — степень с показателем 3 (a³ = a × a × a). Например, 5² = 25, а 5³ = 125. Отдельно "
        "запоминают: любое число в первой степени равно самому себе (a¹ = a), а любое число, кроме "
        "нуля, в нулевой степени равно 1 (a⁰ = 1)."
    ),
    "explanation_game": (
        "В шестом ряду склада, куда указало вычисление, ты находишь тяжёлую каменную шкатулку в форме "
        "идеального куба со стороной 6 сантиметров — на резном замке надпись «сколько камня внутри?». "
        "Замок открывается числом, равным объёму куба, а объём куба со стороной a вычисляется как a в "
        "третьей степени, то есть куб числа: 6³ = 6 × 6 × 6 = 216. Ты вводишь 216 — крышка со щелчком "
        "открывается. Внутри лежит плоская квадратная плитка со стороной 9 сантиметров и гравировкой "
        "«площадь — это твой следующий шаг»: площадь квадрата равна стороне в квадрате, a², то есть "
        "9² = 81. Число 81 выгравировано на обратной стороне плитки рядом со странной незаконченной "
        "формулой — похоже, вор не успел её досчитать, прежде чем его поймали, и теперь досчитать её "
        "предстоит тебе."
    ),
    "questions": [
        {
            "text": "Чему равен квадрат числа 8?",
            "options": ["64", "16", "56", "72"],
            "correct": 0,
            "hint": "Квадрат числа — это число, умноженное само на себя: 8 × 8.",
            "explanation": "8² = 8 × 8 = 64."
        },
        {
            "text": "Чему равен куб числа 5?",
            "options": ["125", "15", "25", "100"],
            "correct": 0,
            "hint": "Куб числа — это число, умноженное само на себя три раза: 5 × 5 × 5.",
            "explanation": "5³ = 5 × 5 × 5 = 125."
        },
        {
            "text": "В записи 7⁴ число 4 называется…",
            "options": ["показателем степени", "основанием степени", "произведением", "остатком"],
            "correct": 0,
            "hint": "Число, показывающее, сколько раз умножается основание, стоит наверху справа.",
            "explanation": "В записи aⁿ число n (в нашем случае 4) называется показателем степени — оно показывает, сколько раз основание умножается само на себя."
        },
        {
            "text": "Чему равен объём куба со стороной 3 см?",
            "options": ["27 куб. см", "9 куб. см", "6 куб. см", "18 куб. см"],
            "correct": 0,
            "hint": "Объём куба вычисляется как сторона в третьей степени.",
            "explanation": "Объём куба со стороной a равен a³. 3³ = 3 × 3 × 3 = 27 куб. см."
        },
        {
            "text": "Какая запись означает «5 умножить само на себя 3 раза»?",
            "options": ["5³", "3⁵", "5 × 3", "5 + 5 + 5"],
            "correct": 0,
            "hint": "Показатель степени показывает количество одинаковых множителей.",
            "explanation": "«Умножить число само на себя 3 раза» — это возвести его в третью степень: 5³ = 5 × 5 × 5."
        }
    ],
    "boss_task": {
        "answer": "58",
        "text": (
            "На обратной стороне плитки выгравирована незаконченная запись: 2³ + 5² × 2. Вору не "
            "хватило времени её вычислить. Помоги закончить: чему равно значение этого выражения?"
        ),
        "solution": (
            "Ответ: 58. Сначала вычисли каждую степень отдельно: 2³ = 8, 5² = 25. Затем выполни "
            "умножение: 25 × 2 = 50. И только в конце сложение: 8 + 50 = 58."
        ),
        "hint1": "Сначала вычисли каждую степень отдельно: 2³ и 5².",
        "hint2": "Не забудь про умножение — оно выполняется раньше сложения.",
    },
    "coins_lesson": 65,
    "coins_boss": 40,
}

LESSON_ORDER_OPERATIONS = {
    "topic": "Порядок действий",
    "context_theme": "detective",
    "explanation": (
        "В выражениях без скобок сначала выполняют возведение в степень (если оно есть), затем "
        "умножение и деление — в том порядке, в котором они встречаются слева направо, — и только "
        "после этого сложение и вычитание, тоже слева направо. Если в выражении есть скобки, действия "
        "в скобках выполняются первыми, а уже после этого — степень, умножение или деление, а затем "
        "сложение или вычитание в оставшейся части выражения. Нарушение этого порядка — одна из самых "
        "частых ошибок в вычислениях."
    ),
    "explanation_game": (
        "Рядом с числом 58 на плитке обнаруживается ещё одна строка, стёртая почти начисто, но под "
        "лупой читается: (216 − 81) ÷ 27 + 4 × 2³. Смотритель музея, вызванный на консультацию, "
        "узнаёт этот шифр — именно такими выражениями вор запечатывал последние страницы своего "
        "архива, чтобы отбить желание считать их у любого, кто не знает порядка действий. Если "
        "выполнять действия не по порядку, получится бессмысленное число, а если правильно — сначала "
        "скобки, потом степень, потом умножение и деление слева направо, и только в конце сложение — "
        "получится код от последнего, самого главного тайника архива. Считаем по порядку: "
        "(216 − 81) = 135, затем 135 ÷ 27 = 5, отдельно 2³ = 8, затем 4 × 8 = 32, и наконец 5 + 32 = 37. "
        "Код 37 открывает последний тайник — в нём не краденые экспонаты, а стопка блокнотов с "
        "описанием ещё сотни зазевавшихся чисел по всему городу: похоже, у вора были ученики. Раздел "
        "«Действия с натуральными числами» пройден, дело об архиве закрыто — но у детектива чисел "
        "явно прибавилось работы впереди."
    ),
    "questions": [
        {
            "text": "В каком порядке нужно выполнять действия в выражении 12 + 3 × 4?",
            "options": [
                "Сначала умножение, потом сложение",
                "Сначала сложение, потом умножение",
                "Строго слева направо, как написано",
                "Порядок не важен, результат будет одинаковым"
            ],
            "correct": 0,
            "hint": "Умножение и деление выполняются раньше сложения и вычитания, если нет скобок.",
            "explanation": "Без скобок умножение выполняется раньше сложения: 12 + 3×4 = 12 + 12 = 24."
        },
        {
            "text": "Вычисли: 20 − 8 ÷ 2.",
            "options": ["16", "6", "12", "24"],
            "correct": 0,
            "hint": "Сначала выполни деление, потом вычитание.",
            "explanation": "8 ÷ 2 = 4, затем 20 − 4 = 16."
        },
        {
            "text": "Вычисли: (14 − 6) × 3.",
            "options": ["24", "36", "8", "42"],
            "correct": 0,
            "hint": "Скобки выполняются первыми, независимо от того, какое действие внутри них.",
            "explanation": "14 − 6 = 8, затем 8 × 3 = 24."
        },
        {
            "text": "Вычисли: 3² + 4 × 2.",
            "options": ["17", "20", "22", "14"],
            "correct": 0,
            "hint": "Сначала вычисли степень, затем умножение, и только потом сложение.",
            "explanation": "3² = 9, 4 × 2 = 8, затем 9 + 8 = 17."
        },
        {
            "text": "Вычисли: (18 + 6) ÷ 4 × 2.",
            "options": ["12", "6", "24", "9"],
            "correct": 0,
            "hint": "После скобок деление и умножение идут по порядку слева направо: сначала деление, потом умножение.",
            "explanation": "18 + 6 = 24, затем 24 ÷ 4 = 6, и наконец 6 × 2 = 12."
        }
    ],
    "boss_task": {
        "answer": "37",
        "text": (
            "Финальный код архива зашифрован в выражении (216 − 81) ÷ 27 + 4 × 2³. Вычисли его "
            "значение, соблюдая правильный порядок действий, — это и есть код последнего тайника."
        ),
        "solution": (
            "Ответ: 37. Сначала скобки: 216 − 81 = 135. Затем степень: 2³ = 8. Теперь деление и "
            "умножение слева направо: 135 ÷ 27 = 5, и 4 × 8 = 32. И в самом конце сложение: 5 + 32 = 37."
        ),
        "hint1": "Сначала посчитай, что в скобках, и отдельно вычисли степень 2³.",
        "hint2": "Раздели результат в скобках на 27, умножь 4 на результат степени, а затем сложи оба числа.",
    },
    "coins_lesson": 70,
    "coins_boss": 45,
}

LESSON_CONTROL_NATURAL_OPERATIONS = {
    "topic": "Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Это итоговая проверка по всем темам раздела «Действия с натуральными числами»: "
        "переместительное и сочетательное свойства сложения, распределительное свойство "
        "умножения, деление с остатком, степень числа (квадрат и куб), а также порядок "
        "выполнения действий в выражениях со скобками и степенями. Каждое задание проверяет "
        "отдельное умение из четырёх пройденных уроков раздела."
    ),
    "explanation_game": (
        "Архив закрыт, код 37 сработал, и тайник со стопкой блокнотов учеников вора уже почти у "
        "тебя в руках — но старший инспектор снова требует полного отчёта, на этот раз по "
        "разделу «Действия с натуральными числами»: если хоть один приём вычислений подведёт, "
        "расследование блокнотов придётся отложить. Ты ещё раз показываешь, как удобно "
        "группировать слагаемые ради круглых чисел, как раскрывать скобки по распределительному "
        "свойству, как находить неполное частное и остаток при делении по полкам, как возводить "
        "числа в квадрат и куб, и в каком порядке считать выражения со скобками и степенями. Пока "
        "инспектор сверяет последний пункт отчёта, ты замечаешь на обороте страницы странную "
        "приписку — вместо чисел там буквы k и m, а рядом набросан план музейного зала: k рядов "
        "по 9 экспонатов и m рядов по 10. Похоже, кто-то из учеников вора уже начал шифровать "
        "записи буквами задолго до того, как ты нашёл первый гроссбух, — и теперь тебе предстоит "
        "прочитать это первым."
    ),
    "questions": [
        {
            "text": "Вычисли удобным способом: 358 + 642 + 247, сгруппировав слагаемые ради круглого числа.",
            "options": ["1247", "1237", "1147", "1257"],
            "correct": 0,
            "hint": "Найди среди слагаемых пару, которая в сумме даёт круглое число: 358 и 642.",
            "explanation": "358 + 642 = 1000 (круглое число), затем 1000 + 247 = 1247."
        },
        {
            "text": "Чему равна разность любого числа и нуля?",
            "options": ["Самому этому числу", "Нулю", "Единице", "Нельзя определить"],
            "correct": 0,
            "hint": "Вычитание нуля не меняет число.",
            "explanation": "Если из числа вычесть 0, число не изменится: a − 0 = a."
        },
        {
            "text": "Раскрой скобки, используя распределительное свойство: 10 × (a − 4).",
            "options": ["10a − 40", "10a − 4", "a − 40", "10a + 40"],
            "correct": 0,
            "hint": "Умножь 10 на каждое слагаемое (уменьшаемое и вычитаемое) внутри скобок отдельно.",
            "explanation": "10 × (a − 4) = 10×a − 10×4 = 10a − 40."
        },
        {
            "text": "Раскрой скобки: (3 + 8) × x.",
            "options": ["11x", "3x + 8", "24x", "3 + 8x"],
            "correct": 0,
            "hint": "Сначала сложи числа в скобках, а затем умножь результат на x.",
            "explanation": "(3 + 8) × x = 11 × x = 11x."
        },
        {
            "text": "На складе 53 экспоната распределяют поровну по 6 полкам. Сколько экспонатов на каждой полке и какой остаток?",
            "options": [
                "8 экспонатов на полке, 5 в остатке",
                "9 экспонатов на полке, 1 в остатке",
                "7 экспонатов на полке, 11 в остатке",
                "8 экспонатов на полке, 6 в остатке"
            ],
            "correct": 0,
            "hint": "Умножь 6 на пробное неполное частное и сравни результат с 53: 6×8=48.",
            "explanation": "6 × 8 = 48, а 53 − 48 = 5. Остаток 5 меньше делителя 6 — значит, деление выполнено верно: 53 = 6×8 + 5."
        },
        {
            "text": "Запиши произведение 7 × 7 × 7 в виде степени и найди его значение.",
            "options": ["7³ = 343", "3⁷ = 2187", "7³ = 21", "7² = 49"],
            "correct": 0,
            "hint": "Число повторяется множителем три раза — это и есть показатель степени.",
            "explanation": "7 × 7 × 7 — это число 7, умноженное само на себя 3 раза, то есть 7³. 7³ = 343."
        },
        {
            "text": "Сравни: 3⁴ и 4³. Какой знак нужно поставить?",
            "options": [">", "<", "=", "сравнить нельзя"],
            "correct": 0,
            "hint": "Сначала вычисли каждую степень отдельно, а потом сравни числа.",
            "explanation": "3⁴ = 3×3×3×3 = 81, а 4³ = 4×4×4 = 64. Так как 81 > 64, то 3⁴ > 4³."
        },
        {
            "text": "Вычисли: 6² − 3² + 20 ÷ 4.",
            "options": ["32", "29", "38", "17"],
            "correct": 0,
            "hint": "Сначала вычисли обе степени и раздели 20 на 4, а уже потом складывай и вычитай слева направо.",
            "explanation": "6² = 36, 3² = 9, 20 ÷ 4 = 5. Затем 36 − 9 + 5 = 32."
        }
    ],
    "boss_task": {
        "answer": "192",
        "text": (
            "На обороте отчёта — приписка не рукой вора: буквы k и m вместо чисел, а рядом план "
            "музейного зала: k рядов по 9 экспонатов в каждом и m рядов по 10 экспонатов в каждом. "
            "1) Составь буквенное выражение для подсчёта всех экспонатов в зале. "
            "2) Вычисли общее количество экспонатов, если k = 8, а m = 12."
        ),
        "solution": (
            "Ответ: выражение 9k + 10m, при k=8 и m=12 получается 192 экспоната. В k рядах по 9 "
            "экспонатов — всего 9×k, в m рядах по 10 экспонатов — всего 10×m, вместе 9k + 10m. "
            "При k=8: 9×8=72. При m=12: 10×12=120. Всего: 72 + 120 = 192 экспоната."
        ),
        "hint1": "Сначала запиши отдельно, сколько экспонатов в k рядах по 9, и сколько в m рядах по 10.",
        "hint2": "Сложи оба буквенных произведения в одно выражение, а затем подставь k=8 и m=12 и вычисли.",
    },
    "coins_lesson": 82,
    "coins_boss": 52,
}

LESSON_EXPRESSIONS = {
    "topic": "Числовые и буквенные выражения",
    "context_theme": "detective",
    "explanation": (
        "Числовое выражение — это запись из чисел, соединённых знаками действий, например 3×5+7. "
        "Буквенное выражение — это запись, где вместо одного или нескольких чисел стоит буква "
        "(переменная), например 3a+15: буква обозначает любое число, которое пока неизвестно или "
        "может меняться. Чтобы найти значение буквенного выражения при конкретном значении "
        "переменной, букву заменяют этим числом и вычисляют результат по обычным правилам порядка "
        "действий. Одно и то же буквенное выражение может принимать разные числовые значения — в "
        "зависимости от того, какое число подставлено вместо буквы."
    ),
    "explanation_game": (
        "В последнем тайнике архива нашлась не только стопка блокнотов, но и почерк, явно "
        "отличающийся от почерка самого вора, — это записи его «учеников», которые тоже "
        "промышляли по музеям города, но зашифровывали свои дела не числами, а буквами, чтобы "
        "посторонний, даже завладев блокнотом, ничего не понял без секретного значения переменной. "
        "На первой странице — запись «3a + 15» и пометка на полях мелким почерком. Ты понимаешь: "
        "это буквенное выражение, где a — переменная, а конкретное число вместо неё известно "
        "только автору записи. Числовое выражение получится, если букву заменить числом — тогда "
        "его можно вычислить обычным способом, соблюдая порядок действий: сначала умножение, потом "
        "сложение. Разгадав пометку на полях («сколько будет, если от десяти пальцев на руках "
        "отнять три»), ты находишь значение a = 7 и подставляешь его в выражение — получившееся "
        "число оказывается номером следующей страницы блокнота, где спрятана новая улика."
    ),
    "questions": [
        {
            "text": "Какая из записей является буквенным выражением?",
            "options": ["4x + 9", "4 × 9 + 9", "36", "4 + 9 = 13"],
            "correct": 0,
            "hint": "Буквенное выражение обязательно содержит букву (переменную).",
            "explanation": "Буквенное выражение — это запись, в которой вместо числа стоит буква. Только в «4x + 9» есть переменная x."
        },
        {
            "text": "Найди значение выражения 5b − 12 при b = 6.",
            "options": ["18", "17", "30", "42"],
            "correct": 0,
            "hint": "Подставь 6 вместо b и вычисли: сначала умножение, потом вычитание.",
            "explanation": "5×6 = 30, затем 30 − 12 = 18."
        },
        {
            "text": "Выражение 2n + 1 при n = 3 даёт 7, при n = 5 даёт 11. Чему равно значение этого выражения при n = 4?",
            "options": ["9", "8", "10", "6"],
            "correct": 0,
            "hint": "Подставь n = 4 в выражение 2n + 1.",
            "explanation": "2×4 = 8, затем 8 + 1 = 9."
        },
        {
            "text": "Одна тетрадь стоит x рублей. Как записать стоимость 8 таких тетрадей?",
            "options": ["8x", "x + 8", "x ÷ 8", "x − 8"],
            "correct": 0,
            "hint": "Стоимость нескольких одинаковых предметов находят умножением цены на количество.",
            "explanation": "Стоимость 8 тетрадей по x рублей каждая записывается как 8×x, или короче — 8x."
        },
        {
            "text": "Периметр квадрата со стороной a вычисляется по формуле P = 4a. Чему равен периметр при a = 9 см?",
            "options": ["36 см", "13 см", "18 см", "81 см"],
            "correct": 0,
            "hint": "Подставь a = 9 в выражение 4a.",
            "explanation": "P = 4 × 9 = 36 см."
        }
    ],
    "boss_task": {
        "answer": "36",
        "text": (
            "На первой странице блокнота учеников — выражение 3a + 15, а на полях пометка: «a — "
            "сколько будет, если от десяти пальцев на руках отнять три». Вычисли значение "
            "выражения — это номер страницы со следующей уликой."
        ),
        "solution": (
            "Ответ: 36. Сначала находим a: 10 − 3 = 7. Подставляем в выражение: 3 × 7 = 21, затем "
            "21 + 15 = 36 — это номер нужной страницы."
        ),
        "hint1": "Сначала пойми, чему равно a, разгадав пометку на полях: 10 − 3.",
        "hint2": "Подставь найденное значение в выражение 3a + 15 и вычисли: сначала умножение, потом сложение.",
    },
    "coins_lesson": 55,
    "coins_boss": 32,
}

LESSON_EQUATIONS = {
    "topic": "Уравнения",
    "context_theme": "detective",
    "explanation": (
        "Уравнение — это равенство, содержащее неизвестное число, обозначенное буквой; значение "
        "переменной, при котором равенство становится верным, называется корнем уравнения. Чтобы "
        "найти корень, используют зависимости между компонентами действий: неизвестное слагаемое "
        "находят, вычитая из суммы известное слагаемое; неизвестное уменьшаемое — прибавляя к "
        "разности вычитаемое; неизвестное вычитаемое — вычитая из уменьшаемого разность; "
        "неизвестный множитель — деля произведение на известный множитель; неизвестное делимое — "
        "умножая частное на делитель; неизвестный делитель — деля делимое на частное."
    ),
    "explanation_game": (
        "На странице 36, найденной в прошлый раз, — не число и не буквенное выражение, а целое "
        "уравнение: x − 18 = 47, и приписка «здесь будет следующая встреча». Чтобы найти корень "
        "уравнения — то самое число x, при котором равенство станет верным, — вспоминаешь "
        "зависимость компонентов вычитания: x здесь уменьшаемое, значит, чтобы его найти, нужно к "
        "разности прибавить вычитаемое. x = 47 + 18 = 65. Расшифровка ведёт к дому 65 на соседней "
        "улице — судя по всему, именно там ученики вора назначают друг другу встречи, обмениваясь "
        "награбленным. Ты записываешь адрес и отправляешься туда, зная, что уравнения — это способ "
        "находить неизвестное, даже если оно спрятано за буквой."
    ),
    "questions": [
        {
            "text": "Что называют корнем уравнения?",
            "options": [
                "Значение переменной, при котором равенство становится верным",
                "Любое число в уравнении",
                "Знак равенства в уравнении",
                "Сумму всех чисел в уравнении"
            ],
            "correct": 0,
            "hint": "Корень — это то самое число, которое делает равенство истинным.",
            "explanation": "Корень уравнения — это значение переменной, при подстановке которого равенство становится верным."
        },
        {
            "text": "Реши уравнение: y + 24 = 60.",
            "options": ["36", "84", "26", "40"],
            "correct": 0,
            "hint": "Неизвестное слагаемое находят, вычитая из суммы известное слагаемое.",
            "explanation": "y = 60 − 24 = 36."
        },
        {
            "text": "Реши уравнение: 80 − z = 25.",
            "options": ["55", "105", "45", "65"],
            "correct": 0,
            "hint": "Неизвестное вычитаемое находят, вычитая из уменьшаемого разность.",
            "explanation": "z = 80 − 25 = 55."
        },
        {
            "text": "Реши уравнение: 8 × n = 96.",
            "options": ["12", "13", "8", "88"],
            "correct": 0,
            "hint": "Неизвестный множитель находят, деля произведение на известный множитель.",
            "explanation": "n = 96 ÷ 8 = 12."
        },
        {
            "text": "Реши уравнение: k ÷ 7 = 9.",
            "options": ["63", "16", "2", "56"],
            "correct": 0,
            "hint": "Неизвестное делимое находят, умножая частное на делитель.",
            "explanation": "k = 9 × 7 = 63."
        }
    ],
    "boss_task": {
        "answer": "65",
        "text": (
            "На странице 36 записано уравнение x − 18 = 47 с пометкой «здесь будет следующая "
            "встреча». Реши уравнение и узнай номер дома, куда нужно отправиться."
        ),
        "solution": (
            "Ответ: 65. Чтобы найти неизвестное уменьшаемое x, нужно к разности прибавить "
            "вычитаемое: x = 47 + 18 = 65. Встреча назначена у дома 65."
        ),
        "hint1": "Вспомни: неизвестное уменьшаемое находят, прибавляя к разности вычитаемое.",
        "hint2": "Подставь числа: 47 + 18.",
    },
    "coins_lesson": 62,
    "coins_boss": 38,
}

LESSON_FORMULAS = {
    "topic": "Формулы",
    "context_theme": "detective",
    "explanation": (
        "Формула — это буквенное равенство, которое связывает несколько величин и позволяет "
        "находить одну из них, если известны другие. Например, формула пути s = v × t связывает "
        "расстояние s, скорость v и время t: если известны скорость и время, умножив их, находят "
        "пройденный путь; если известны путь и время, разделив путь на время, находят скорость; "
        "если известны путь и скорость, разделив путь на скорость, находят время."
    ),
    "explanation_game": (
        "У дома 65 детектива встречает только что покинутый штаб учеников — сосед рассказывает, "
        "что один из них умчался на самокате в сторону вокзала буквально пять минут назад, а "
        "поезд отправляется через 24 минуты. До вокзала — 6 км, скорость самоката — 15 км/ч. "
        "Чтобы понять, успеет ли ученик и есть ли шанс перехватить его, нужна формула пути "
        "s = v × t, а точнее — обратная к ней: время находят, разделив путь на скорость, "
        "t = s ÷ v. Для самоката: 6 ÷ 15 = 0,4 часа, то есть ровно 24 минуты — впритык, но "
        "успевает. Детектив бежит к автобусной остановке: автобус до вокзала едет по той же "
        "дороге со скоростью 40 км/ч, и по той же формуле 6 ÷ 40 = 0,15 часа — это всего 9 минут. "
        "Автобус приезжает почти на четверть часа раньше самоката, и детектив успевает встретить "
        "ученика прямо на перроне, ещё до отправления поезда."
    ),
    "questions": [
        {
            "text": "Какая формула связывает путь, скорость и время?",
            "options": ["s = v × t", "s = v + t", "s = v − t", "s = v ÷ t"],
            "correct": 0,
            "hint": "Путь находят, умножая скорость на время движения.",
            "explanation": "Формула пути: s = v × t, где s — путь, v — скорость, t — время."
        },
        {
            "text": "Найди путь, если скорость 15 км/ч, а время в пути 3 часа.",
            "options": ["45 км", "18 км", "5 км", "12 км"],
            "correct": 0,
            "hint": "Используй формулу s = v × t.",
            "explanation": "s = 15 × 3 = 45 км."
        },
        {
            "text": "Путь 84 км пройден за 2 часа. Какова была скорость?",
            "options": ["42 км/ч", "168 км/ч", "82 км/ч", "40 км/ч"],
            "correct": 0,
            "hint": "Скорость находят, деля путь на время: v = s ÷ t.",
            "explanation": "v = 84 ÷ 2 = 42 км/ч."
        },
        {
            "text": "Автомобиль ехал со скоростью 60 км/ч и проехал 180 км. Сколько времени он был в пути?",
            "options": ["3 часа", "120 часов", "2 часа", "4 часа"],
            "correct": 0,
            "hint": "Время находят, деля путь на скорость: t = s ÷ v.",
            "explanation": "t = 180 ÷ 60 = 3 часа."
        },
        {
            "text": "Самокат едет со скоростью 15 км/ч. За сколько минут он проедет 6 км?",
            "options": ["24 минуты", "15 минут", "40 минут", "9 минут"],
            "correct": 0,
            "hint": "Сначала найди время в часах по формуле t = s ÷ v, а потом переведи в минуты (1 ч = 60 мин).",
            "explanation": "t = 6 ÷ 15 = 0,4 часа = 24 минуты."
        }
    ],
    "boss_task": {
        "answer": "да",
        "text": (
            "Ученик мчится на самокате к вокзалу: путь 6 км, скорость самоката 15 км/ч, а поезд "
            "отправляется через 24 минуты. Детектив бежит к автобусу, который идёт по той же "
            "дороге со скоростью 40 км/ч. Сравни время в пути у самоката и у автобуса и узнай, "
            "успевает ли детектив добраться до вокзала раньше отправления поезда."
        ),
        "solution": (
            "Ответ: да, успевает — автобус приезжает за 9 минут против 24 минут у самоката. "
            "Время самоката: t = 6 ÷ 15 = 0,4 часа = 24 минуты — он приезжает точно к отправлению "
            "поезда. Время автобуса: t = 6 ÷ 40 = 0,15 часа = 9 минут — детектив оказывается на "
            "вокзале почти на четверть часа раньше и успевает встретить ученика на перроне, ещё "
            "до отправления."
        ),
        "hint1": "Раздели путь на скорость для каждого способа передвижения: t = s ÷ v.",
        "hint2": "Переведи получившиеся часы в минуты (1 час = 60 минут) и сравни оба числа.",
    },
    "coins_lesson": 70,
    "coins_boss": 45,
}

LESSON_CONTROL_EXPRESSIONS_EQUATIONS = {
    "topic": "Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Это итоговая проверка по всем темам раздела «Выражения и уравнения»: числовые и "
        "буквенные выражения, составление выражений по условию и нахождение их значений при "
        "заданных переменных, понятия уравнения и корня уравнения, решение уравнений на основе "
        "зависимостей между компонентами действий, а также использование буквенных формул. "
        "Каждое задание проверяет отдельное умение из трёх пройденных уроков раздела."
    ),
    "explanation_game": (
        "Ты успеваешь встретить ученика прямо на перроне, но пока он, растерявшись, объясняет "
        "что-то невнятное, рядом оказывается инспектор — и замечает у него в кармане ещё один "
        "блокнот, потолще прежних, полностью исписанный уравнениями и формулами. Прежде чем "
        "открыть его, инспектор устраивает тебе проверку по всему разделу: просит отличить "
        "буквенное выражение от числового, составить выражение по условию, найти его значение при "
        "подстановке, вспомнить, что такое корень уравнения, решить несколько уравнений — и "
        "простых, и с несколькими действиями — по зависимостям компонентов, а под конец применить "
        "формулу пути, как в погоне у вокзала. Только когда все ответы сходятся, инспектор "
        "протягивает тебе найденный блокнот — на первой странице выведены два псевдонима, "
        "«Тень» и «Эхо», а рядом — головоломка с жетонами, которую тебе предстоит разгадать "
        "прямо сейчас, ещё до того, как блокнот унесут в архив для более подробного изучения."
    ),
    "questions": [
        {
            "text": "Что называют уравнением?",
            "options": [
                "Равенство, содержащее переменную, значение которой нужно найти",
                "Любую запись с буквой",
                "Выражение без знака равенства",
                "Число, умноженное на букву"
            ],
            "correct": 0,
            "hint": "Ключевое слово — «равенство» и «переменная, значение которой ищут».",
            "explanation": "Уравнение — это равенство, содержащее неизвестное число, обозначенное буквой, значение которой нужно найти."
        },
        {
            "text": "Какая из записей — буквенное выражение (не числовое и не уравнение)?",
            "options": ["5x + 7", "12 + 8", "x + 9 = 20", "45"],
            "correct": 0,
            "hint": "Буквенное выражение содержит переменную, но не содержит знак «=».",
            "explanation": "«5x + 7» содержит букву x и не является равенством — это буквенное выражение. «12+8» и «45» — числовые, а «x+9=20» — уравнение."
        },
        {
            "text": "Запиши в виде буквенного выражения: «произведение разности чисел 90 и 25 и числа n».",
            "options": ["(90 − 25) × n", "90 − 25 × n", "90 × n − 25", "(90 + 25) × n"],
            "correct": 0,
            "hint": "Сначала найди разность 90 и 25, а результат умножь на n — разность нужно взять в скобки.",
            "explanation": "«Разность чисел 90 и 25» — это (90 − 25), а «произведение этой разности и n» — (90 − 25) × n."
        },
        {
            "text": "Запиши в виде буквенного выражения: «к частному переменной y и числа 4 прибавить 18».",
            "options": ["y ÷ 4 + 18", "(y + 18) ÷ 4", "y ÷ (4 + 18)", "18 ÷ y + 4"],
            "correct": 0,
            "hint": "Сначала раздели y на 4, а затем прибавь 18 к результату.",
            "explanation": "«Частное y и 4» — это y ÷ 4, а «прибавить к нему 18» — y ÷ 4 + 18."
        },
        {
            "text": "Найди значение выражения b ÷ 4 + 9 × k, если b = 124, а k = 6.",
            "options": ["85", "94", "76", "138"],
            "correct": 0,
            "hint": "Сначала выполни деление и умножение по отдельности, а затем сложи результаты.",
            "explanation": "124 ÷ 4 = 31, 9 × 6 = 54. Затем 31 + 54 = 85."
        },
        {
            "text": "Реши уравнение: x + 58 = 126.",
            "options": ["68", "184", "58", "74"],
            "correct": 0,
            "hint": "Неизвестное слагаемое находят, вычитая из суммы известное слагаемое.",
            "explanation": "x = 126 − 58 = 68."
        },
        {
            "text": "Реши уравнение: 312 ÷ x = 39.",
            "options": ["8", "12 153", "6", "351"],
            "correct": 0,
            "hint": "Неизвестный делитель находят, деля делимое на частное.",
            "explanation": "x = 312 ÷ 39 = 8. Проверка: 312 ÷ 8 = 39 — верно."
        },
        {
            "text": "Реши уравнение по алгоритму (выдели последнее действие в левой части, затем найди неизвестный компонент): 3 × (x − 7) ÷ 6 = 9.",
            "options": ["25", "20", "34", "13"],
            "correct": 0,
            "hint": "Сначала найди 3×(x−7): раз это выражение при делении на 6 даёт 9, само оно равно 9×6.",
            "explanation": "3×(x−7) ÷ 6 = 9, значит 3×(x−7) = 9×6 = 54. Тогда x−7 = 54÷3 = 18. Значит x = 18+7 = 25. Проверка: 3×(25−7)÷6 = 3×18÷6 = 54÷6 = 9 — верно."
        },
        {
            "text": "Найди путь s, если скорость v = 18 км/ч, а время в пути t = 5 ч (используй формулу s = v × t).",
            "options": ["90 км", "23 км", "13 км", "3,6 км"],
            "correct": 0,
            "hint": "Путь находят, умножая скорость на время.",
            "explanation": "s = v × t = 18 × 5 = 90 км."
        },
        {
            "text": "Найди периметр P прямоугольного зала со сторонами a = 12 м и b = 9 м по формуле P = 2 × (a + b).",
            "options": ["42 м", "21 м", "108 м", "84 м"],
            "correct": 0,
            "hint": "Сначала сложи стороны a и b, а результат умножь на 2.",
            "explanation": "P = 2 × (12 + 9) = 2 × 21 = 42 м."
        }
    ],
    "boss_task": {
        "answer": "6 и 24",
        "text": (
            "На первой странице нового блокнота — головоломка с двумя псевдонимами. «Тень» "
            "хвастался, что собрал жетонов в 4 раза больше, чем «Эхо». После того как «Тень» "
            "отдал кому-то 18 жетонов, у него осталось ровно столько же, сколько было у «Эха» с "
            "самого начала. Обозначь количество жетонов «Эха» через x, вырази через x количество "
            "жетонов «Тени», составь уравнение по условию и найди, сколько жетонов было у каждого "
            "изначально."
        ),
        "solution": (
            "Ответ: у «Эха» было 6 жетонов, у «Тени» — 24. Пусть x — количество жетонов «Эха», "
            "тогда у «Тени» было 4x. После того как «Тень» отдал 18 жетонов, у него осталось "
            "4x − 18, и это равно x (столько же, сколько было у «Эха»): 4x − 18 = x. Переносим x "
            "в левую часть: 3x = 18, значит x = 6. Тогда у «Тени» было 4×6 = 24 жетона."
        ),
        "hint1": "Составь уравнение: количество жетонов «Тени» после того, как он отдал 18, равно количеству жетонов «Эха» в начале.",
        "hint2": "Уравнение получится таким: 4x − 18 = x. Перенеси x в одну часть и найди x.",
    },
    "coins_lesson": 85,
    "coins_boss": 55,
}

def seed_section_intro_if_missing(conn, grade: int, subject: str, section_title: str, intro: str):
    row = conn.execute(
        "SELECT id, intro FROM sections WHERE grade=? AND subject=? AND title=?",
        (grade, subject, section_title)
    ).fetchone()
    if not row or (row["intro"] and row["intro"].strip()):
        return
    conn.execute("UPDATE sections SET intro=? WHERE id=?", (intro, row["id"]))

SECTION_INTRO_NATURAL_NUMBERS = (
    "Каждый раз, когда ты считаешь шаги до подъезда, смотришь на счёт в игре или спрашиваешь "
    "«а сколько до 100 уровня» — ты уже пользуешься натуральными числами. Это самый первый и самый "
    "важный математический инструмент человека — старше письменности, старше денег, старше городов.\n\n"
    "Что это такое: натуральные числа — это числа, которыми считают предметы: 1, 2, 3, 4... и так без "
    "конца. Отдельно стоит число 0 — оно означает «ничего», пустоту, и это тоже важное изобретение.\n\n"
    "Почему без этого не обойтись: все остальные разделы математики — дроби, проценты, уравнения, "
    "геометрия — построены поверх натуральных чисел, как этажи дома поверх фундамента. Нельзя посчитать "
    "половину пиццы, если не умеешь считать целые куски. Нельзя решить уравнение, если не понимаешь, что "
    "значит «прибавить» и «сравнить».\n\n"
    "Зачем это тебе: без уверенного счёта, чтения больших чисел и понимания разрядов сложно посчитать "
    "сдачу в магазине, понять, сколько мегабайт весит игра, сравнить цены или разобраться в статистике "
    "любимой команды. Это не «для школы» — это инструмент на каждый день."
)

SECTION_INTRO_NATURAL_OPERATIONS = (
    "Ты уже умеешь читать, сравнивать и раскладывать натуральные числа — теперь пора разобраться, "
    "что происходит, когда их складывают, вычитают, умножают, делят и возводят в степень.\n\n"
    "Что это такое: действия с числами — сложение, вычитание, умножение, деление и возведение в "
    "степень — подчиняются определённым правилам и свойствам, которые позволяют считать быстрее и "
    "точнее, а не наугад.\n\n"
    "Почему без этого не обойтись: без порядка действий одно и то же выражение можно посчитать "
    "десятком разных способов и получить десяток разных ответов, а правильный только один. Свойства "
    "действий превращают долгие вычисления в столбик в короткие приёмы устного счёта.\n\n"
    "Зачем это тебе: умение быстро посчитать сдачу, разложить деньги или коллекцию поровну, "
    "прикинуть площадь комнаты или посчитать, сколько получится, если умножить цену на количество — "
    "всё это опирается на уверенное владение действиями с числами."
)

SECTION_INTRO_EXPRESSIONS_EQUATIONS = (
    "Ты уже умеешь считать с числами — сложение, умножение, степень, порядок действий. Но что "
    "делать, если одно из чисел неизвестно? Здесь на помощь приходят буквы.\n\n"
    "Что это такое: буквенные выражения используют буквы вместо чисел, чтобы записать общее "
    "правило сразу для любых значений. Уравнения — это равенства с неизвестным числом, которое "
    "нужно найти. Формулы связывают несколько величин между собой, как s = v × t.\n\n"
    "Почему без этого не обойтись: вся дальнейшая математика — от простых задач до сложной "
    "физики — построена на умении обозначать неизвестное буквой и находить его через известные "
    "величины. Это следующий шаг после умения просто считать.\n\n"
    "Зачем это тебе: формулы и уравнения помогают решать задачи из жизни — рассчитать, сколько "
    "успеешь пройти за час, сколько будет стоить покупка при разной цене или сколько времени "
    "займёт дорога — без буквенных обозначений эти вопросы решались бы только перебором чисел "
    "наугад."
)

SECTION_INTRO_FRACTIONS = (
    "Ты уже умеешь считать с целыми числами и решать уравнения. Но что делать, когда речь идёт "
    "не о целом, а только о его части — половине пирога, четверти часа, трети пути?\n\n"
    "Что это такое: обыкновенная дробь — это способ записать часть целого. Число под чертой "
    "(знаменатель) показывает, на сколько равных частей разделили целое, а число над чертой "
    "(числитель) — сколько таких частей взяли. Дроби можно сравнивать, складывать, вычитать, "
    "умножать и делить, а одну и ту же величину можно записать разными, но равными дробями.\n\n"
    "Почему без этого не обойтись: в жизни редко всё делится без остатка на круглые числа — "
    "рецепты, расписания, деньги, расстояния почти всегда приходится делить на части. Дроби — "
    "это универсальный язык для описания таких частей.\n\n"
    "Зачем это тебе: понимание дробей помогает разделить угощение поровну, посчитать, сколько "
    "времени осталось до конца урока, если прошло «две третьих», или понять рецепт, где сказано "
    "«три четверти стакана» — без дробей многие обычные задачи было бы невозможно даже "
    "сформулировать."
)

LESSON_FRACTION_CONCEPT = {
    "topic": "Понятие дроби",
    "context_theme": "detective",
    "explanation": (
        "Дробь — это способ записать часть целого. Число под чертой (знаменатель) показывает, "
        "на сколько равных частей разделили целое, а число над чертой (числитель) — сколько "
        "таких частей взяли. Чтобы изобразить дробь на координатном луче, отрезок от 0 до 1 "
        "делят на равное знаменателю число одинаковых частей, а затем отсчитывают от точки 0 "
        "столько частей, сколько показывает числитель — получившаяся точка и изображает дробь."
    ),
    "explanation_game": (
        "Блокнот, который тебе передал инспектор, начинается не с текста, а с чертежа: длинный "
        "коридор старого пакгауза у товарной станции, разделённый чёрточками на восемь одинаковых "
        "промежутков, и один из них обведён кружком с подписью «здесь» — а под чертежом всего два "
        "числа, одно над другим через горизонтальную черту: 5 и 8. Так Тень и Эхо обозначали не "
        "целое число, а дробь: знаменатель 8 показывает, на сколько равных частей разделили весь "
        "коридор, а числитель 5 — сколько таких частей нужно отсчитать от входа, чтобы попасть в "
        "нужную точку. Длина коридора известна и равна 24 метрам, поэтому каждая из восьми равных "
        "частей — это 24 ÷ 8 = 3 метра, а нужная точка лежит через пять таких частей от входа: "
        "5 × 3 = 15 метров — ровно так, как если бы отметку 5/8 нанесли на координатный луч от 0 "
        "до 1 и растянули его до реальных 24 метров. Отмерив шагами пятнадцать метров вдоль стены, "
        "ты замечаешь, что одна из половиц светлее остальных и слегка шатается под ногой."
    ),
    "questions": [
        {
            "text": "Что показывает знаменатель дроби?",
            "options": [
                "На сколько равных частей разделили целое",
                "Сколько частей целого взяли",
                "Само целое число",
                "Сумму числителя и знаменателя"
            ],
            "correct": 0,
            "hint": "Знаменатель стоит под чертой и говорит о делении целого.",
            "explanation": "Знаменатель показывает, на сколько равных частей разделили целое."
        },
        {
            "text": "Что показывает числитель дроби?",
            "options": [
                "Сколько равных частей целого взяли",
                "На сколько частей разделили целое",
                "Разницу между частями",
                "Общее число частей, которые остались"
            ],
            "correct": 0,
            "hint": "Числитель стоит над чертой и говорит о том, сколько частей взяли.",
            "explanation": "Числитель показывает, сколько равных частей целого взяли."
        },
        {
            "text": "В дроби 4/9 назови числитель и знаменатель.",
            "options": [
                "Числитель 4, знаменатель 9",
                "Числитель 9, знаменатель 4",
                "Числитель 4, знаменатель 4",
                "Числитель 9, знаменатель 9"
            ],
            "correct": 0,
            "hint": "Числитель — число над чертой, знаменатель — число под чертой.",
            "explanation": "В дроби 4/9 числитель — 4 (стоит сверху), знаменатель — 9 (стоит снизу)."
        },
        {
            "text": "Отрезок от 0 до 1 разделили на 6 равных частей. Какую точку изображает дробь 5/6?",
            "options": [
                "Пятую точку деления, считая от 0",
                "Шестую точку деления, считая от 0",
                "Точку ровно посередине отрезка",
                "Первую точку деления, считая от 1"
            ],
            "correct": 0,
            "hint": "Числитель показывает, сколько частей нужно отсчитать от точки 0.",
            "explanation": "Знаменатель 6 задаёт число частей деления, а числитель 5 — сколько из них отсчитать от 0, поэтому 5/6 — пятая точка из шести."
        },
        {
            "text": "Коридор длиной 20 метров разделили на 4 равные части. Где находится точка, соответствующая дроби 3/4?",
            "options": [
                "В 15 метрах от начала",
                "В 5 метрах от начала",
                "В 20 метрах от начала",
                "В 12 метрах от начала"
            ],
            "correct": 0,
            "hint": "Сначала найди длину одной части: 20 ÷ 4.",
            "explanation": "Одна часть равна 20 ÷ 4 = 5 метров, а точка 3/4 лежит через три такие части: 3 × 5 = 15 метров."
        }
    ],
    "boss_task": {
        "answer": "35",
        "text": (
            "На развороте блокнота — вторая пометка на случай, если первая ловушка не сработает: "
            "дробь 7/12 и указание отмерить её вдоль забора длиной 60 метров, начиная от угла "
            "склада. На каком расстоянии от угла склада нужно искать отметку?"
        ),
        "solution": (
            "Ответ: 35 метров. Одна из двенадцати равных частей забора — это 60 ÷ 12 = 5 метров, "
            "а нужная точка лежит через семь таких частей от угла: 7 × 5 = 35 метров."
        ),
        "hint1": "Раздели общую длину забора на знаменатель дроби, чтобы найти длину одной части.",
        "hint2": "Умножь длину одной части на числитель дроби.",
    },
    "coins_lesson": 55,
    "coins_boss": 32,
}

LESSON_FRACTION_TYPES = {
    "topic": "Виды дробей",
    "context_theme": "detective",
    "explanation": (
        "Дробь называют правильной, если её числитель меньше знаменателя — такая дробь всегда "
        "меньше целого. Дробь называют неправильной, если числитель больше знаменателя или равен "
        "ему — такая дробь равна целому или больше него. Смешанное число — это запись, в которой "
        "целая часть указана отдельно от правильной дробной части (например, 5 целых 2/5). Чтобы "
        "перевести неправильную дробь в смешанное число, числитель делят на знаменатель: частное "
        "становится целой частью, а остаток — числителем дробной части (знаменатель не меняется). "
        "Чтобы перевести смешанное число обратно в неправильную дробь, целую часть умножают на "
        "знаменатель, складывают с числителем дробной части, а результат записывают над тем же "
        "знаменателем."
    ),
    "explanation_game": (
        "Половица под ногой поддаётся легко: под ней — плоская железная коробочка с трёхзначным "
        "кодовым замком и клочок бумаги с записью «27/5 бухты» рядом с рисунком мотка верёвки. "
        "Дробь 27/5 — неправильная: её числитель больше знаменателя, значит она показывает больше, "
        "чем одно целое, и её удобнее представить как смешанное число. Чтобы перевести неправильную "
        "дробь в смешанное число, числитель делят на знаменатель: 27 ÷ 5 = 5 в целой части и 2 в "
        "остатке, а остаток становится числителем новой дробной части с тем же знаменателем — "
        "получается 5 целых 2/5. Три цифры этого смешанного числа — 5, 2 и 5 — и есть код замка: "
        "набрав «5-2-5», ты слышишь щелчок, и крышка коробочки открывается."
    ),
    "questions": [
        {
            "text": "Какую дробь называют правильной?",
            "options": [
                "Дробь, у которой числитель меньше знаменателя",
                "Дробь, у которой числитель больше знаменателя",
                "Дробь, у которой числитель равен знаменателю",
                "Любую дробь со знаменателем больше 10"
            ],
            "correct": 0,
            "hint": "Правильная дробь всегда меньше целого.",
            "explanation": "Правильная дробь — та, у которой числитель меньше знаменателя, поэтому она меньше целого."
        },
        {
            "text": "Какую дробь называют неправильной?",
            "options": [
                "Дробь, у которой числитель больше знаменателя или равен ему",
                "Дробь, у которой числитель меньше знаменателя",
                "Дробь с чётным знаменателем",
                "Дробь, записанную без целой части"
            ],
            "correct": 0,
            "hint": "Неправильная дробь равна целому или больше него.",
            "explanation": "Неправильная дробь — та, у которой числитель больше знаменателя или равен ему."
        },
        {
            "text": "Какая из этих дробей неправильная?",
            "options": ["11/8", "5/9", "3/7", "2/3"],
            "correct": 0,
            "hint": "Найди дробь, у которой числитель больше знаменателя.",
            "explanation": "У дроби 11/8 числитель (11) больше знаменателя (8), значит она неправильная."
        },
        {
            "text": "Переведи неправильную дробь 17/4 в смешанное число.",
            "options": ["4 целых 1/4", "4 целых 4/17", "3 целых 1/4", "17 целых 4/4"],
            "correct": 0,
            "hint": "Раздели числитель на знаменатель: целая часть — частное, остаток — новый числитель.",
            "explanation": "17 ÷ 4 = 4 (целых) и 1 в остатке, значит 17/4 = 4 целых 1/4."
        },
        {
            "text": "Переведи смешанное число 3 целых 2/5 в неправильную дробь.",
            "options": ["17/5", "6/5", "32/5", "15/5"],
            "correct": 0,
            "hint": "Умножь целую часть на знаменатель и сложи с числителем дробной части.",
            "explanation": "3 × 5 + 2 = 17, значит 3 целых 2/5 = 17/5."
        }
    ],
    "boss_task": {
        "answer": "516",
        "text": (
            "Внутри первой коробочки — вторая, более крепкая, а на ней тем же почерком выведено "
            "31/6. Переведи эту неправильную дробь в смешанное число и назови три цифры нового кода."
        ),
        "solution": (
            "Ответ: 5 целых 1/6, код замка — 516. 31 ÷ 6 = 5 (целых) и 1 в остатке, значит "
            "31/6 = 5 целых 1/6."
        ),
        "hint1": "Раздели числитель на знаменатель — целая часть смешанного числа равна частному.",
        "hint2": "Остаток от деления становится числителем дробной части, знаменатель не меняется.",
    },
    "coins_lesson": 58,
    "coins_boss": 34,
}

LESSON_FRACTION_PROPERTY = {
    "topic": "Основное свойство дроби",
    "context_theme": "detective",
    "explanation": (
        "Основное свойство дроби: если числитель и знаменатель дроби умножить или разделить на "
        "одно и то же натуральное число (кроме нуля), значение дроби не изменится. На этом "
        "свойстве основаны два действия: сокращение дроби — деление числителя и знаменателя на их "
        "общий делитель, чтобы получить более простую равную дробь, и приведение дроби к новому "
        "знаменателю — умножение числителя и знаменателя на одно и то же число, чтобы получить "
        "дробь с нужным знаменателем (например, общим для нескольких дробей)."
    ),
    "explanation_game": (
        "Внутри второй коробочки — сложенный вчетверо листок с планом ряда гаражных боксов за "
        "старым складом, и на плане нарисована стрелка с дробью 24/36 — судя по всему, именно "
        "такой номер должен быть у нужного бокса. Но на дверях реальных боксов номеров нет — "
        "вместо них таблички с дробями: 3/4, 7/9, 5/6 и 8/12, и все они выглядят по-разному, хотя "
        "должны означать одно и то же место. Чтобы сравнить дроби с разными знаменателями, их "
        "приводят к общему знаменателю, например к 36: 3/4 = 27/36, 7/9 = 28/36, 5/6 = 30/36, а "
        "8/12 = 24/36. Совпадает только последняя — значит, нужный бокс тот, что помечен табличкой "
        "8/12, ведь дробь 24/36 сокращается до того же самого числа: 24 ÷ 12 = 2 и 36 ÷ 12 = 3, "
        "то есть в простейшем виде это 2/3 — точно так же, как и 8/12, если поделить её числитель "
        "и знаменатель на 4."
    ),
    "questions": [
        {
            "text": "Как звучит основное свойство дроби?",
            "options": [
                "Если числитель и знаменатель умножить или разделить на одно и то же число, значение дроби не изменится",
                "Числитель всегда должен быть меньше знаменателя",
                "Дробь можно умножать только на 1",
                "Знаменатель дроби нельзя изменять никогда"
            ],
            "correct": 0,
            "hint": "Свойство связано с умножением и делением числителя и знаменателя на одно число.",
            "explanation": "Основное свойство дроби: умножение или деление числителя и знаменателя на одно и то же натуральное число не меняет значения дроби."
        },
        {
            "text": "Сократи дробь 18/24 до простейшего вида.",
            "options": ["3/4", "9/12", "6/8", "2/3"],
            "correct": 0,
            "hint": "Найди наибольший общий делитель чисел 18 и 24.",
            "explanation": "НОД(18, 24) = 6, значит 18/24 = (18÷6)/(24÷6) = 3/4."
        },
        {
            "text": "Приведи дробь 2/5 к знаменателю 20.",
            "options": ["8/20", "2/20", "10/20", "4/20"],
            "correct": 0,
            "hint": "Узнай, во сколько раз новый знаменатель больше старого, и умножь числитель на это же число.",
            "explanation": "20 ÷ 5 = 4, значит числитель и знаменатель умножают на 4: 2/5 = (2×4)/(5×4) = 8/20."
        },
        {
            "text": "Какая из дробей равна 3/4?",
            "options": ["6/8", "5/7", "9/10", "7/9"],
            "correct": 0,
            "hint": "Приведи все дроби к одинаковому знаменателю и сравни с 3/4.",
            "explanation": "6/8 = (6÷2)/(8÷2) = 3/4, то есть эта дробь равна 3/4. Остальные дроби к 3/4 не сокращаются и не приводятся."
        },
        {
            "text": "Равны ли дроби 4/6 и 6/9?",
            "options": [
                "Да, обе сокращаются до 2/3",
                "Нет, 4/6 больше",
                "Нет, 6/9 больше",
                "Их нельзя сравнивать"
            ],
            "correct": 0,
            "hint": "Сократи каждую дробь до простейшего вида и сравни результаты.",
            "explanation": "4/6 = 2/3 и 6/9 = 2/3 — обе дроби равны."
        }
    ],
    "boss_task": {
        "answer": "ящик 2/3",
        "text": (
            "На обратной стороне листка — ещё одна пометка: дробь 14/21, а в глубине бокса — "
            "четыре ящика с табличками 2/5, 4/7, 2/3 и 5/6. Сократи дробь 14/21 до простейшего "
            "вида и определи, какой из ящиков обозначает то же число."
        ),
        "solution": (
            "Ответ: ящик 2/3. Наибольший общий делитель чисел 14 и 21 равен 7, значит "
            "14/21 = (14÷7)/(21÷7) = 2/3 — именно так помечен нужный ящик."
        ),
        "hint1": "Найди наибольший общий делитель числителя и знаменателя дроби 14/21.",
        "hint2": "Раздели и числитель, и знаменатель на этот делитель — получишь дробь в простейшем виде.",
    },
    "coins_lesson": 62,
    "coins_boss": 36,
}

LESSON_FRACTION_OPERATIONS = {
    "topic": "Действия с дробями",
    "context_theme": "detective",
    "explanation": (
        "Дроби с одинаковым знаменателем сравнивают по числителю: больше та дробь, у которой "
        "числитель больше. Дроби с одинаковыми знаменателями складывают и вычитают, складывая или "
        "вычитая числители и оставляя знаменатель без изменений; если результат — неправильная "
        "дробь, из неё выделяют целую часть. Со смешанными числами при сложении и вычитании "
        "действуют так же: целые части складывают (вычитают) отдельно от дробных, а если дробная "
        "часть при сложении становится неправильной дробью, из неё выделяют целую часть и "
        "добавляют её к сумме целых. Чтобы умножить дробь на натуральное число, умножают числитель "
        "на это число, а знаменатель оставляют прежним. Чтобы разделить дробь или смешанное число "
        "на дробь, делимое переводят в неправильную дробь и умножают на дробь, обратную делителю "
        "(у которой числитель и знаменатель делителя меняют местами)."
    ),
    "explanation_game": (
        "В ящике 2/3 — старый пульверизатор с проявителем для тайных надписей и два мерных "
        "сосуда: в одном 2/4 объёма, в другом 3/4. Раз 3/4 больше, чем 2/4 (у обеих дробей "
        "знаменатель одинаковый — 4, а значит сравнивают только числители, и 3 больше 2), для "
        "смеси берут именно его. В третьем сосуде уже отмерено 1 целая 2/4 проявителя — смешанное "
        "число, — и его сливают вместе с содержимым второго сосуда: целые части складывают "
        "отдельно (1 и 0), а дробные — по числителям при одинаковом знаменателе (2/4 + 3/4 = 5/4), "
        "и поскольку 5/4 — уже больше целого, из неё выделяют целую часть (5/4 = 1 целая 1/4) и "
        "добавляют её к сумме целых: получается 2 целых 1/4 литра готового проявителя. Рычаг "
        "пульверизатора выпускает жидкость дозами по 3/4 литра, а число доз находят делением: "
        "2 целых 1/4 сначала переводят в неправильную дробь (2 целых 1/4 = 9/4), а деление на "
        "дробь заменяют умножением на обратную ей: 9/4 ÷ 3/4 = 9/4 × 4/3 = 36/12 = 3 — ровно три "
        "нажатия. Проверка через умножение подтверждает: 3 дозы по 3/4 литра — это 3 × 3/4 = 9/4 = "
        "2 целых 1/4 литра, всё сходится. После третьего нажатия на обороте старой афиши, "
        "прикреплённой к стене бокса, медленно проступают координаты следующего места."
    ),
    "questions": [
        {
            "text": "Какая из дробей больше: 7/9 или 5/9?",
            "options": ["7/9", "5/9", "Они равны", "Сравнить нельзя"],
            "correct": 0,
            "hint": "У дробей одинаковый знаменатель — сравни числители.",
            "explanation": "При одинаковом знаменателе больше та дробь, у которой числитель больше: 7 > 5, значит 7/9 больше."
        },
        {
            "text": "Вычисли: 3/8 + 4/8.",
            "options": ["7/8", "7/16", "1/8", "12/8"],
            "correct": 0,
            "hint": "Знаменатели одинаковые — сложи только числители.",
            "explanation": "3/8 + 4/8 = (3+4)/8 = 7/8."
        },
        {
            "text": "Вычисли: 2 целых 3/7 + 1 целая 5/7.",
            "options": ["4 целых 1/7", "3 целых 8/7", "3 целых 1/7", "4 целых 8/7"],
            "correct": 0,
            "hint": "Сложи отдельно целые части и отдельно дробные, потом проверь, не получилась ли неправильная дробь.",
            "explanation": "Целые: 2+1=3. Дробные: 3/7+5/7=8/7=1 целая 1/7. Итого: 3+1 целых и 1/7 = 4 целых 1/7."
        },
        {
            "text": "Вычисли: 5/9 × 3. Ответ дай как обычную дробь.",
            "options": ["15/9", "5/27", "8/9", "15/3"],
            "correct": 0,
            "hint": "Умножь числитель на 3, знаменатель оставь без изменений.",
            "explanation": "5/9 × 3 = (5×3)/9 = 15/9."
        },
        {
            "text": "Плитку шоколада, от которой осталось 3/5, разделили поровну между 2 детьми. Какая часть целой плитки достанется каждому?",
            "options": ["3/10", "3/5", "6/5", "3/2"],
            "correct": 0,
            "hint": "Раздели дробь 3/5 на натуральное число 2 — умножь знаменатель на это число.",
            "explanation": "3/5 ÷ 2 = 3/(5×2) = 3/10."
        }
    ],
    "boss_task": {
        "answer": "4 полные дозы, останется 1/5 литра",
        "text": (
            "Пока проявляются координаты, в бардачке ты находишь запасной пузырёк реагента: всего "
            "в нём 1 целая 4/5 литра, а распылитель делает только целые дозы по 2/5 литра. Сколько "
            "полных доз получится и сколько реагента останется?"
        ),
        "solution": (
            "Ответ: 4 полные дозы, останется 1/5 литра. Переведи 1 целую 4/5 в неправильную дробь: "
            "9/5. Раздели на размер дозы: 9/5 ÷ 2/5 = 9/5 × 5/2 = 9/2 = 4,5, значит получится 4 "
            "полные дозы. Они расходуют 4 × 2/5 = 8/5, а остаток равен 9/5 − 8/5 = 1/5 литра."
        ),
        "hint1": "Смешанное число 1 целая 4/5 переведи в неправильную дробь.",
        "hint2": "Раздели количество реагента на размер одной дозы; целая часть результата — число полных доз, а остаток покажет, сколько реагента не израсходовано.",
    },
    "coins_lesson": 68,
    "coins_boss": 42,
}

LESSON_FRACTION_PROBLEMS = {
    "topic": "Задачи на дроби",
    "context_theme": "detective",
    "explanation": (
        "Чтобы найти часть числа, число умножают на дробь: например, чтобы найти 2/5 от 40, "
        "вычисляют 40 × 2/5 = 16. Чтобы найти число по известной его части, известную величину "
        "делят на дробь: если 2/5 числа равны 16, то само число равно 16 ÷ 2/5 = 40. Чтобы найти, "
        "какую часть одно число составляет от другого (дробное отношение двух чисел), первое "
        "число делят на второе и записывают результат в виде дроби, сокращая её при возможности."
    ),
    "explanation_game": (
        "По координатам, проступившим на афише, ты добираешься до дощатого сарая под мостом за "
        "товарной станцией — там, под старым брезентом, лежит потрёпанная бухгалтерская книга, "
        "исписанная тем же почерком, что и весь блокнот. Одна из последних строк гласит: «Тень "
        "получил 2/5 общей суммы — 840 монет», без итога. Чтобы найти общую сумму по известной её "
        "части, известную величину делят на дробь: 840 ÷ 2/5 = 840 × 5/2 = 2100 монет — вот сколько "
        "всего было награблено в этом деле. Значит, Эхо, судя по записи чуть ниже «остальное — "
        "Эхо», получил оставшуюся часть: 2100 − 840 = 1260 монет. Чтобы понять, в какой пропорции "
        "делили добычу, находят дробное отношение двух чисел — долю Тени к доле Эха: 840 к 1260, "
        "что при сокращении на общий делитель 420 даёт 2 к 3. Это последняя запись в книге про "
        "раздел «Обыкновенные дроби» — дальше страницы книги переходят к чертежам: планам этажей, "
        "углам и периметрам, — судя по всему, следующее дело ждёт уже не в цифрах, а в геометрии "
        "здания, которое Тень и Эхо готовили под что-то более крупное."
    ),
    "questions": [
        {
            "text": "Найди 3/4 от числа 60.",
            "options": ["45", "80", "15", "40"],
            "correct": 0,
            "hint": "Умножь число на дробь: 60 × 3/4.",
            "explanation": "60 × 3/4 = 180/4 = 45."
        },
        {
            "text": "5/8 числа равны 45. Найди само число.",
            "options": ["72", "56", "225", "36"],
            "correct": 0,
            "hint": "Раздели известную часть на дробь: 45 ÷ 5/8.",
            "explanation": "45 ÷ 5/8 = 45 × 8/5 = 360/5 = 72."
        },
        {
            "text": "Какую часть число 12 составляет от числа 30?",
            "options": ["2/5", "5/2", "12/30 без сокращения — так и оставляют", "3/5"],
            "correct": 0,
            "hint": "Раздели первое число на второе и запиши как дробь, сократив её.",
            "explanation": "12/30 = (12÷6)/(30÷6) = 2/5."
        },
        {
            "text": "В классе 24 ученика, и 2/3 из них ходят в шахматный кружок. Сколько это учеников?",
            "options": ["16", "12", "8", "18"],
            "correct": 0,
            "hint": "Умножь общее число учеников на дробь 2/3.",
            "explanation": "24 × 2/3 = 48/3 = 16."
        },
        {
            "text": "3/7 некоторой суммы денег равны 210 рублям. Сколько рублей составляет вся сумма?",
            "options": ["490", "70", "630", "300"],
            "correct": 0,
            "hint": "Раздели известную часть суммы на дробь 3/7.",
            "explanation": "210 ÷ 3/7 = 210 × 7/3 = 1470/3 = 490."
        }
    ],
    "boss_task": {
        "answer": "по 700 монет каждому",
        "text": (
            "Последняя, самая мятая страница книги описывает другой случай: общая добыча "
            "составила 2700 монет, Тень получил 2/9 этой суммы, а остальное поделили поровну между "
            "тремя другими сообщниками. Сколько монет получил каждый из этих троих?"
        ),
        "solution": (
            "Ответ: по 700 монет каждому. Доля Тени: 2700 × 2/9 = 5400/9 = 600 монет. Осталось "
            "2700 − 600 = 2100 монет, поделенных на троих: 2100 ÷ 3 = 700 монет каждому."
        ),
        "hint1": "Сначала найди долю Тени — умножь общую сумму 2700 на дробь 2/9.",
        "hint2": "Вычти долю Тени из общей суммы и раздели остаток на троих сообщников.",
    },
    "coins_lesson": 65,
    "coins_boss": 40,
}

LESSON_CONTROL_FRACTIONS = {
    "topic": "Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Это итоговая проверка по всем темам раздела «Обыкновенные дроби»: понятие дроби "
        "(числитель и знаменатель), виды дробей (правильные, неправильные, смешанные числа), "
        "основное свойство дроби (сокращение и приведение к общему знаменателю), действия с "
        "дробями (сравнение, сложение, вычитание, умножение и деление) и задачи на дроби "
        "(нахождение части от числа и числа по его части). Каждое задание проверяет отдельное "
        "умение из пяти пройденных уроков раздела."
    ),
    "explanation_game": (
        "Прежде чем перевернуть последнюю страницу гроссбуха в поисках того, что скрывается на "
        "самом её обороте, инспектор откладывает книгу в сторону. «Слишком много цифр у Тени и "
        "Эха завязано именно на дробях, — говорит он, — не хочу, чтобы мы неправильно поняли "
        "улику из-за одной ошибки в вычислениях». Он устраивает тебе полную проверку по всему "
        "разделу: отличить числитель от знаменателя, определить вид дроби, сократить её и "
        "привести к общему знаменателю, сравнить, сложить и перемножить дроби, а под конец — "
        "найти часть числа и число по его части, как в самом последнем деле про раздел добычи. "
        "Только когда все ответы сходятся, инспектор наконец кивает и возвращает тебе книгу — "
        "можно переворачивать последнюю страницу."
    ),
    "questions": [
        {
            "text": "В дроби 5/8 число 8 называется…",
            "options": ["Знаменатель", "Числитель", "Целая часть", "Остаток"],
            "correct": 0,
            "hint": "Это число под чертой дроби.",
            "explanation": "Число под чертой дроби называется знаменателем — оно показывает, на сколько частей разделили целое."
        },
        {
            "text": "Что показывает числитель дроби?",
            "options": [
                "Сколько частей целого взято",
                "На сколько частей разделили целое",
                "Целую часть смешанного числа",
                "Общий знаменатель"
            ],
            "correct": 0,
            "hint": "Это число над чертой дроби.",
            "explanation": "Числитель (число над чертой) показывает, сколько равных частей целого взято."
        },
        {
            "text": "Дробь 9/4 является…",
            "options": ["Неправильной", "Правильной", "Целым числом", "Несократимой единицей"],
            "correct": 0,
            "hint": "Сравни числитель со знаменателем.",
            "explanation": "У дроби 9/4 числитель (9) больше знаменателя (4), значит она неправильная."
        },
        {
            "text": "Переведи неправильную дробь 23/6 в смешанное число.",
            "options": ["3 целых 5/6", "4 целых 1/6", "3 целых 1/6", "2 целых 5/6"],
            "correct": 0,
            "hint": "Раздели числитель на знаменатель с остатком: частное — целая часть, остаток — числитель дробной части.",
            "explanation": "23 ÷ 6 = 3 (остаток 5), значит 23/6 = 3 целых 5/6."
        },
        {
            "text": "Сократи дробь 18/24.",
            "options": ["3/4", "9/12", "2/3", "6/8"],
            "correct": 0,
            "hint": "Раздели числитель и знаменатель на их общий делитель 6.",
            "explanation": "18÷6=3, 24÷6=4, значит 18/24 = 3/4."
        },
        {
            "text": "Сравни дроби 3/5 и 5/8, приведя их к общему знаменателю 40.",
            "options": ["5/8 больше, чем 3/5", "3/5 больше, чем 5/8", "Дроби равны", "Сравнить нельзя"],
            "correct": 0,
            "hint": "3/5 = 24/40, а 5/8 = 25/40 — сравни числители.",
            "explanation": "3/5 = 24/40, 5/8 = 25/40. Так как 25 больше 24, дробь 5/8 больше, чем 3/5."
        },
        {
            "text": "Вычисли: 2 целых 3/7 + 1 целая 5/7.",
            "options": ["4 целых 1/7", "3 целых 8/7", "3 целых 1/7", "4 целых 8/7"],
            "correct": 0,
            "hint": "Сложи целые части отдельно, дробные — отдельно, а затем выдели новую целую часть, если дробная часть окажется неправильной.",
            "explanation": "2+1=3 (целые части), 3/7+5/7=8/7=1 целая 1/7. Итого: 3 + 1 целая 1/7 = 4 целых 1/7."
        },
        {
            "text": "Вычисли: 2/3 × 3/5.",
            "options": ["2/5", "6/15", "5/8", "1/2"],
            "correct": 0,
            "hint": "Перемножь числители между собой и знаменатели между собой, затем сократи результат.",
            "explanation": "2/3 × 3/5 = (2×3)/(3×5) = 6/15 = 2/5 (после сокращения на 3)."
        },
        {
            "text": "Найди 3/5 от числа 45.",
            "options": ["27", "15", "9", "35"],
            "correct": 0,
            "hint": "Умножь число на дробь: 45 × 3/5.",
            "explanation": "45 × 3/5 = 135/5 = 27."
        }
    ],
    "boss_task": {
        "answer": "900",
        "text": (
            "Опись в гроссбухе говорит: общая сумма похищенного за весь раздел «Обыкновенные "
            "дроби» составила 4500 монет. Тень получил 2/5 этой суммы, а Эхо — 1/3 от того, что "
            "осталось после доли Тени. Сколько монет получил Эхо?"
        ),
        "solution": (
            "Ответ: 900 монет. Доля Тени: 4500 × 2/5 = 1800 монет. Остаток: 4500 − 1800 = 2700 "
            "монет. Доля Эха: 2700 × 1/3 = 900 монет."
        ),
        "hint1": "Сначала найди долю Тени — 2/5 от 4500 монет.",
        "hint2": "Вычти долю Тени из общей суммы, а затем возьми 1/3 от остатка — это доля Эха.",
    },
    "coins_lesson": 80,
    "coins_boss": 50,
}

SECTION_INTRO_GEOMETRY = (
    "Ты уже умеешь работать с числами, дробями и уравнениями. Но как быть, если нужно не просто "
    "посчитать, а понять форму, размер или расположение предметов в пространстве — например, "
    "начертить план комнаты или узнать, сколько краски нужно на стену?\n\n"
    "Что это такое: геометрия изучает фигуры — точки, прямые, отрезки, углы, многоугольники — и "
    "величины, которые их описывают: длину, площадь и объём. У каждой фигуры есть свои свойства и "
    "формулы для вычисления этих величин.\n\n"
    "Почему без этого не обойтись: любой чертёж, план здания, карта участка или упаковка товара "
    "построены на геометрических правилах — без них невозможно ни спроектировать дом, ни "
    "рассчитать, сколько плитки купить на пол.\n\n"
    "Зачем это тебе: с геометрией ты сможешь прочитать план квартиры, вычислить, поместится ли "
    "шкаф в комнату, посчитать площадь огорода или объём коробки для переезда — эти навыки "
    "пригождаются далеко за пределами школьных задач."
)

LESSON_GEOMETRY_BASICS = {
    "topic": "Основные объекты",
    "context_theme": "detective",
    "explanation": (
        "Точка — простейший геометрический объект: у неё нет размеров, только положение. Через "
        "одну точку можно провести сколько угодно прямых, а через две различные точки — ровно "
        "одну прямую. Прямая бесконечна в обе стороны и не имеет ни начала, ни конца. Луч — часть "
        "прямой, у которой есть начало (одна точка), но нет конца — он бесконечен только в одну "
        "сторону. Отрезок — часть прямой, ограниченная двумя точками (концами отрезка), поэтому у "
        "него есть конечная длина. Плоскость — ровная поверхность, бесконечная во все стороны, на "
        "которой лежат все эти объекты."
    ),
    "explanation_game": (
        "В самом конце бухгалтерской книги, под последней записью про Тень и Эхо, ты замечаешь "
        "плотный сложенный лист — вклеенный чертёж какого-то здания, без единой подписи, что это "
        "за место. На листе пунктиром нанесены линии, в нескольких местах поставлены жирные точки, "
        "а из одной точки торчит стрелка со стороны. Чтобы вообще читать такие чертежи, нужно "
        "различать их язык: точка — просто метка без размера, прямая — линия без начала и конца в "
        "обе стороны, луч — линия со стрелкой, у которой есть начало, но нет конца, отрезок — "
        "участок между двумя точками с точной длиной, а сам лист чертежа — это плоскость, на "
        "которой всё это нарисовано. На одной из стен чердака (судя по почерку — той самой, что "
        "изображена на чертеже) действительно находишь пять одинаковых зарубок в ряд. Похоже, "
        "именно они отмечают тайники, которые нужно сосчитать и связать между собой."
    ),
    "questions": [
        {
            "text": "Чем отрезок отличается от прямой?",
            "options": [
                "У отрезка есть два конца и конечная длина, а прямая бесконечна в обе стороны",
                "Отрезок толще прямой",
                "Отрезок и прямая — это одно и то же",
                "У прямой есть начало, а у отрезка нет"
            ],
            "correct": 0,
            "hint": "Подумай, можно ли измерить длину прямой линейкой.",
            "explanation": "Отрезок ограничен двумя точками и имеет конечную длину, а прямую нельзя измерить целиком — она бесконечна в обе стороны."
        },
        {
            "text": "Сколько прямых можно провести через две различные точки?",
            "options": ["Ровно одну", "Ни одной", "Ровно две", "Бесконечно много"],
            "correct": 0,
            "hint": "Попробуй представить: если точки заданы, куда ещё может отклониться линия между ними?",
            "explanation": "Через две различные точки проходит ровно одна прямая — иначе точки не были бы полностью определены."
        },
        {
            "text": "Чем луч отличается от отрезка?",
            "options": [
                "У луча есть только одно начало, а конца нет — он бесконечен в одну сторону",
                "Луч всегда короче отрезка",
                "У луча два конца, как у отрезка",
                "Луч — это то же самое, что прямая"
            ],
            "correct": 0,
            "hint": "Посмотри на стрелку, которой обозначают луч на чертеже.",
            "explanation": "Луч имеет начало (одну точку), но не имеет конца — он продолжается бесконечно только в одну сторону, в отличие от отрезка с двумя концами."
        },
        {
            "text": "Какой объект не имеет ни длины, ни ширины — только положение?",
            "options": ["Точка", "Отрезок", "Луч", "Плоскость"],
            "correct": 0,
            "hint": "Это самый простой из всех объектов на чертеже.",
            "explanation": "Точка не имеет размеров — у неё есть только положение на чертеже."
        },
        {
            "text": "Сам лист чертежа, на котором нарисованы все точки и линии, лучше всего представляет собой…",
            "options": ["Плоскость", "Отрезок", "Луч", "Угол"],
            "correct": 0,
            "hint": "Это ровная поверхность, бесконечная во все стороны, на которой размещаются остальные объекты.",
            "explanation": "Плоскость — это ровная бесконечная поверхность, на которой лежат точки, прямые, лучи и отрезки."
        }
    ],
    "boss_task": {
        "answer": "10",
        "text": (
            "На стене чердака в ряд на одной прямой отмечены пять зарубок-тайников: А, Б, В, Г, Д. "
            "Сколько всего различных отрезков можно провести между этими точками, если брать их "
            "по две?"
        ),
        "solution": (
            "Ответ: 10 отрезков. От каждой из 5 точек можно провести отрезок к 4 другим точкам, "
            "всего получится 5×4=20 отрезков, но каждый отрезок при этом посчитан дважды (отрезок "
            "от А до Б — то же самое, что отрезок от Б до А), поэтому итоговое число делят пополам: "
            "20÷2=10."
        ),
        "hint1": "Отрезок задаётся двумя точками — посчитай, сколько есть способов выбрать 2 точки из 5.",
        "hint2": "От каждой точки идёт отрезок к 4 остальным (5×4=20), но каждый отрезок при этом посчитан дважды — раздели результат на 2.",
    },
    "coins_lesson": 45,
    "coins_boss": 26,
}

LESSON_GEOMETRY_MEASURE = {
    "topic": "Измерения",
    "context_theme": "detective",
    "explanation": (
        "Чтобы измерить длину отрезка, линейку прикладывают так, чтобы её нулевая отметка "
        "совпала с одним концом отрезка, и смотрят, какое число совпадает со вторым концом — это "
        "и есть длина в выбранных единицах. Основные единицы длины: миллиметр (мм), сантиметр "
        "(см), дециметр (дм), метр (м) и километр (км). Соседние единицы связаны соотношениями: "
        "1 см = 10 мм, 1 дм = 10 см, 1 м = 10 дм = 100 см, 1 км = 1000 м. При измерении реальных "
        "объектов по чертежу используют масштаб — отношение длины на чертеже к настоящей длине: "
        "например, масштаб 1:100 означает, что 1 см на чертеже соответствует 100 см (1 м) в "
        "реальности."
    ),
    "explanation_game": (
        "В углу чертежа находится маленькая линейка-шкала с подписью «1:100» — масштаб. Один из "
        "отрезков на плане, ведущий от лестницы к дальней стене, размечен, но длина рядом не "
        "подписана — только пометка карандашом «здесь». Ты берёшь линейку и измеряешь этот отрезок "
        "прямо на бумаге: получается 8,4 см. Раз масштаб 1:100, каждый сантиметр на чертеже "
        "соответствует 100 см в реальности, значит настоящая длина этого участка — 8,4×100=840 см, "
        "то есть 8 метров 40 сантиметров. Отмерив это расстояние вдоль настоящей стены чердака от "
        "лестницы, ты нащупываешь едва заметную зарубку — ровно на отметке 840 см от пола до неё "
        "было бы неудобно, но по горизонтали, вдоль стены, метка сходится идеально. Это явно не "
        "случайность: кто-то специально подгонял чертёж под реальные размеры."
    ),
    "questions": [
        {
            "text": "Переведи 3 м 5 см в сантиметры.",
            "options": ["305 см", "35 см", "350 см", "3005 см"],
            "correct": 0,
            "hint": "1 м = 100 см, добавь оставшиеся сантиметры отдельно.",
            "explanation": "3 м = 300 см, плюс ещё 5 см — итого 305 см."
        },
        {
            "text": "Масштаб чертежа 1:50. Длина коридора на чертеже — 6 см. Какова его настоящая длина?",
            "options": ["300 см (3 м)", "56 см", "50 см", "6 м"],
            "correct": 0,
            "hint": "Умножь длину на чертеже на коэффициент масштаба.",
            "explanation": "6 см × 50 = 300 см = 3 м."
        },
        {
            "text": "Какой единицей удобнее всего измерить длину карандаша?",
            "options": ["Сантиметрами", "Километрами", "Метрами", "Дециметрами"],
            "correct": 0,
            "hint": "Подумай о реальном размере карандаша.",
            "explanation": "Карандаш обычно около 15-18 см, поэтому сантиметры — самая удобная единица."
        },
        {
            "text": "Сколько метров в 4700 мм?",
            "options": ["4 м 700 мм (4,7 м)", "47 м", "470 м", "0,47 м"],
            "correct": 0,
            "hint": "1 м = 1000 мм.",
            "explanation": "4700 мм = 4000 мм + 700 мм = 4 м + 700 мм = 4,7 м."
        },
        {
            "text": "Что больше: 2 м 5 см или 205 см?",
            "options": ["Они равны", "2 м 5 см больше", "205 см больше", "Сравнить нельзя"],
            "correct": 0,
            "hint": "Переведи обе величины в одинаковые единицы, прежде чем сравнивать.",
            "explanation": "2 м 5 см = 200 см + 5 см = 205 см — это то же самое число, просто записанное по-другому."
        }
    ],
    "boss_task": {
        "answer": "840",
        "text": (
            "На чертеже отмечен отрезок между лестницей и дальней стеной длиной 8,4 см, масштаб "
            "чертежа — 1:100. Какова настоящая длина этого участка в сантиметрах?"
        ),
        "solution": (
            "Ответ: 840 см (8 м 40 см). Масштаб 1:100 значит, что 1 см на чертеже соответствует "
            "100 см в реальности, поэтому 8,4 см × 100 = 840 см."
        ),
        "hint1": "Масштаб 1:100 значит, что каждый сантиметр на чертеже соответствует 100 см в реальности.",
        "hint2": "Умножь длину на чертеже (8,4 см) на коэффициент масштаба (100).",
    },
    "coins_lesson": 47,
    "coins_boss": 27,
}

LESSON_GEOMETRY_POLYGON = {
    "topic": "Ломаная и многоугольники",
    "context_theme": "detective",
    "explanation": (
        "Ломаная — это фигура из нескольких отрезков, соединённых по очереди так, что конец "
        "одного отрезка совпадает с началом следующего; отрезки называются звеньями ломаной, а "
        "точки их соединения — вершинами. Если у ломаной последняя вершина совпадает с первой "
        "(ломаная замкнута) и звенья при этом не пересекаются, получается многоугольник. У "
        "многоугольника стороны — это звенья ломаной, а периметр — это сумма длин всех его сторон."
    ),
    "explanation_game": (
        "За отметкой 840 см в стене прячется низкая дверца. За ней — не прямой коридор, а "
        "настоящая ломаная: путь резко сворачивает пять раз, прежде чем вывести тебя в комнату "
        "странной формы — пятиугольную, со стенами разной длины. Чтобы понять, сколько всего "
        "пришлось пройти, звенья ломаной коридора нужно сложить: 12 м, 9 м, 15 м, 7 м и 11 м, что "
        "в сумме даёт 12+9+15+7+11=54 метра. Сама комната-пятиугольник, в которую ты попадаешь, "
        "тоже размечена на чертеже: её пять сторон — 6 м, 8 м, 5 м, 9 м и 7 м, а вдоль плинтуса "
        "кто-то прежде явно натягивал верёвку или провод ровно по периметру — судя по помятым "
        "гвоздикам в стенах. Периметр комнаты равен 6+8+5+9+7=35 метров, заметно меньше, чем весь "
        "путь по коридору."
    ),
    "questions": [
        {
            "text": "Как называются точки, где соединяются звенья ломаной?",
            "options": ["Вершины", "Центры", "Основания", "Диагонали"],
            "correct": 0,
            "hint": "То же слово используют и для многоугольников.",
            "explanation": "Точки соединения звеньев ломаной называются вершинами."
        },
        {
            "text": "Когда ломаная называется замкнутой?",
            "options": [
                "Когда её последняя вершина совпадает с первой",
                "Когда у неё больше трёх звеньев",
                "Когда все звенья одинаковой длины",
                "Когда она нарисована по прямой линии"
            ],
            "correct": 0,
            "hint": "Подумай, что нужно, чтобы фигура «замкнулась» и превратилась в многоугольник.",
            "explanation": "Ломаная замкнута, если её конец совпадает с началом — тогда, если звенья не пересекаются, получается многоугольник."
        },
        {
            "text": "У многоугольника с 6 сторонами сколько вершин?",
            "options": ["6", "5", "12", "3"],
            "correct": 0,
            "hint": "У многоугольника число вершин всегда равно числу сторон.",
            "explanation": "Число вершин многоугольника всегда равно числу его сторон — у шестиугольника 6 вершин."
        },
        {
            "text": "Стороны четырёхугольника равны 4 м, 6 м, 5 м и 7 м. Чему равен его периметр?",
            "options": ["22 м", "18 м", "24 м", "20 м"],
            "correct": 0,
            "hint": "Периметр — это сумма длин всех сторон.",
            "explanation": "4+6+5+7=22 м."
        },
        {
            "text": "Чем многоугольник отличается от обычной (не замкнутой) ломаной?",
            "options": [
                "Многоугольник замкнут, а его звенья не пересекаются",
                "У многоугольника меньше звеньев",
                "Многоугольник состоит только из прямых углов",
                "Это одно и то же"
            ],
            "correct": 0,
            "hint": "Вспомни определение из объяснения.",
            "explanation": "Многоугольник — это замкнутая ломаная, звенья которой не пересекаются между собой."
        }
    ],
    "boss_task": {
        "answer": "19",
        "text": (
            "Звенья ломаного коридора равны 12 м, 9 м, 15 м, 7 м и 11 м, а стороны "
            "комнаты-пятиугольника в конце пути равны 6 м, 8 м, 5 м, 9 м и 7 м. На сколько метров "
            "весь пройденный коридор длиннее периметра комнаты?"
        ),
        "solution": (
            "Ответ: 19 м. Длина коридора: 12+9+15+7+11=54 м. Периметр комнаты: 6+8+5+9+7=35 м. "
            "Разница: 54−35=19 м."
        ),
        "hint1": "Сначала сложи все звенья ломаной коридора отдельно.",
        "hint2": "Потом сложи все стороны пятиугольной комнаты и вычти это число из длины коридора.",
    },
    "coins_lesson": 50,
    "coins_boss": 29,
}

LESSON_GEOMETRY_ANGLES = {
    "topic": "Углы",
    "context_theme": "detective",
    "explanation": (
        "Угол — это фигура, образованная двумя лучами (сторонами угла), выходящими из одной "
        "точки (вершины угла). Углы измеряют в градусах с помощью транспортира: центр "
        "транспортира прикладывают к вершине угла, совмещают один луч с нулевой отметкой шкалы и "
        "смотрят, на какое деление указывает второй луч. По величине углы делятся на острые "
        "(меньше 90°), прямые (ровно 90°), тупые (больше 90°, но меньше 180°) и развёрнутые "
        "(ровно 180° — в этом случае стороны угла образуют прямую линию)."
    ),
    "explanation_game": (
        "В центре пятиугольной комнаты на полу нарисован круглый диск с делениями, как у "
        "транспортира — судя по всему, это часть механизма, открывающего следующий проход. Рядом "
        "на стене — записка вора: «встань стрелку так, чтобы оба угла вместе легли ровно вдоль "
        "стены». Ты понимаешь: два угла, о которых речь, вместе должны образовать развёрнутый "
        "угол — то есть их сумма обязана равняться 180°. Один из углов на диске уже зафиксирован "
        "намертво и равен 118°, а второй — тот, что нужно выставить стрелкой. Значит, "
        "180°−118°=62° — вот на сколько градусов нужно повернуть стрелку, чтобы диск с щелчком "
        "провернулся, открывая проход дальше."
    ),
    "questions": [
        {
            "text": "К какому виду относится угол в 47°?",
            "options": ["Острый", "Прямой", "Тупой", "Развёрнутый"],
            "correct": 0,
            "hint": "Острый угол меньше 90°.",
            "explanation": "47° меньше 90°, значит угол острый."
        },
        {
            "text": "Как называется угол, равный ровно 180°?",
            "options": ["Развёрнутый", "Прямой", "Острый", "Тупой"],
            "correct": 0,
            "hint": "При таком угле стороны образуют прямую линию.",
            "explanation": "Угол в 180° называется развёрнутым — его стороны лежат на одной прямой."
        },
        {
            "text": "Два угла вместе образуют развёрнутый угол. Один из них равен 65°. Чему равен второй?",
            "options": ["115°", "125°", "65°", "180°"],
            "correct": 0,
            "hint": "Сумма таких двух углов всегда равна 180°.",
            "explanation": "180°−65°=115°."
        },
        {
            "text": "Чему равен прямой угол?",
            "options": ["90°", "45°", "180°", "60°"],
            "correct": 0,
            "hint": "Это угол, который образуют, например, соседние стороны прямоугольника.",
            "explanation": "Прямой угол всегда равен ровно 90°."
        },
        {
            "text": "К какому виду относится угол в 133°?",
            "options": ["Тупой", "Острый", "Прямой", "Развёрнутый"],
            "correct": 0,
            "hint": "Тупой угол больше 90°, но меньше 180°.",
            "explanation": "133° больше 90° и меньше 180°, значит угол тупой."
        }
    ],
    "boss_task": {
        "answer": "62",
        "text": (
            "На диске-механизме два угла вместе образуют развёрнутый угол (лежат вдоль одной "
            "стены). Один из них зафиксирован и равен 118°. На сколько градусов нужно выставить "
            "второй угол стрелкой, чтобы механизм сработал?"
        ),
        "solution": (
            "Ответ: 62°. Два угла, образующие развёрнутый угол, в сумме дают 180°, значит второй "
            "угол равен 180°−118°=62°."
        ),
        "hint1": "Вспомни: если два угла вместе образуют развёрнутый угол (прямую), их сумма равна 180°.",
        "hint2": "Вычти известный угол (118°) из 180°.",
    },
    "coins_lesson": 52,
    "coins_boss": 30,
}

LESSON_GEOMETRY_LINES = {
    "topic": "Взаимное расположение прямых",
    "context_theme": "detective",
    "explanation": (
        "Две прямые на плоскости могут быть параллельными — если они лежат в одной плоскости и "
        "никогда не пересекаются, сколько бы их ни продолжали в обе стороны. Если же две прямые "
        "пересекаются и образуют в точке пересечения прямой угол (90°), их называют "
        "перпендикулярными. Остальные пересекающиеся прямые, угол между которыми не равен 90°, "
        "называют просто пересекающимися."
    ),
    "explanation_game": (
        "Диск проворачивается, открывая проход в соседнее помещение, и ты сверяешь его форму с "
        "чертежом: по плану все стены здесь должны быть либо параллельны противоположной стене, "
        "либо перпендикулярны соседней — обычная прямоугольная комната. Но, промерив углы у "
        "каждого угла помещения транспортиром, ты обнаруживаешь: одна стена пересекает соседнюю "
        "не под 90°, как остальные, а под 100°. На чертеже эта же стена отмечена странным "
        "росчерком — как будто её специально «подвинули» при перестройке. Отклонение от "
        "перпендикуляра составляет 100°−90°=10° — небольшая, но заметная щель за этой стеной "
        "вполне может скрывать тайник."
    ),
    "questions": [
        {
            "text": "Какие прямые называются параллельными?",
            "options": [
                "Те, что лежат в одной плоскости и никогда не пересекаются",
                "Те, что пересекаются под углом 90°",
                "Любые две прямые на чертеже",
                "Те, что имеют общую точку"
            ],
            "correct": 0,
            "hint": "Подумай о рельсах железной дороги.",
            "explanation": "Параллельные прямые лежат в одной плоскости и не пересекаются, сколько бы их ни продолжали."
        },
        {
            "text": "Какие прямые называются перпендикулярными?",
            "options": [
                "Те, что пересекаются под углом 90°",
                "Те, что никогда не пересекаются",
                "Те, что пересекаются под любым углом",
                "Те, что равны по длине"
            ],
            "correct": 0,
            "hint": "Вспомни, какой угол образуют, например, стороны листа бумаги.",
            "explanation": "Перпендикулярные прямые пересекаются и образуют в точке пересечения прямой угол — 90°."
        },
        {
            "text": "Две прямые пересекаются под углом 90°. Как их назвать?",
            "options": ["Перпендикулярные", "Параллельные", "Равные", "Ломаные"],
            "correct": 0,
            "hint": "Название образовано от слова «перпендикуляр».",
            "explanation": "Прямые, пересекающиеся под углом 90°, называются перпендикулярными."
        },
        {
            "text": "Две стены пересекаются под углом 70°. Как их правильно описать?",
            "options": [
                "Пересекающиеся, но не перпендикулярные",
                "Параллельные",
                "Перпендикулярные",
                "Такого не бывает"
            ],
            "correct": 0,
            "hint": "Угол 70° не равен ни 0° (параллельность), ни 90° (перпендикулярность).",
            "explanation": "Раз угол между стенами не равен 90°, они пересекаются, но не являются перпендикулярными."
        },
        {
            "text": "В прямоугольной комнате противоположные стены обычно… а соседние — …",
            "options": [
                "параллельны; перпендикулярны",
                "перпендикулярны; параллельны",
                "параллельны; параллельны",
                "перпендикулярны; перпендикулярны"
            ],
            "correct": 0,
            "hint": "Вспомни форму обычного прямоугольника.",
            "explanation": "В прямоугольнике противоположные стороны параллельны друг другу, а соседние — перпендикулярны."
        }
    ],
    "boss_task": {
        "answer": "10",
        "text": (
            "Во всей комнате стены перпендикулярны соседним и параллельны противоположным — кроме "
            "одной: она пересекает соседнюю стену под углом 100° вместо положенных 90°. На сколько "
            "градусов эта стена отклоняется от перпендикуляра?"
        ),
        "solution": (
            "Ответ: 10°. Если бы стена была перпендикулярна соседней, угол между ними составлял "
            "бы 90°. По факту угол равен 100°, значит отклонение равно 100°−90°=10°."
        ),
        "hint1": "Сравни данный угол (100°) с углом, который должен быть у перпендикулярных стен (90°).",
        "hint2": "Найди разницу между этими двумя углами.",
    },
    "coins_lesson": 54,
    "coins_boss": 31,
}

LESSON_GEOMETRY_AREA = {
    "topic": "Площадь",
    "context_theme": "detective",
    "explanation": (
        "Площадь прямоугольника находят, перемножив длины двух его смежных сторон: S = a × b. "
        "Площадь квадрата со стороной a равна S = a × a = a². Площадь прямоугольного треугольника "
        "равна половине произведения его катетов — сторон, образующих прямой угол: S = (a × b) ÷ 2, "
        "потому что такой треугольник составляет ровно половину прямоугольника со сторонами, "
        "равными его катетам. Для измерения небольших площадей используют квадратные метры (м²) и "
        "квадратные сантиметры (см²), а для больших участков земли — ар (100 м², то есть квадрат "
        "10×10 м) и гектар (100 аров, то есть 10 000 м²)."
    ),
    "explanation_game": (
        "За отклонившейся стеной находится треугольный закуток — раньше здесь, судя по следу "
        "копоти, стояла печная труба, которую потом убрали, срезав угол помещения. Само помещение "
        "по чертежу представляет собой прямоугольник 6 м на 4 м, из которого в одном углу вырезан "
        "прямоугольный треугольник с катетами 3 м и 2 м — как раз там, где раньше была труба. "
        "Чтобы понять, поместится ли внутрь тайник нужного размера, сначала считаешь площадь всего "
        "прямоугольника: 6×4=24 м². Потом — площадь вырезанного треугольника: (3×2)÷2=3 м². "
        "Свободная площадь помещения равна 24−3=21 м² — вполне достаточно, чтобы здесь можно было "
        "что-то спрятать."
    ),
    "questions": [
        {
            "text": "Найди площадь прямоугольника со сторонами 5 м и 3 м.",
            "options": ["15 м²", "8 м²", "16 м²", "10 м²"],
            "correct": 0,
            "hint": "Площадь прямоугольника — произведение двух смежных сторон.",
            "explanation": "5×3=15 м²."
        },
        {
            "text": "Найди площадь квадрата со стороной 7 см.",
            "options": ["49 см²", "14 см²", "28 см²", "21 см²"],
            "correct": 0,
            "hint": "Площадь квадрата — сторона в квадрате.",
            "explanation": "7×7=49 см²."
        },
        {
            "text": "Катеты прямоугольного треугольника равны 6 м и 4 м. Чему равна его площадь?",
            "options": ["12 м²", "24 м²", "10 м²", "20 м²"],
            "correct": 0,
            "hint": "Площадь прямоугольного треугольника — половина произведения катетов.",
            "explanation": "(6×4)÷2=24÷2=12 м²."
        },
        {
            "text": "Сколько квадратных метров в 3 арах?",
            "options": ["300 м²", "3000 м²", "30 м²", "3 м²"],
            "correct": 0,
            "hint": "1 ар = 100 м².",
            "explanation": "3 ара × 100 м² = 300 м²."
        },
        {
            "text": "Сколько квадратных метров в 2 гектарах?",
            "options": ["20 000 м²", "2 000 м²", "200 м²", "200 000 м²"],
            "correct": 0,
            "hint": "1 гектар = 10 000 м².",
            "explanation": "2 гектара × 10 000 м² = 20 000 м²."
        }
    ],
    "boss_task": {
        "answer": "21",
        "text": (
            "Тайная комната имеет форму прямоугольника со сторонами 6 м и 4 м, но в одном углу от "
            "неё отрезан прямоугольный треугольник с катетами 3 м и 2 м — там раньше стояла печная "
            "труба. Какова площадь помещения, доступного под тайник, в квадратных метрах?"
        ),
        "solution": (
            "Ответ: 21 м². Площадь прямоугольника: 6×4=24 м². Площадь отрезанного треугольника: "
            "(3×2)÷2=3 м². Доступная площадь: 24−3=21 м²."
        ),
        "hint1": "Сначала найди площадь всего прямоугольника, как будто треугольного выреза нет.",
        "hint2": "Вычисли площадь отрезанного прямоугольного треугольника и вычти её из площади прямоугольника.",
    },
    "coins_lesson": 58,
    "coins_boss": 34,
}

LESSON_GEOMETRY_VOLUME = {
    "topic": "Объем",
    "context_theme": "detective",
    "explanation": (
        "Прямоугольный параллелепипед — объёмная фигура с шестью прямоугольными гранями (простой "
        "пример — коробка или кирпич); если известны его длина a, ширина b и высота c, объём "
        "находят по формуле V = a × b × c. Куб — частный случай параллелепипеда, у которого все "
        "рёбра равны между собой (a = b = c), поэтому его объём равен V = a³. Площадь полной "
        "поверхности параллелепипеда равна сумме площадей всех шести граней (у противоположных "
        "граней площади попарно равны). Объём измеряют в кубических единицах — кубических "
        "сантиметрах (см³), кубических дециметрах (дм³) и кубических метрах (м³); 1 дм³ "
        "(кубический дециметр) равен 1 литру."
    ),
    "explanation_game": (
        "В самом свободном от треугольного выреза углу комнаты, под половицей, находится сундук "
        "в форме прямоугольного параллелепипеда с рёбрами 60 см, 40 см и 30 см. Чтобы понять, "
        "сколько он может вместить, переводишь рёбра в дециметры (10 см = 1 дм): получается 6 дм, "
        "4 дм и 3 дм. Объём сундука равен 6×4×3=72 дм³, то есть 72 литра — вполне хватило бы на "
        "тысячи монет, о которых шла речь в бухгалтерской книге. Но когда ты откидываешь крышку, "
        "внутри пусто — только сложенный листок с аккуратной таблицей: столбцы дат, сумм и имён, "
        "явно вырванный из другой, более новой тетради. Похоже, вор с сообщниками вели точный учёт "
        "своей добычи — и чтобы разобраться в этих записях, придётся научиться читать не чертежи, "
        "а таблицы и диаграммы. Раздел «5. Геометрические фигуры и величины» пройден полностью "
        "(7/7) — а следующее дело явно ждёт в цифрах этой самой таблицы."
    ),
    "questions": [
        {
            "text": "Найди объём прямоугольного параллелепипеда с рёбрами 5 см, 3 см и 2 см.",
            "options": ["30 см³", "10 см³", "15 см³", "20 см³"],
            "correct": 0,
            "hint": "Объём параллелепипеда — произведение трёх его рёбер.",
            "explanation": "5×3×2=30 см³."
        },
        {
            "text": "Найди объём куба с ребром 4 см.",
            "options": ["64 см³", "16 см³", "12 см³", "48 см³"],
            "correct": 0,
            "hint": "Объём куба — ребро в кубе (a×a×a).",
            "explanation": "4×4×4=64 см³."
        },
        {
            "text": "Найди площадь полной поверхности куба с ребром 3 см.",
            "options": ["54 см²", "27 см²", "18 см²", "9 см²"],
            "correct": 0,
            "hint": "У куба 6 одинаковых граней, площадь одной грани — ребро в квадрате.",
            "explanation": "Площадь одной грани: 3×3=9 см². Всего граней 6, значит 9×6=54 см²."
        },
        {
            "text": "Сколько литров в 1 дм³?",
            "options": ["1 литр", "10 литров", "0,1 литра", "100 литров"],
            "correct": 0,
            "hint": "Это стандартное соотношение между кубическим дециметром и литром.",
            "explanation": "1 кубический дециметр (1 дм³) равен ровно 1 литру."
        },
        {
            "text": "Найди площадь полной поверхности прямоугольного параллелепипеда с рёбрами 5 см, 3 см и 2 см.",
            "options": ["62 см²", "31 см²", "30 см²", "60 см²"],
            "correct": 0,
            "hint": "Сложи площади трёх разных граней и удвой результат: 2×(ab+bc+ac).",
            "explanation": "2×(5×3 + 3×2 + 5×2) = 2×(15+6+10) = 2×31 = 62 см²."
        }
    ],
    "boss_task": {
        "answer": "72",
        "text": (
            "Сундук имеет форму прямоугольного параллелепипеда с рёбрами 60 см, 40 см и 30 см. "
            "Сколько кубических дециметров (литров) вмещает сундук?"
        ),
        "solution": (
            "Ответ: 72 дм³ (72 литра). Переведи рёбра в дециметры: 60 см=6 дм, 40 см=4 дм, "
            "30 см=3 дм. Объём равен 6×4×3=72 дм³."
        ),
        "hint1": "Переведи все три ребра сундука из сантиметров в дециметры (10 см = 1 дм).",
        "hint2": "Перемножь три ребра, выраженные в дециметрах, между собой.",
    },
    "coins_lesson": 63,
    "coins_boss": 38,
}

LESSON_CONTROL_GEOMETRY = {
    "topic": "Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Это итоговая проверка по всем темам раздела «Геометрические фигуры и величины»: "
        "основные объекты (точка, прямая, луч, отрезок, плоскость), измерения (единицы длины и "
        "масштаб), ломаная и многоугольники (вершины, звенья, периметр), углы (виды углов и их "
        "измерение), взаимное расположение прямых (параллельность и перпендикулярность), площадь "
        "(прямоугольника, квадрата, прямоугольного треугольника) и объём (параллелепипеда и "
        "куба). Каждое задание проверяет отдельное умение из семи пройденных уроков раздела."
    ),
    "explanation_game": (
        "Ты уже готов развернуть найденный в сундуке листок с таблицей, но инспектор останавливает "
        "тебя за руку. «Сначала как следует задокументируем находку — сундук, комнату, чертёж, — "
        "говорит он, — и я должен убедиться, что ты во всём этом как следует разобрался, прежде "
        "чем мы откроем новую улику». Он проверяет тебя по всему разделу: просит различить "
        "основные геометрические объекты, перевести единицы длины, посчитать периметр "
        "многоугольника, определить вид угла и найти второй угол в паре, отличить параллельные "
        "прямые от перпендикулярных, вычислить площадь и, наконец, объём. Только когда все ответы "
        "сходятся, инспектор кивает и разрешает наконец развернуть находку — и на листке "
        "действительно оказывается таблица с датами и суммами."
    ),
    "questions": [
        {
            "text": "Какой объект не имеет ни длины, ни ширины — только положение?",
            "options": ["Точка", "Отрезок", "Луч", "Плоскость"],
            "correct": 0,
            "hint": "Это самый простой из всех геометрических объектов.",
            "explanation": "Точка не имеет размеров — у неё есть только положение."
        },
        {
            "text": "Сколько прямых можно провести через две различные точки?",
            "options": ["Ровно одну", "Ни одной", "Ровно две", "Бесконечно много"],
            "correct": 0,
            "hint": "Точки полностью определяют прямую.",
            "explanation": "Через две различные точки проходит ровно одна прямая."
        },
        {
            "text": "Сколько сантиметров в 5 дм 3 см?",
            "options": ["53 см", "503 см", "5,3 см", "35 см"],
            "correct": 0,
            "hint": "1 дм = 10 см.",
            "explanation": "5 дм = 50 см, плюс ещё 3 см — итого 53 см."
        },
        {
            "text": "Масштаб чертежа 1:20. Отрезок на чертеже — 4 см. Какова его настоящая длина?",
            "options": ["80 см", "24 см", "16 см", "5 см"],
            "correct": 0,
            "hint": "Умножь длину на чертеже на коэффициент масштаба.",
            "explanation": "4 см × 20 = 80 см."
        },
        {
            "text": "Найди периметр треугольника со сторонами 6 м, 8 м и 10 м.",
            "options": ["24 м", "48 м", "18 м", "20 м"],
            "correct": 0,
            "hint": "Периметр — это сумма длин всех сторон.",
            "explanation": "6+8+10=24 м."
        },
        {
            "text": "Какой угол равен ровно 90°?",
            "options": ["Прямой", "Острый", "Тупой", "Развёрнутый"],
            "correct": 0,
            "hint": "Такой угол образуют, например, соседние стороны прямоугольника.",
            "explanation": "Угол, равный ровно 90°, называется прямым."
        },
        {
            "text": "Два угла вместе образуют развёрнутый угол. Один из них равен 73°. Чему равен второй?",
            "options": ["107°", "117°", "17°", "73°"],
            "correct": 0,
            "hint": "Сумма таких двух углов всегда равна 180°.",
            "explanation": "180°−73°=107°."
        },
        {
            "text": "Как называются прямые, которые пересекаются под углом 90°?",
            "options": ["Перпендикулярные", "Параллельные", "Ломаные", "Равные"],
            "correct": 0,
            "hint": "Название образовано от слова «перпендикуляр».",
            "explanation": "Прямые, пересекающиеся под углом 90°, называются перпендикулярными."
        },
        {
            "text": "Найди площадь прямоугольника со сторонами 9 м и 4 м.",
            "options": ["36 м²", "26 м²", "13 м²", "18 м²"],
            "correct": 0,
            "hint": "Площадь прямоугольника — произведение двух смежных сторон.",
            "explanation": "9×4=36 м²."
        },
        {
            "text": "Найди объём куба с ребром 5 см.",
            "options": ["125 см³", "25 см³", "15 см³", "10 см³"],
            "correct": 0,
            "hint": "Объём куба — ребро в кубе (a×a×a).",
            "explanation": "5×5×5=125 см³."
        }
    ],
    "boss_task": {
        "answer": "60",
        "text": (
            "Тайник в стене представляет собой прямоугольный параллелепипед с основанием — "
            "прямоугольником со сторонами 5 дм и 4 дм — и высотой 3 дм. Сначала найди площадь "
            "основания, а затем — объём тайника в кубических дециметрах (литрах)."
        ),
        "solution": (
            "Ответ: 60 дм³ (60 литров). Площадь основания: 5×4=20 дм². Объём: 20×3=60 дм³."
        ),
        "hint1": "Сначала найди площадь прямоугольного основания (произведение двух его сторон).",
        "hint2": "Умножь площадь основания на высоту, чтобы получить объём.",
    },
    "coins_lesson": 74,
    "coins_boss": 45,
}

SECTION_INTRO_DATA_ANALYSIS = (
    "Ты уже умеешь считать, решать уравнения, работать с дробями и разбираться в геометрических "
    "фигурах. Но что делать, когда данных много — не один пример, а десятки чисел, дат и имён, — "
    "и нужно увидеть в них закономерность, а не просто сложить всё подряд?\n\n"
    "Что это такое: анализ данных — это умение представлять числа в таблицах и столбчатых "
    "диаграммах, находить среднее арифметическое значение нескольких чисел, а ещё решать типовые "
    "текстовые задачи — на движение (навстречу друг другу, вдогонку, по течению и против течения "
    "реки) и на взвешивание и переливание.\n\n"
    "Почему без этого не обойтись: реальные данные — расписания, счета, результаты опросов — "
    "всегда приходят вперемешку, и без таблиц и диаграмм в них легко запутаться, а многие "
    "практические задачи (сколько времени в пути, сколько воды перелить, какой предмет тяжелее) "
    "решаются именно по известным типовым схемам.\n\n"
    "Зачем это тебе: этот раздел научит тебя видеть главное в ворохе чисел — ровно то, что нужно, "
    "чтобы закрыть последнее дело и понять, куда все эти месяцы вели следы вора и его учеников."
)

LESSON_DATA_TABLES = {
    "topic": "Работа с информацией",
    "context_theme": "detective",
    "explanation": (
        "Данные удобно представлять в таблице — сетке со строками и столбцами, где на "
        "пересечении строки и столбца записано конкретное значение. Столбчатая диаграмма "
        "показывает те же данные в виде столбиков разной высоты: чем выше столбик, тем больше "
        "значение, а высоту столбика читают по шкале на боковой оси. По таблице и диаграмме легко "
        "находить наибольшее и наименьшее значение, сравнивать величины между собой и находить их "
        "сумму."
    ),
    "explanation_game": (
        "Развернув найденный в сундуке листок, ты видишь аккуратную таблицу: пять дат, а рядом с "
        "каждой — сумма в монетах. Первые четыре строки помечены галочкой «выполнено»: 3 июня — "
        "800 монет, 10 июня — 700 монет, 17 июня — 1200 монет, 24 июня — 900 монет. Пятая строка, "
        "1 июля, галочки не имеет — вместо неё дата дважды подчёркнута красным, а сумма рядом "
        "заметно больше остальных — 1500 монет. Чтобы наглядно сравнить все пять сумм, ты "
        "перерисовываешь таблицу в виде столбчатой диаграммы: столбик за 1 июля оказывается выше "
        "всех остальных, даже не считая, что дело по нему ещё не «закрыто». Инспектор хмурится: "
        "если четыре предыдущих даты — это уже случившиеся кражи, то 1 июля — это то, что "
        "только предстоит, и оно крупнее любого из прошлых дел."
    ),
    "questions": [
        {
            "text": "На столбчатой диаграмме высота столбика показывает…",
            "options": [
                "Величину (значение) того показателя, который она обозначает",
                "Количество диаграмм на странице",
                "Цвет, которым закрашен показатель",
                "Время, когда была построена диаграмма"
            ],
            "correct": 0,
            "hint": "Чем выше столбик, тем больше то, что он показывает.",
            "explanation": "Высота столбика на диаграмме соответствует значению (величине) показателя — чем он больше, тем выше столбик."
        },
        {
            "text": (
                "В таблице записаны баллы учеников за три теста:\n"
                "         Тест 1  Тест 2  Тест 3\n"
                "Аня        7       8       9\n"
                "Боря       6       9       7\n"
                "Какой балл получил Боря за Тест 2?"
            ),
            "options": ["9", "6", "7", "8"],
            "correct": 0,
            "hint": "Найди строку «Боря» и столбец «Тест 2» — их пересечение и есть ответ.",
            "explanation": "На пересечении строки «Боря» и столбца «Тест 2» стоит число 9."
        },
        {
            "text": (
                "На диаграмме продаж мороженого по дням недели: понедельник — 12, вторник — 18, "
                "среда — 9, четверг — 15 порций. В какой день продали больше всего мороженого?"
            ),
            "options": ["Во вторник", "В понедельник", "В среду", "В четверг"],
            "correct": 0,
            "hint": "Найди самое большое число среди четырёх значений.",
            "explanation": "18 порций (вторник) — самое большое значение из четырёх."
        },
        {
            "text": "Найди сумму всех значений в таблице: 120, 95 и 150.",
            "options": ["365", "355", "375", "345"],
            "correct": 0,
            "hint": "Сложи все три числа по очереди.",
            "explanation": "120+95=215, 215+150=365."
        },
        {
            "text": (
                "На диаграмме показаны суммы четырёх уже совершённых краж: 800, 700, 1200 и 900 "
                "монет. Какова разница между самой большой и самой маленькой суммой?"
            ),
            "options": ["500", "400", "600", "300"],
            "correct": 0,
            "hint": "Вычти наименьшее значение из наибольшего.",
            "explanation": "Наибольшее значение — 1200, наименьшее — 700. Разница: 1200−700=500."
        }
    ],
    "boss_task": {
        "answer": "3600",
        "text": (
            "В таблице — суммы четырёх уже совершённых краж, каждая отмечена галочкой "
            "«выполнено»: 800, 700, 1200 и 900 монет. Чему равна их общая сумма?"
        ),
        "solution": (
            "Ответ: 3600 монет. Складываем все четыре отмеченные суммы: 800+700=1500, "
            "1500+1200=2700, 2700+900=3600."
        ),
        "hint1": "Сложи первые две суммы, потом прибавь третью, потом четвёртую — по порядку.",
        "hint2": "800+700=1500, затем 1500+1200=2700, затем 2700+900=3600.",
    },
    "coins_lesson": 46,
    "coins_boss": 27,
}

LESSON_AVERAGE = {
    "topic": "Среднее арифметическое",
    "context_theme": "detective",
    "explanation": (
        "Среднее арифметическое нескольких чисел находят так: складывают все числа, а затем "
        "делят полученную сумму на количество этих чисел. Например, среднее арифметическое чисел "
        "4, 7 и 10 равно (4+7+10)÷3=21÷3=7. Среднее арифметическое показывает, какое «типичное» "
        "значение можно было бы ожидать, если бы общая сумма делилась поровну между всеми "
        "слагаемыми."
    ),
    "explanation_game": (
        "Чтобы понять, насколько необычна сумма за 1 июля, ты считаешь среднее арифметическое "
        "четырёх уже известных краж: (800+700+1200+900)÷4=3600÷4=900 монет — вот сколько в среднем "
        "приносило одно дело раньше. Пока ты записываешь расчёт, инспектор приносит из архива ещё "
        "два похожих старых отчёта, которые нашлись под грудой других бумаг — суммы по ним "
        "составили 1100 и 1300 монет. С учётом всех шести известных сумм среднее становится "
        "ровнее, но главное не меняется: 1500 монет, ожидаемые 1 июля, заметно выше любого "
        "«типичного» дела Тени и Эха. Это не рядовая кража, а что-то более крупное — и, судя по "
        "дате, оно вот-вот должно произойти."
    ),
    "questions": [
        {
            "text": "Найди среднее арифметическое чисел 5, 9 и 13.",
            "options": ["9", "13", "5", "27"],
            "correct": 0,
            "hint": "Сложи все три числа и раздели сумму на 3.",
            "explanation": "(5+9+13)÷3=27÷3=9."
        },
        {
            "text": "Найди среднее арифметическое чисел 10, 20, 30 и 40.",
            "options": ["25", "20", "30", "100"],
            "correct": 0,
            "hint": "Сложи все четыре числа и раздели сумму на 4.",
            "explanation": "(10+20+30+40)÷4=100÷4=25."
        },
        {
            "text": "Чтобы найти среднее арифметическое нескольких чисел, нужно…",
            "options": [
                "Сложить все числа и разделить сумму на их количество",
                "Перемножить все числа между собой",
                "Найти самое большое из чисел",
                "Вычесть меньшее число из большего"
            ],
            "correct": 0,
            "hint": "Вспомни правило из объяснения.",
            "explanation": "Среднее арифметическое находят, складывая все числа и деля сумму на их количество."
        },
        {
            "text": "Найди среднее арифметическое сумм четырёх краж: 800, 700, 1200 и 900 монет.",
            "options": ["900", "850", "950", "800"],
            "correct": 0,
            "hint": "Сложи все четыре суммы и раздели на 4.",
            "explanation": "(800+700+1200+900)÷4=3600÷4=900."
        },
        {
            "text": "Среднее арифметическое трёх чисел равно 12, два из них — 10 и 15. Чему равно третье число?",
            "options": ["11", "13", "9", "12"],
            "correct": 0,
            "hint": "Сначала найди сумму всех трёх чисел (среднее × количество), а затем вычти два известных.",
            "explanation": "Сумма трёх чисел: 12×3=36. Третье число: 36−10−15=11."
        }
    ],
    "boss_task": {
        "answer": "1000",
        "text": (
            "В архиве нашлись ещё два похожих отчёта о прошлых кражах на суммы 1100 и 1300 "
            "монет — в дополнение к уже известным четырём (800, 700, 1200 и 900 монет). Каково "
            "среднее арифметическое всех шести известных сумм?"
        ),
        "solution": (
            "Ответ: 1000 монет. Сумма всех шести значений: 800+700+1200+900+1100+1300=6000. "
            "Среднее арифметическое: 6000÷6=1000."
        ),
        "hint1": "Сначала сложи все шесть сумм по порядку.",
        "hint2": "Раздели полученную сумму на количество сумм — на 6.",
    },
    "coins_lesson": 50,
    "coins_boss": 29,
}

LESSON_TYPICAL_PROBLEMS = {
    "topic": "Типовые задачи",
    "context_theme": "detective",
    "explanation": (
        "В задачах на движение навстречу друг другу расстояние между объектами сокращается на "
        "сумму их скоростей за каждую единицу времени, поэтому время до встречи находят делением "
        "начального расстояния на сумму скоростей. В задачах на движение в одном направлении "
        "(когда один догоняет другого) расстояние между ними меняется на разность скоростей, "
        "поэтому время, через которое один догонит другого, находят делением расстояния между "
        "ними на разность скоростей. При движении по реке скорость по течению равна собственной "
        "скорости плюс скорость течения, а против течения — собственная скорость минус скорость "
        "течения. В задачах на взвешивание и переливание используют то, что общая масса или объём "
        "при переливании и перекладывании не меняется — меняется только то, как они распределены "
        "между сосудами или чашами весов."
    ),
    "explanation_game": (
        "1 июля, ровно как и предсказывала диаграмма, на реке за старым складом появляется лодка "
        "— Тень и Эхо пытаются уйти вниз по течению с уже награбленным. Полицейский катер "
        "бросается в погоню с того же места, но с опозданием: когда катер отходит от причала, "
        "лодка уже на 12 км впереди. Собственная скорость катера — 24 км/ч, лодки — 18 км/ч, "
        "скорость течения реки — 3 км/ч, и оба судна идут по течению. Значит, катер движется со "
        "скоростью 24+3=27 км/ч, а лодка — 18+3=21 км/ч. Расстояние между ними сокращается на "
        "27−21=6 км за каждый час, а значит нагнать лодку, отставание в 12 км, катер сможет ровно "
        "за 12÷6=2 часа. Инспектор передаёт расчёт по рации на катер — и ровно через два часа "
        "лодку Тени и Эха действительно останавливают у поворота реки."
    ),
    "questions": [
        {
            "text": (
                "Расстояние между двумя городами — 180 км. Из них навстречу друг другу выехали "
                "два автомобиля со скоростями 40 км/ч и 50 км/ч. Через сколько часов они "
                "встретятся?"
            ),
            "options": ["2 ч", "3 ч", "4,5 ч", "1,8 ч"],
            "correct": 0,
            "hint": "При движении навстречу друг другу время встречи — расстояние, делённое на сумму скоростей.",
            "explanation": "180 ÷ (40+50) = 180 ÷ 90 = 2 ч."
        },
        {
            "text": (
                "Первый велосипедист едет со скоростью 60 км/ч следом за вторым, который едет со "
                "скоростью 45 км/ч в том же направлении. Расстояние между ними — 30 км. Через "
                "сколько часов первый догонит второго?"
            ),
            "options": ["2 ч", "1,5 ч", "3 ч", "0,5 ч"],
            "correct": 0,
            "hint": "При движении вдогонку время — расстояние, делённое на разность скоростей.",
            "explanation": "30 ÷ (60−45) = 30 ÷ 15 = 2 ч."
        },
        {
            "text": (
                "Собственная скорость лодки — 15 км/ч, скорость течения реки — 2 км/ч. Какова "
                "скорость лодки против течения?"
            ),
            "options": ["13 км/ч", "17 км/ч", "15 км/ч", "30 км/ч"],
            "correct": 0,
            "hint": "Против течения из собственной скорости вычитают скорость течения.",
            "explanation": "15−2=13 км/ч."
        },
        {
            "text": (
                "На чашечных весах слева лежит гиря 7 кг и яблоко, справа — гиря 10 кг. Весы в "
                "равновесии. Сколько весит яблоко?"
            ),
            "options": ["3 кг", "17 кг", "7 кг", "10 кг"],
            "correct": 0,
            "hint": "Равновесие значит, что масса слева равна массе справа — вычти известную гирю из другой чаши.",
            "explanation": "10−7=3 кг."
        },
        {
            "text": (
                "В сосуде было 8 литров воды. Сначала отлили половину, а затем ещё 1 литр. Сколько "
                "литров воды осталось в сосуде?"
            ),
            "options": ["3 л", "4 л", "5 л", "2 л"],
            "correct": 0,
            "hint": "Сначала найди половину от 8 литров, а затем вычти ещё 1 литр.",
            "explanation": "Половина от 8 л — это 4 л. После этого отлили ещё 1 л: 4−1=3 л."
        }
    ],
    "boss_task": {
        "answer": "2",
        "text": (
            "Катер полиции бросился в погоню за лодкой Тени и Эха, которые пытаются уйти вниз по "
            "реке. Собственная скорость катера — 24 км/ч, лодки — 18 км/ч, скорость течения реки "
            "— 3 км/ч, оба судна идут по течению. В момент начала погони лодка была впереди катера "
            "на 12 км. Через сколько часов катер догонит лодку?"
        ),
        "solution": (
            "Ответ: 2 часа. Скорость катера по течению: 24+3=27 км/ч. Скорость лодки по течению: "
            "18+3=21 км/ч. Разность скоростей: 27−21=6 км/ч. Время погони: 12÷6=2 часа."
        ),
        "hint1": "Найди скорость катера и лодки по течению реки (прибавь скорость течения к собственной скорости каждого).",
        "hint2": "Раздели расстояние между ними (12 км) на разность их скоростей по течению.",
    },
    "coins_lesson": 68,
    "coins_boss": 45,
}

LESSON_CONTROL_DATA_ANALYSIS = {
    "topic": "Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Это итоговая проверка по всем темам раздела «Анализ данных и текстовые задачи»: чтение "
        "и построение таблиц и столбчатых диаграмм, нахождение среднего арифметического "
        "нескольких чисел, а также решение типовых задач на движение (навстречу, вдогонку, по "
        "течению и против течения реки) и на взвешивание и переливание. Каждое задание проверяет "
        "отдельное умение из трёх пройденных уроков раздела."
    ),
    "explanation_game": (
        "Катер настигает лодку ровно там, где и предсказывал расчёт — Тень и Эхо задержаны у "
        "поворота реки, а с ними и весь награбленный за 1 июля груз. Инспектор составляет "
        "итоговый протокол по всему разделу «Анализ данных» и всему долгому расследованию, "
        "которое началось ещё с кражи цифр из музея, — и напоследок устраивает тебе финальную "
        "проверку: прочитать диаграмму, найти среднее значение, решить задачу на движение и на "
        "взвешивание. Когда всё сходится, инспектор наконец достаёт из архива самый первый, ещё "
        "музейный сейф — тот, что был закрыт с самого начала расследования, — и внутри, среди "
        "документов, лежит опись украденного по годам. Дело окончательно закрыто, а вместе с ним "
        "пройден весь курс математики 5 класса."
    ),
    "questions": [
        {
            "text": (
                "На диаграмме показаны уловы трёх рыбаков: Иван поймал 14 кг, Пётр — 9 кг, Сергей "
                "— 20 кг рыбы. Кто поймал больше всех?"
            ),
            "options": ["Сергей", "Иван", "Пётр", "Все поймали поровну"],
            "correct": 0,
            "hint": "Найди самое большое число среди трёх значений.",
            "explanation": "20 кг (Сергей) — самое большое значение из трёх."
        },
        {
            "text": (
                "В таблице расходов отряда полиции за три месяца:\n"
                "               Март  Апрель  Май\n"
                "Патрули         40     35     50\n"
                "Топливо         20     18     25\n"
                "Сколько было потрачено на топливо в мае?"
            ),
            "options": ["25", "50", "18", "35"],
            "correct": 0,
            "hint": "Найди строку «Топливо» и столбец «Май».",
            "explanation": "На пересечении строки «Топливо» и столбца «Май» стоит число 25."
        },
        {
            "text": "Сложи все значения диаграммы: 300, 250, 400 и 150.",
            "options": ["1100", "1000", "1200", "950"],
            "correct": 0,
            "hint": "Складывай числа по очереди.",
            "explanation": "300+250=550, 550+400=950, 950+150=1100."
        },
        {
            "text": "Найди среднее арифметическое чисел 6, 10 и 14.",
            "options": ["10", "14", "6", "30"],
            "correct": 0,
            "hint": "Сложи числа и раздели сумму на 3.",
            "explanation": "(6+10+14)÷3=30÷3=10."
        },
        {
            "text": (
                "За 5 дней турист проходил 8, 10, 12, 9 и 11 км. Сколько километров в среднем он "
                "проходил за день?"
            ),
            "options": ["10 км", "12 км", "9 км", "11 км"],
            "correct": 0,
            "hint": "Сложи все пять значений и раздели сумму на 5.",
            "explanation": "8+10+12+9+11=50, 50÷5=10 км."
        },
        {
            "text": (
                "Среднее арифметическое четырёх чисел равно 15. Три из них — 10, 18 и 20. Чему "
                "равно четвёртое число?"
            ),
            "options": ["12", "18", "8", "22"],
            "correct": 0,
            "hint": "Сумма всех четырёх чисел равна 15×4. Вычти из неё три известных числа.",
            "explanation": "Сумма всех чисел: 15×4=60. Четвёртое число: 60−10−18−20=12."
        },
        {
            "text": (
                "Расстояние между городами — 210 км. Навстречу друг другу выехали два автомобиля "
                "со скоростями 55 км/ч и 50 км/ч. Через сколько часов они встретятся?"
            ),
            "options": ["2 ч", "4 ч", "1,5 ч", "3 ч"],
            "correct": 0,
            "hint": "Раздели расстояние на сумму скоростей.",
            "explanation": "210 ÷ (55+50) = 210 ÷ 105 = 2 ч."
        },
        {
            "text": (
                "Скорость катера — 32 км/ч, скорость лодки — 20 км/ч, лодка находится впереди на "
                "24 км, оба плывут в одну сторону. Через сколько часов катер догонит лодку?"
            ),
            "options": ["2 ч", "1,2 ч", "4 ч", "0,75 ч"],
            "correct": 0,
            "hint": "Раздели расстояние на разность скоростей.",
            "explanation": "24 ÷ (32−20) = 24 ÷ 12 = 2 ч."
        },
        {
            "text": (
                "Собственная скорость лодки — 16 км/ч, скорость течения реки — 4 км/ч. Какова "
                "скорость лодки против течения?"
            ),
            "options": ["12 км/ч", "20 км/ч", "16 км/ч", "4 км/ч"],
            "correct": 0,
            "hint": "Против течения из собственной скорости вычитают скорость течения.",
            "explanation": "16−4=12 км/ч."
        },
        {
            "text": (
                "На весах уравновешены гиря 12 кг и мешок с песком. Из мешка отсыпали 5 кг песка "
                "в другой пустой мешок. Сколько килограммов песка осталось в первом мешке?"
            ),
            "options": ["7 кг", "12 кг", "5 кг", "17 кг"],
            "correct": 0,
            "hint": "Вычти отсыпанную массу из первоначальной массы мешка.",
            "explanation": "12−5=7 кг."
        }
    ],
    "boss_task": {
        "answer": "2500",
        "text": (
            "В музейном сейфе — опись украденного по 4 годам: 2400, 1900, 3100 и 2600 монет за "
            "каждый год. Найди среднее количество монет, украденных за один год."
        ),
        "solution": (
            "Ответ: 2500 монет. Сумма по всем годам: 2400+1900+3100+2600=10000. Среднее "
            "арифметическое: 10000÷4=2500."
        ),
        "hint1": "Сложи суммы за все 4 года.",
        "hint2": "Раздели полученную сумму на количество лет — на 4.",
    },
    "coins_lesson": 90,
    "coins_boss": 60,
}

LESSON_FINAL_EXAM = {
    "topic": "Итоговый экзамен",
    "context_theme": "detective",
    "explanation": (
        "Это финальный обзорный урок по всему курсу «Математика, 5 класс» — по одному-два "
        "вопроса из каждого раздела, плюс комплексная итоговая задача. Раздел «Натуральные "
        "числа»: чтение и сравнение многозначных чисел, признаки делимости на 2, 3, 5, 9 и 10, "
        "НОД (наибольший общий делитель) и НОК (наименьшее общее кратное, НОК=(a×b)÷НОД). "
        "Раздел «Действия с натуральными числами»: свойства сложения и умножения, степень числа "
        "(aⁿ — умножение числа на себя n раз), порядок действий — сначала скобки, затем степень, "
        "затем умножение и деление слева направо, и только потом сложение и вычитание. Раздел "
        "«Выражения и уравнения»: буквенные выражения и подстановка значений переменной, "
        "уравнение и его корень, формула пути s=v×t и обратные к ней. Раздел «Обыкновенные "
        "дроби»: числитель и знаменатель, основное свойство дроби (сокращение и приведение к "
        "новому знаменателю), действия с дробями, нахождение части от числа и числа по его "
        "части. Раздел «Геометрические фигуры и величины»: периметр многоугольника, площадь "
        "прямоугольника S=a×b, объём прямоугольного параллелепипеда V=a×b×c и куба V=a³. Раздел "
        "«Анализ данных и текстовые задачи»: чтение таблиц и столбчатых диаграмм, среднее "
        "арифметическое нескольких чисел, задачи на движение навстречу, вдогонку и по реке."
    ),
    "explanation_game": (
        "Дело, начатое кражей цифр из музея, официально закрыто, но старший инспектор просит об "
        "последней услуге: составить сводное досье для суда — короткую выжимку по каждому эпизоду "
        "расследования, от самого первого сейфа в музейном зале до поимки Тени и Эха на реке. "
        "Директор музея хочет понять, какой именно приём помог раскрыть каждое дело: разряды и "
        "сравнение чисел в самом начале, свойства действий и порядок вычислений в архиве вора, "
        "буквенные уравнения в блокнотах учеников, дроби у проявителя на чердаке пакгауза, "
        "чертежи здания с углами и объёмом тайника, и, наконец, таблицы и расчёты скорости в "
        "погоне на реке. Ты садишься писать финальный протокол, вспоминая по очереди все "
        "использованные приёмы, а в самом конце инспектор просит вычислить номер архивного дела "
        "по последней формуле — после этого сейф с материалами расследования будет опечатан "
        "навсегда."
    ),
    "questions": [
        {
            "text": "Из чисел 342, 145, 720 и 891 выбери то, которое делится одновременно на 2, 3 и 5.",
            "options": ["342", "145", "720", "891"],
            "correct": 2,
            "hint": "Число, которое делится и на 2, и на 5 одновременно, обязательно оканчивается на 0.",
            "explanation": "720 оканчивается на 0 (делится на 2 и 5), а сумма его цифр 7+2+0=9 делится на 3."
        },
        {
            "text": "Найди НОК чисел 8 и 12.",
            "options": ["24", "96", "4", "48"],
            "correct": 0,
            "hint": "Используй формулу НОК = (a×b) ÷ НОД(a,b).",
            "explanation": "НОД(8,12)=4, поэтому НОК=(8×12)÷4=96÷4=24."
        },
        {
            "text": "Вычисли значение выражения: 3² + (14−6) × 2.",
            "options": ["34", "46", "22", "25"],
            "correct": 3,
            "hint": "Порядок действий: сначала скобки, потом степень, потом умножение, и только затем сложение.",
            "explanation": "3²=9, в скобках 14−6=8, затем 8×2=16, и 9+16=25."
        },
        {
            "text": "Чему равно значение выражения 4³?",
            "options": ["16", "64", "12", "48"],
            "correct": 1,
            "hint": "Возведение в куб — это умножение числа само на себя три раза.",
            "explanation": "4³=4×4×4=64."
        },
        {
            "text": "Реши уравнение: 7x−9=40. Чему равен корень уравнения x?",
            "options": ["5", "49", "7", "4"],
            "correct": 2,
            "hint": "Перенеси −9 в правую часть с противоположным знаком, а затем раздели обе части на 7.",
            "explanation": "7x=40+9=49, значит x=49÷7=7."
        },
        {
            "text": "Мотоциклист ехал 3 часа со скоростью 54 км/ч. Какое расстояние он проехал?",
            "options": ["162", "170", "54", "180"],
            "correct": 0,
            "hint": "Используй формулу пути: s=v×t.",
            "explanation": "s=54×3=162 км."
        },
        {
            "text": "Сократи дробь 36/48 до несократимого вида.",
            "options": ["9/12", "6/8", "2/3", "3/4"],
            "correct": 3,
            "hint": "Найди наибольший общий делитель числителя и знаменателя и раздели оба числа на него.",
            "explanation": "НОД(36,48)=12, значит 36÷12=3, 48÷12=4, и дробь принимает вид 3/4."
        },
        {
            "text": "В коробке было 90 конфет. Дети съели 2/5 всех конфет. Сколько конфет они съели?",
            "options": ["45", "36", "54", "18"],
            "correct": 1,
            "hint": "Чтобы найти часть от числа, умножь число на дробь.",
            "explanation": "90×2/5=180/5=36 конфет."
        },
        {
            "text": "Найди площадь прямоугольника со сторонами 9 м и 6 м.",
            "options": ["30", "15", "54", "45"],
            "correct": 2,
            "hint": "Площадь прямоугольника вычисляется по формуле S=a×b.",
            "explanation": "S=9×6=54 м²."
        },
        {
            "text": "Найди среднее арифметическое чисел 12, 18, 24 и 30.",
            "options": ["21", "20", "22", "24"],
            "correct": 0,
            "hint": "Сложи все числа и раздели сумму на их количество.",
            "explanation": "(12+18+24+30)÷4=84÷4=21."
        }
    ],
    "boss_task": {
        "answer": "27",
        "text": (
            "Чтобы опечатать архив, нужно вычислить номер финального протокола. Шаг 1: реши "
            "уравнение 5x−14=61 и найди x. Шаг 2: найди периметр прямоугольника со сторонами x см "
            "и (x−3) см. Шаг 3: раздели полученный периметр на 2. Какое число получится в итоге?"
        ),
        "solution": (
            "Ответ: 27. Шаг 1: 5x−14=61 → 5x=75 → x=15. Шаг 2: стороны прямоугольника — 15 см и "
            "12 см, периметр P=2×(15+12)=54 см. Шаг 3: 54÷2=27."
        ),
        "hint1": "Сначала реши уравнение: перенеси −14 в правую часть с противоположным знаком.",
        "hint2": "Периметр прямоугольника считается по формуле P=2×(a+b), где a и b — стороны.",
    },
    "coins_lesson": 100,
    "coins_boss": 70,
}

LESSON_REINFORCE_FRACTION_PROPERTY = {
    "topic": "Закрепление: Основное свойство дроби",
    "context_theme": "detective",
    "explanation": (
        "Повторим основное свойство дроби: числитель и знаменатель можно умножить или разделить "
        "на одно и то же натуральное число — значение дроби не изменится. При сокращении важно "
        "делить на наибольший общий делитель (НОД) числителя и знаменателя, а не на первое "
        "попавшееся общее число — иначе дробь сократится не полностью и её нужно будет сокращать "
        "ещё раз. При приведении к новому знаменателю сначала находят, во сколько раз новый "
        "знаменатель больше старого (делят новый знаменатель на старый), а затем умножают на это "
        "число не только знаменатель, но и числитель — записывать в числитель сам множитель "
        "вместо результата умножения нельзя."
    ),
    "explanation_game": (
        "Перед тем как архив опечатают навсегда, инспектор находит на чердаке ещё одну россыпь "
        "бирок с дробями — судя по всему, черновик, который Тень и Эхо использовали, пока "
        "готовили основной тайник. Часть бирок сокращена не до конца, часть явно приведена к "
        "общему знаменателю с ошибкой, и инспектор просит тебя навести порядок в записях, прежде "
        "чем сдать их в качестве вещественного доказательства."
    ),
    "questions": [
        {
            "text": "Сократи дробь 24/32 до простейшего вида.",
            "options": ["3/4", "6/8", "12/16", "4/3"],
            "correct": 0,
            "hint": "Раздели числитель и знаменатель не на любое общее число, а на их наибольший общий делитель.",
            "explanation": "НОД(24,32)=8, значит 24/32=(24÷8)/(32÷8)=3/4. Если разделить только на 2 или на 4, дробь сократится не полностью."
        },
        {
            "text": "Сократи дробь 42/56 до простейшего вида.",
            "options": ["6/8", "21/28", "3/4", "4/3"],
            "correct": 2,
            "hint": "Проверь: делится ли ещё дробь после первого сокращения? Ищи именно наибольший общий делитель.",
            "explanation": "НОД(42,56)=14, значит 42/56=(42÷14)/(56÷14)=3/4."
        },
        {
            "text": "Приведи дробь 3/7 к знаменателю 28.",
            "options": ["4/28", "12/28", "9/28", "24/28"],
            "correct": 1,
            "hint": "Сначала узнай, во сколько раз 28 больше 7, а затем умножь на это число И числитель, И знаменатель.",
            "explanation": "28÷7=4, значит умножаем числитель и знаменатель на 4: 3/7=(3×4)/(7×4)=12/28. Число 4 — это множитель, а не готовый числитель."
        },
        {
            "text": "Приведи дробь 5/9 к знаменателю 54.",
            "options": ["6/54", "24/54", "45/54", "30/54"],
            "correct": 3,
            "hint": "54÷9 даёт множитель — умножь на него и числитель тоже, а не только знаменатель.",
            "explanation": "54÷9=6, значит 5/9=(5×6)/(9×6)=30/54."
        },
        {
            "text": "Равны ли дроби 8/10 и 20/25?",
            "options": [
                "Нет, 8/10 больше",
                "Нет, 20/25 больше",
                "Да, обе сокращаются до 4/5",
                "Их нельзя сравнивать"
            ],
            "correct": 2,
            "hint": "Сократи каждую дробь до простейшего вида и сравни результаты.",
            "explanation": "8/10=4/5 и 20/25=4/5 — обе дроби равны."
        }
    ],
    "boss_task": {
        "answer": "3/4",
        "text": (
            "На новой полке архива — четыре бирки с дробями: 3/8, 5/12, 3/4 и 7/10, а в описи "
            "рядом стоит дробь 27/36. Сократи 27/36 до простейшего вида и определи, какой из "
            "бирок она соответствует."
        ),
        "solution": (
            "Ответ: 3/4. Наибольший общий делитель чисел 27 и 36 равен 9, значит "
            "27/36=(27÷9)/(36÷9)=3/4 — это и есть нужная бирка."
        ),
        "hint1": "Найди наибольший общий делитель числителя и знаменателя дроби 27/36.",
        "hint2": "Раздели и числитель, и знаменатель на этот общий делитель — сравни результат с бирками.",
    },
    "coins_lesson": 58,
    "coins_boss": 34,
}

LESSON_REINFORCE_FRACTION_OPERATIONS = {
    "topic": "Закрепление: Действия с дробями",
    "context_theme": "detective",
    "explanation": (
        "При сложении и вычитании смешанных чисел целые и дробные части складывают (вычитают) "
        "отдельно. Если при сложении дробных частей получается неправильная дробь (числитель "
        "больше или равен знаменателю), из неё обязательно выделяют целую часть и добавляют её к "
        "сумме целых — оставлять неправильную дробь в ответе нельзя. При вычитании, если дробная "
        "часть уменьшаемого меньше дробной части вычитаемого, одну целую единицу «занимают» и "
        "переводят в дробь того же знаменателя, прежде чем вычитать. Чтобы умножить дробь на "
        "натуральное число, умножают числитель; чтобы разделить дробь на натуральное число, "
        "умножают знаменатель (или делят числитель, если он делится нацело)."
    ),
    "explanation_game": (
        "В том же ящике под старой афишей находится ещё один мерный сосуд с остатками "
        "проявителя — судя по пятнам на этикетке, кто-то уже пробовал с ним работать, но "
        "перепутал в расчётах целые и дробные части. Прежде чем закрыть это дело окончательно, "
        "инспектор просит тебя пересчитать всё заново на похожих смесях, чтобы в протоколе не "
        "осталось ни одной неправильной дроби."
    ),
    "questions": [
        {
            "text": "Вычисли: 1 целая 4/9 + 2 целых 7/9.",
            "options": ["3 целых 11/9", "4 целых 2/9", "3 целых 2/9", "4 целых 11/9"],
            "correct": 1,
            "hint": "Сложи целые части и дробные части отдельно, а затем проверь: не получилась ли дробная часть неправильной дробью?",
            "explanation": "Целые: 1+2=3. Дробные: 4/9+7/9=11/9=1 целая 2/9. Итого: 3+1 целых и 2/9 = 4 целых 2/9."
        },
        {
            "text": "Вычисли: 3 целых 5/8 + 2 целых 6/8.",
            "options": ["5 целых 11/8", "5 целых 3/8", "6 целых 11/8", "6 целых 3/8"],
            "correct": 3,
            "hint": "Дробная часть 5/8+6/8 больше единицы — не забудь перенести лишнюю целую в сумму целых частей.",
            "explanation": "Целые: 3+2=5. Дробные: 5/8+6/8=11/8=1 целая 3/8. Итого: 5+1 целых и 3/8 = 6 целых 3/8."
        },
        {
            "text": "Вычисли: 5 целых 2/7 − 1 целая 5/7.",
            "options": ["4 целых 3/7", "3 целых 3/7", "3 целых 4/7", "4 целых 4/7"],
            "correct": 2,
            "hint": "Дробная часть уменьшаемого (2/7) меньше дробной части вычитаемого (5/7) — займи одну целую единицу и переведи её в 7/7.",
            "explanation": "Занимаем единицу: 5 целых 2/7 = 4 целых 9/7. Целые: 4−1=3. Дробные: 9/7−5/7=4/7. Итого: 3 целых 4/7."
        },
        {
            "text": "Вычисли: 3/5 × 4. Ответ дай как обычную дробь.",
            "options": ["12/5", "7/5", "12/20", "3/20"],
            "correct": 0,
            "hint": "Умножь числитель на 4, знаменатель оставь без изменений.",
            "explanation": "3/5 × 4 = (3×4)/5 = 12/5."
        },
        {
            "text": "От плитки шоколада осталось 4/7. Её разделили поровну между 2 детьми. Какая часть целой плитки достанется каждому?",
            "options": ["4/14", "2/7", "8/7", "4/7"],
            "correct": 1,
            "hint": "Раздели дробь 4/7 на натуральное число 2 — умножь знаменатель на это число, а затем сократи результат, если возможно.",
            "explanation": "4/7 ÷ 2 = 4/(7×2) = 4/14, а после сокращения на 2 получаем 2/7."
        }
    ],
    "boss_task": {
        "answer": "7 полных бутылочек, останется 1/5 литра",
        "text": (
            "В третьем сосуде было 2 целых 3/5 литра раствора, инспектор доливает ещё 1 целую "
            "4/5 литра из второго сосуда. Затем всю смесь разливают по бутылочкам вместимостью "
            "3/5 литра каждая. Сколько получится полных бутылочек и сколько раствора останется?"
        ),
        "solution": (
            "Ответ: 7 полных бутылочек, останется 1/5 литра. Сложи объёмы: целые 2+1=3, дробные "
            "3/5+4/5=7/5=1 целая 2/5, итого 3+1 целых и 2/5 = 4 целых 2/5 = 22/5 литра. Раздели на "
            "размер бутылочки: 22/5 ÷ 3/5 = 22/3 ≈ 7,33, значит получится 7 полных бутылочек. Они "
            "расходуют 7×3/5=21/5, а остаток равен 22/5−21/5=1/5 литра."
        ),
        "hint1": "Сначала сложи оба объёма — не забудь про перенос, если дробная часть суммы становится больше единицы.",
        "hint2": "Получившийся объём переведи в неправильную дробь и раздели на размер одной бутылочки; целая часть результата — число полных бутылочек, а остаток покажет, сколько раствора не израсходовано.",
    },
    "coins_lesson": 65,
    "coins_boss": 40,
}

LESSON_REINFORCE_FRACTION_PROBLEMS = {
    "topic": "Закрепление: Задачи на дроби",
    "context_theme": "detective",
    "explanation": (
        "Чтобы найти, какую часть одно число составляет от другого (дробное отношение двух "
        "чисел), первое число делят на второе и записывают результат в виде дроби — но эту дробь "
        "обязательно сокращают до простейшего вида, а не оставляют как есть. Чтобы найти часть от "
        "числа, число умножают на дробь. Чтобы найти число по известной его части, известную "
        "величину делят на дробь."
    ),
    "explanation_game": (
        "В самом конце бухгалтерской книги, уже после записи про Тень и Эха, инспектор находит "
        "черновую страницу с недописанными расчётами долей — судя по всему, вор пытался понять, "
        "какую часть добычи получил каждый из сообщников, но бросил вычисления на середине, не "
        "сократив ни одной дроби до конца. Инспектор просит тебя закончить эти расчёты на похожих "
        "числах, прежде чем страница окончательно уйдёт в архив."
    ),
    "questions": [
        {
            "text": "Какую часть число 15 составляет от числа 60?",
            "options": ["1/4", "4/15", "1/3", "15/60 без сокращения — так и оставляют"],
            "correct": 0,
            "hint": "Раздели первое число на второе и запиши как дробь, обязательно сократив её до простейшего вида.",
            "explanation": "15/60 = (15÷15)/(60÷15) = 1/4."
        },
        {
            "text": "Какую часть число 8 составляет от числа 20?",
            "options": ["8/20 без сокращения — так и оставляют", "5/2", "2/5", "3/5"],
            "correct": 2,
            "hint": "Не оставляй дробь в исходном виде — найди её наибольший общий делитель с числителем.",
            "explanation": "8/20 = (8÷4)/(20÷4) = 2/5."
        },
        {
            "text": "Найди отношение числа 18 к числу 45 в виде несократимой дроби.",
            "options": ["18/45", "2/5", "5/2", "1/3"],
            "correct": 1,
            "hint": "НОД чисел 18 и 45 больше единицы — найди его и сократи дробь полностью.",
            "explanation": "НОД(18,45)=9, значит 18/45=(18÷9)/(45÷9)=2/5."
        },
        {
            "text": "Найди 5/6 от числа 42.",
            "options": ["36", "30", "37", "35"],
            "correct": 3,
            "hint": "Умножь число на дробь: 42 × 5/6.",
            "explanation": "42 × 5/6 = 210/6 = 35."
        },
        {
            "text": "4/9 некоторого числа равны 36. Найди само число.",
            "options": ["81", "80", "144", "32"],
            "correct": 0,
            "hint": "Раздели известную часть на дробь: 36 ÷ 4/9.",
            "explanation": "36 ÷ 4/9 = 36 × 9/4 = 324/4 = 81."
        }
    ],
    "boss_task": {
        "answer": "1/3",
        "text": (
            "В архиве всего 54 вещественных доказательства по делу, и 36 из них уже занесены в "
            "протокол. Какую часть вещдоков ещё нужно занести — дай ответ несократимой дробью?"
        ),
        "solution": (
            "Ответ: 1/3. Осталось занести 54−36=18 вещдоков. Их доля от общего числа: "
            "18/54=(18÷18)/(54÷18)=1/3."
        ),
        "hint1": "Сначала найди, сколько вещдоков ещё осталось занести — вычти занесённые из общего числа.",
        "hint2": "Раздели оставшееся число на общее число вещдоков и сократи получившуюся дробь до простейшего вида.",
    },
    "coins_lesson": 60,
    "coins_boss": 36,
}

LESSON_REINFORCE_GEOMETRY_VOLUME = {
    "topic": "Закрепление: Объем",
    "context_theme": "detective",
    "explanation": (
        "Объём прямоугольного параллелепипеда с рёбрами a, b и c находят по формуле V=a×b×c, а "
        "объём куба с ребром a — по формуле V=a³=a×a×a. Площадь полной поверхности — это площадь "
        "всех граней фигуры вместе, а не одной грани: у куба шесть одинаковых граней, поэтому "
        "площадь одной грани (a×a) обязательно умножают на 6; у прямоугольного параллелепипеда три "
        "пары одинаковых граней, поэтому используют формулу 2×(a×b+b×c+a×c) — площадь трёх разных "
        "граней складывают и удваивают."
    ),
    "explanation_game": (
        "Пока архив готовят к опечатыванию, в описи находится ещё несколько ящиков-вещдоков, "
        "которые нужно обмерить и занести в протокол — и для каждого требуется указать не только "
        "объём, но и площадь полной поверхности, чтобы понять, сколько материала ушло на его "
        "изготовление. Инспектор просит быть внимательным: в прошлый раз в похожем протоколе "
        "площадь поверхности куба посчитали всего по одной грани, забыв, что у куба их целых "
        "шесть."
    ),
    "questions": [
        {
            "text": "Найди площадь полной поверхности куба с ребром 5 см.",
            "options": ["25 см²", "150 см²", "125 см³", "100 см²"],
            "correct": 1,
            "hint": "У куба шесть одинаковых граней — площадь одной грани умножь на 6.",
            "explanation": "Площадь одной грани: 5×5=25 см². Всего граней 6, значит 25×6=150 см²."
        },
        {
            "text": "Найди площадь полной поверхности куба с ребром 6 см.",
            "options": ["36 см²", "144 см²", "180 см²", "216 см²"],
            "correct": 3,
            "hint": "Не забудь: у куба именно шесть граней, а не четыре и не пять.",
            "explanation": "Площадь одной грани: 6×6=36 см². Всего граней 6, значит 36×6=216 см²."
        },
        {
            "text": "Найди площадь полной поверхности прямоугольного параллелепипеда с рёбрами 4 см, 3 см и 2 см.",
            "options": ["52 см²", "9 см²", "24 см²", "26 см²"],
            "correct": 0,
            "hint": "Сложи площади трёх разных граней и удвой результат: 2×(ab+bc+ac).",
            "explanation": "2×(4×3 + 3×2 + 4×2) = 2×(12+6+8) = 2×26 = 52 см²."
        },
        {
            "text": "Найди объём куба с ребром 5 см.",
            "options": ["25 см³", "15 см³", "125 см³", "30 см³"],
            "correct": 2,
            "hint": "Объём куба — ребро в кубе (a×a×a), а не ребро, умноженное на 6.",
            "explanation": "5×5×5=125 см³."
        },
        {
            "text": "Сколько литров вмещает контейнер-параллелепипед с рёбрами 20 см, 30 см и 10 см?",
            "options": ["6000 л", "6 л", "60 л", "600 л"],
            "correct": 1,
            "hint": "Сначала переведи все рёбра в дециметры (10 см = 1 дм), а уже потом перемножь их.",
            "explanation": "20 см=2 дм, 30 см=3 дм, 10 см=1 дм. Объём: 2×3×1=6 дм³=6 литров."
        }
    ],
    "boss_task": {
        "answer": "896",
        "text": (
            "В архиве нашёлся ещё один опечатанный ящик-куб с ребром 8 см. Найди его объём и "
            "площадь полной поверхности, а затем сложи оба этих числа. Какое число получится?"
        ),
        "solution": (
            "Ответ: 896. Объём куба: 8×8×8=512 см³. Площадь одной грани: 8×8=64 см², площадь "
            "полной поверхности: 64×6=384 см². Сумма: 512+384=896."
        ),
        "hint1": "Сначала вычисли объём куба — ребро в кубе.",
        "hint2": "Затем найди площадь полной поверхности куба — площадь одной грани, умноженную на 6 — и сложи оба результата.",
    },
    "coins_lesson": 56,
    "coins_boss": 33,
}

LESSON_REINFORCE_CONTROL_GEOMETRY = {
    "topic": "Закрепление: Контрольная работа",
    "context_theme": "detective",
    "explanation": (
        "Точка — простейший геометрический объект, у неё нет ни длины, ни ширины, ни толщины, "
        "только положение. Прямая — бесконечная линия без начала и конца. Луч — часть прямой с "
        "одним началом и без конца на второй стороне. Отрезок — часть прямой с двумя концами, "
        "поэтому у него есть длина. Плоскость — бесконечная ровная поверхность, у неё есть длина и "
        "ширина, но нет толщины. Через две различные точки можно провести ровно одну прямую. "
        "Перпендикулярные прямые пересекаются под углом ровно 90°, а параллельные не пересекаются "
        "никогда."
    ),
    "explanation_game": (
        "Инспектор снова достаёт чертёж здания из бухгалтерской книги — теперь уже для итогового "
        "протокола по делу — и просит ещё раз, уже без спешки, точно назвать, что есть что на "
        "плане: где на чертеже просто отметка-положение, где линия без конца, а где целая "
        "поверхность стены. В прошлый раз в отчёте точку перепутали с плоскостью, а такая ошибка "
        "в официальном документе недопустима."
    ),
    "questions": [
        {
            "text": "Какой объект не имеет ни длины, ни ширины, ни толщины — только положение на плоскости?",
            "options": ["Отрезок", "Луч", "Плоскость", "Точка"],
            "correct": 3,
            "hint": "Это самый простой из всех геометрических объектов — у него вообще нет размеров.",
            "explanation": "Точка не имеет ни длины, ни ширины — у неё есть только положение. Плоскость, в отличие от точки, имеет длину и ширину."
        },
        {
            "text": "Как называется часть прямой, у которой есть только одно начало, а вторая сторона продолжается бесконечно?",
            "options": ["Отрезок", "Прямая", "Луч", "Точка"],
            "correct": 2,
            "hint": "У этого объекта один конец есть, а второго — нет.",
            "explanation": "Луч имеет одно начало, а с другой стороны продолжается бесконечно."
        },
        {
            "text": "Чем отрезок отличается от луча?",
            "options": [
                "У отрезка два конца, у луча — только одно начало, а вторая сторона бесконечна",
                "Отрезок и луч — это одно и то же",
                "У отрезка нет концов, а у луча есть",
                "Луч всегда длиннее отрезка"
            ],
            "correct": 0,
            "hint": "Вспомни, у скольких сторон отрезка есть чёткая граница, а у скольких сторон луча.",
            "explanation": "У отрезка есть оба конца, поэтому у него есть длина; у луча только одно начало, а вторая сторона продолжается бесконечно."
        },
        {
            "text": "Сколько прямых можно провести через две различные точки?",
            "options": ["Бесконечно много", "Ни одной", "Ровно две", "Ровно одну"],
            "correct": 3,
            "hint": "Две точки полностью определяют положение прямой.",
            "explanation": "Через две различные точки проходит ровно одна прямая."
        },
        {
            "text": "Как называются прямые, которые пересекаются под углом ровно 90°?",
            "options": ["Параллельные", "Перпендикулярные", "Ломаные", "Совпадающие"],
            "correct": 1,
            "hint": "Такой угол называется прямым.",
            "explanation": "Прямые, пересекающиеся под углом 90°, называются перпендикулярными."
        }
    ],
    "boss_task": {
        "answer": "Б",
        "text": (
            "На чертеже архивариуса — четыре пометки: А — линия, идущая в обе стороны бесконечно; "
            "Б — точка пересечения двух стен; В — стена, если представить её бесконечной "
            "поверхностью; Г — отрезок коридора между двумя дверями. Какой буквой помечен объект, "
            "у которого есть только положение, а длины и ширины нет?"
        ),
        "solution": (
            "Ответ: Б. Пометка А — это прямая (бесконечная линия), В — плоскость (есть длина и "
            "ширина), Г — отрезок (есть длина, два конца). Только у точки (Б) нет ни длины, ни "
            "ширины — только положение."
        ),
        "hint1": "Вспомни определение точки — у неё нет ни длины, ни ширины, только положение.",
        "hint2": "Проверь по очереди каждую пометку: А — прямая, В — плоскость, Г — отрезок; какая пометка осталась?",
    },
    "coins_lesson": 60,
    "coins_boss": 35,
}

LESSON_REINFORCE_TYPICAL_PROBLEMS = {
    "topic": "Закрепление: Типовые задачи",
    "context_theme": "detective",
    "explanation": (
        "В задачах на движение навстречу друг другу расстояние сокращается на сумму скоростей, "
        "поэтому время до встречи находят делением расстояния на сумму скоростей. В задачах на "
        "движение вдогонку (когда один объект догоняет другой, едущий впереди в том же "
        "направлении) расстояние между ними сокращается на разность скоростей, поэтому время "
        "погони находят делением расстояния между ними именно на разность скоростей, а не на "
        "сумму. При движении по реке скорость по течению равна собственной скорости плюс скорость "
        "течения, а против течения — собственная скорость минус скорость течения."
    ),
    "explanation_game": (
        "Пока архив с делом о краже цифр готовят к окончательному опечатыванию, инспектор "
        "натыкается в старых сводках патрульной службы на похожий случай погони, произошедший "
        "задолго до этого расследования. Он просит тебя разобрать этот старый отчёт для итогового "
        "досье — и особенно внимательно проверить, не перепутаешь ли ты снова погоню вдогонку с "
        "движением навстречу: в прошлый раз в расчётах вместо разности скоростей по ошибке "
        "использовали что-то другое."
    ),
    "questions": [
        {
            "text": (
                "Второй турист идёт со скоростью 6 км/ч, первый догоняет его со скоростью 9 км/ч "
                "в том же направлении. Расстояние между ними сейчас 12 км. Через сколько часов "
                "первый догонит второго?"
            ),
            "options": ["0,8 ч", "4 ч", "2 ч", "6 ч"],
            "correct": 1,
            "hint": "При движении вдогонку время — расстояние, делённое на разность скоростей, а не на сумму.",
            "explanation": "12 ÷ (9−6) = 12 ÷ 3 = 4 ч."
        },
        {
            "text": (
                "Расстояние между сёлами — 96 км. Одновременно навстречу друг другу выехали "
                "грузовик со скоростью 42 км/ч и легковой автомобиль со скоростью 54 км/ч. Через "
                "сколько часов они встретятся?"
            ),
            "options": ["8 ч", "2 ч", "0,5 ч", "1 ч"],
            "correct": 3,
            "hint": "При движении навстречу друг другу время встречи — расстояние, делённое на сумму скоростей.",
            "explanation": "96 ÷ (42+54) = 96 ÷ 96 = 1 ч."
        },
        {
            "text": (
                "Мотоциклист (46 км/ч) догоняет велосипедиста (30 км/ч), который едет впереди в "
                "том же направлении. Расстояние между ними — 48 км. Через сколько часов "
                "мотоциклист догонит велосипедиста?"
            ),
            "options": ["0,6 ч", "1,5 ч", "3 ч", "6 ч"],
            "correct": 2,
            "hint": "Раздели расстояние между ними на разность их скоростей.",
            "explanation": "48 ÷ (46−30) = 48 ÷ 16 = 3 ч."
        },
        {
            "text": "Собственная скорость катера — 22 км/ч, скорость течения реки — 4 км/ч. Какова скорость катера против течения?",
            "options": ["18 км/ч", "26 км/ч", "22 км/ч", "4 км/ч"],
            "correct": 0,
            "hint": "Против течения из собственной скорости вычитают скорость течения.",
            "explanation": "22−4=18 км/ч."
        },
        {
            "text": "На чашечных весах слева гиря 9 кг и коробка, справа гиря 15 кг. Весы в равновесии. Сколько весит коробка?",
            "options": ["24 кг", "9 кг", "15 кг", "6 кг"],
            "correct": 3,
            "hint": "Равновесие значит, что масса слева равна массе справа — вычти известную гирю из другой чаши.",
            "explanation": "15−9=6 кг."
        }
    ],
    "boss_task": {
        "answer": "1,5",
        "text": (
            "В старой сводке патрульная машина (72 км/ч) замечает угнанный грузовик (54 км/ч), "
            "который успел уйти на 27 км вперёд — оба едут в одном направлении по шоссе. Через "
            "сколько часов патруль догонит грузовик?"
        ),
        "solution": (
            "Ответ: 1,5 ч. Это движение вдогонку, поэтому расстояние делят на разность скоростей: "
            "27 ÷ (72−54) = 27 ÷ 18 = 1,5 ч."
        ),
        "hint1": "Это движение вдогонку — используй разность скоростей, а не сумму.",
        "hint2": "Раздели расстояние между машинами (27 км) на разность их скоростей (72−54).",
    },
    "coins_lesson": 60,
    "coins_boss": 38,
}

# Раздел-слайдшоу «Архитектура математики»: не квиз, а просто упорядоченная колода картинок
# (lesson_type="slideshow"). Никаких вопросов, объяснений или монет — только сами слайды и
# кнопки «вперёд»/«назад» на фронтенде (см. ветку lesson_type==='slideshow' в LessonPage.jsx).
# Картинки для слотов "archmath_01".."archmath_15" загружаются родителем в кабинете родителя
# (Настройки → раздел «Архитектура математики — слайды»), через тот же генерический механизм
# слотов (POST /api/settings/upload?slot=...), что и остальные картинки интерфейса. Если слот не
# заполнен — на месте слайда показывается плейсхолдер, ничего не ломается. Число слайдов (15)
# можно менять: LessonPage.jsx ориентируется на длину lesson["slides"], а не на фиксированное
# число, но набор слотов на странице настроек (ARCH_MATH_SLIDES в Settings.jsx) нужно
# синхронизировать при изменении количества.
LESSON_ARCH_MATH_SLIDESHOW = {
    "topic": "Архитектура математики",
    "lesson_type": "slideshow",
    "slides": [f"archmath_{i:02d}" for i in range(1, 16)],
}

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

MATH_5_CURRICULUM = """
**1. Натуральные числа**

- **Цифры и натуральные числа:** чтение, запись и именование многозначных чисел; натуральный ряд и число нуль.
- **Сравнение натуральных чисел:** правила сравнения чисел по разрядам.
- **Округление чисел:** правила округления до заданного разряда.
- **Делимость чисел:** делители и кратные; признаки делимости на 2, 5, 10, 3 и 9.
- **Простые и составные числа:** разложение числа на простые множители.
- **НОД и НОК:** нахождение наибольшего общего делителя и наименьшего общего кратного.
- **Контрольная работа:** итоговая проверка знаний по всем темам раздела «Натуральные числа».

**2. Действия с натуральными числами**

- **Сложение и вычитание:** свойства действий (переместительное, сочетательное) и их применение для упрощения вычислений.
- **Умножение и деление:** свойства умножения (включая распределительное); деление нацело и деление с остатком.
- **Степень числа:** понятие степени с натуральным показателем; квадрат и куб числа.
- **Порядок действий:** правила выполнения операций в числовых выражениях со скобками и без.
- **Контрольная работа:** итоговая проверка знаний по всем темам раздела «Действия с натуральными числами».

**3. Выражения и уравнения**

- **Числовые и буквенные выражения:** составление выражений по условию задачи и нахождение их значений при заданных переменных.
- **Уравнения:** понятия «уравнение» и «корень уравнения»; решение уравнений на основе зависимостей между компонентами действий.
- **Формулы:** использование буквенных формул (например, формулы пути s=v⋅t).
- **Контрольная работа:** итоговая проверка знаний по всем темам раздела «Выражения и уравнения».

**4. Обыкновенные дроби**

- **Понятие дроби:** числитель и знаменатель; изображение дробей на координатном луче.
- **Виды дробей:** правильные и неправильные дроби; понятие смешанного числа.
- **Основное свойство дроби:** сокращение дробей и приведение их к новому знаменателю.
- **Действия с дробями:** сравнение, сложение и вычитание дробей с одинаковыми знаменателями; действия со смешанными числами; умножение и деление дробей.
- **Задачи на дроби:** нахождение части от числа, нахождение числа по его части и определение дробного отношения двух чисел.
- **Контрольная работа:** итоговая проверка знаний по всем темам раздела «Обыкновенные дроби».
- **Закрепление: Основное свойство дроби:** дополнительная практика на сокращение дробей до простейшего вида и приведение к новому знаменателю.
- **Закрепление: Действия с дробями:** дополнительная практика на сложение и вычитание смешанных чисел с переносом целой части.
- **Закрепление: Задачи на дроби:** дополнительная практика на нахождение дробного отношения двух чисел с обязательным сокращением дроби.

**5. Геометрические фигуры и величины**

- **Основные объекты:** точка, прямая, луч, отрезок, плоскость.
- **Измерения:** измерение длины отрезка; единицы измерения длины.
- **Ломаная и многоугольники:** вершины, стороны, понятие периметра многоугольника.
- **Углы:** виды углов (острый, прямой, тупой, развернутый); измерение и построение углов с помощью транспортира.
- **Взаимное расположение прямых:** параллельные и перпендикулярные прямые.
- **Площадь:** формулы площади прямоугольника и квадрата; площадь прямоугольного треугольника; единицы измерения площади (ар, гектар).
- **Объем:** прямоугольный параллелепипед и куб; площадь поверхности и объем; единицы измерения объема.
- **Контрольная работа:** итоговая проверка знаний по всем темам раздела «Геометрические фигуры и величины».
- **Закрепление: Объем:** дополнительная практика на площадь полной поверхности куба и параллелепипеда.
- **Закрепление: Контрольная работа:** дополнительная практика на различение основных геометрических объектов (точка, прямая, луч, отрезок, плоскость).

**6. Анализ данных и текстовые задачи**

- **Работа с информацией:** представление данных в таблицах и столбчатых диаграммах.
- **Среднее арифметическое:** нахождение среднего значения нескольких чисел.
- **Типовые задачи:** задачи на движение (встречное, в противоположных направлениях, по течению и против течения реки); задачи на взвешивание и переливание.
- **Контрольная работа:** итоговая проверка знаний по всем темам раздела «Анализ данных и текстовые задачи».
- **Итоговый экзамен:** финальный обзорный урок по всему курсу «Математика, 5 класс» — по одному-два вопроса из каждого раздела плюс комплексная итоговая задача.
- **Закрепление: Типовые задачи:** дополнительная практика на движение вдогонку (разность скоростей) в сравнении с движением навстречу (сумма скоростей).

**7. Архитектура математики**

- **Архитектура математики:** слайд-шоу без вопросов — только картинки и кнопки «вперёд»/«назад», кратко обо всех правилах и закономерностях за 5 класс.
"""

# Программа «Русский язык, 5 класс» — сюжет «Вечерний вестник» (см. docs/CONTEXT_FOR_CLAUDE.md,
# раздел «Предмет: Русский язык»). Названия разделов и тем (в формате «§ N. Название») взяты из
# программы учебника, поделённого на 2 части (§ нумеруются заново в каждой части — это НЕ ошибка,
# так в оригинале). Описания после двоеточия не сохраняются в БД (используются только как заметки
# для будущей генерации уроков), сами темы разбирает parse_curriculum_text().
RUSSIAN_5_CURRICULUM = """
**1. Повторение изученного в начальных классах**

- **§ 1. Текст:** что такое текст, тема и основная мысль, заголовок.
- **§ 2. Словосочетание. Предложение:** различие словосочетания и предложения, грамматическая основа.
- **§ 3. Состав слова. Орфограмма:** корень, приставка, суффикс, окончание; что такое орфограмма.
- **§ 4. Правописание:** повторение изученных в начальной школе орфограмм (жи-ши, ча-ща, безударные гласные и т.п.).
- **§ 5. Части речи:** повторение самостоятельных и служебных частей речи, их различение.

**2. Культура устной и письменной речи**

- **§ 6. Язык и речь:** различие понятий «язык» и «речь», функции языка.
- **§ 7. Культура устной и письменной речи. Нормы литературного языка:** понятие языковой нормы, её обязательность.
- **§ 8. Произносительная, орфографическая, словообразовательная нормы:** правильное произношение, написание и образование слов.
- **§ 9. Морфологическая, синтаксическая, пунктуационная нормы:** правильное образование форм слов, построение предложений, расстановка знаков препинания.
- **§ 10. Качества речи. Точность и логичность речи:** что делает речь хорошей; точный подбор слов, последовательность изложения.
- **§ 11. Богатство, выразительность, чистота и уместность речи:** разнообразие языковых средств, уместность их использования в разных ситуациях.
- **§ 12. Диалог. Монолог:** различие диалогической и монологической речи, оформление реплик диалога.

**3. Речевая ситуация. Стили речи**

- **§ 13. Признаки речевой ситуации:** кто говорит, кому, зачем и где — компоненты речевой ситуации.
- **§ 14. Разговорный, научный и художественный стили речи:** отличительные признаки трёх стилей, примеры.
- **§ 15. Официально-деловой, публицистический стили речи:** отличительные признаки, сфера применения, примеры.
- **§ 16. Речевая норма:** соответствие стиля речи речевой ситуации.

**4. Синтаксис и пунктуация**

- **§ 17. Словосочетание:** главное и зависимое слово, виды связи.
- **§ 18. Предложение. Виды предложений по цели высказывания и интонации:** повествовательные, вопросительные, побудительные; восклицательные и невосклицательные.
- **§ 19. Главные члены предложения:** подлежащее и сказуемое, способы их выражения.
- **§ 20. Правописание -тся и -ться в глаголах:** правило различения по вопросу (что делает? / что делать?).
- **§ 21. Правописание личных окончаний глаголов:** I и II спряжение, определение спряжения.
- **§ 22. Второстепенные члены предложения:** дополнение, определение, обстоятельство.
- **§ 23. Однородные члены предложения:** признаки однородности, знаки препинания при однородных членах.
- **§ 24. Обращение:** что такое обращение, знаки препинания при обращении.
- **§ 25. Строение сложного предложения:** простые и сложные предложения, союзная и бессоюзная связь.
- **§ 26. Предложения с прямой речью. Знаки препинания в предложениях с прямой речью:** оформление прямой речи до и после слов автора.

**5. Текст**

- **§ 27. Понятие о тексте:** текст как речевое произведение, отличие от набора предложений.
- **§ 28. Основные признаки текста:** связность, цельность, завершённость, наличие темы и основной мысли.
- **§ 29. Виды связи предложений в тексте:** цепная и параллельная связь предложений.
- **§ 30. Как строится текст. Повествование, описание, рассуждение:** типы речи и их структурные признаки.

**6. Фонетика**

- **§ 31. Звуки речи и буквы:** различие звука и буквы, звуковой состав слова.
- **§ 32. Гласные и согласные звуки речи:** классификация звуков, ударные и безударные гласные, парные/непарные согласные.

**7. Фонетика (продолжение)**

- **§ 1. Обозначение мягкости согласных на письме. Двойная роль букв е, ё, ю, я:** мягкий знак, буквы после согласных и в начале слова/после гласной/после ъ и ь.
- **§ 2. Слог. Правила переноса слов. Ударение:** деление на слоги, правила переноса, подвижность и разноместность ударения.

**8. Орфография**

- **§ 3. Правописание безударных гласных в корне слова:** проверяемые ударением, непроверяемые, чередующиеся — общий обзор.
- **§ 4. Правописание согласных в корне слова:** проверяемые, непроизносимые и непроверяемые согласные.
- **§ 5. Правописание безударных гласных в окончании:** проверка окончаний по образцу/вопросу в зависимости от части речи.
- **§ 6. Правописание гласных и согласных в приставках:** приставки, пишущиеся одинаково независимо от произношения.
- **§ 7. Правописание букв з и с на конце приставок:** приставки на з/с перед звонкими и глухими согласными.
- **§ 8. Правописание ы, и после приставок на согласный:** буква ы после русских приставок на согласный вместо и.
- **§ 9. Правописание о, ё после шипящих в корне слова:** проверка чередованием с е, слова-исключения.
- **§ 10. Правописание о, ё после шипящих и ц в окончаниях имён существительных и имён прилагательных:** зависимость от ударения.
- **§ 11. Правописание о, ё после шипящих и ц в суффиксах имён существительных и имён прилагательных:** зависимость от ударения, частные случаи.
- **§ 12. Правописание гласных о, а в корнях с чередованием -гор-//-гар-, -зор-//-зар-, -клон-//-клан-:** зависимость от ударения.
- **§ 13. Правописание гласных о, а в корнях с чередованием -лаг-//-лож-, -раст- (-ращ-)//-рос-:** зависимость от следующих букв/сочетаний, слова-исключения.
- **§ 14. Правописание гласных о, а в корнях с чередованием -кос-//-кас-:** зависимость от наличия суффикса -а- после корня.
- **§ 15. Правописание корней с чередованием гласных е, и:** зависимость от наличия суффикса -а- после корня (-бер-//-бир- и т.п.).
- **§ 16. Правописание и, ы после ц:** в корне, в суффиксах и окончаниях, слова-исключения.
- **§ 17. Правописание буквы ь после шипящих:** в существительных, прилагательных, глаголах — правило по частям речи.

**9. Лексика**

- **§ 18. Слово и его лексическое значение. Прямое и переносное значения слова:** понятие лексического значения, метафора и метонимия как основа переноса.
- **§ 19. Однозначные и многозначные слова:** различение, работа с толковым словарём.
- **§ 20. Синонимы:** синонимический ряд, различия синонимов по оттенкам значения и стилю.
- **§ 21. Антонимы:** подбор антонимов, антонимы в пословицах и поговорках.
- **§ 22. Исконно русские и заимствованные слова:** признаки заимствованных слов, происхождение.
- **§ 23. Общеупотребительные слова. Профессиональные слова и термины:** различие сфер употребления лексики.
- **§ 24. Устаревшие слова. Неологизмы:** историзмы и архаизмы, причины появления новых слов.
- **§ 25. Фразеологические обороты, их отличие от свободных словосочетаний:** признаки фразеологизма, значение целиком, а не по частям.

**10. Повторение изученного в 5-м классе**
"""

# ── Русский язык, 5 класс — раздел 1 ────────────────────────────────────────────

SECTION_INTRO_RU_REVIEW = (
    "Ты уже писал сочинения, разбирал слова по составу и учил части речи в начальной школе — "
    "теперь настало время закрепить эти знания и подняться на новый уровень.\n\n"
    "Что это такое: раздел повторяет базовые понятия русского языка — что такое текст, чем "
    "отличается словосочетание от предложения, из каких частей состоит слово и какие бывают "
    "части речи.\n\n"
    "Почему без этого не обойтись: весь курс русского языка 5 класса — синтаксис, орфография, "
    "лексика — строится на этих понятиях, как этажи дома на фундаменте. Нельзя разбирать сложные "
    "предложения, не умея находить грамматическую основу, и нельзя объяснить орфограмму, не "
    "понимая, из каких частей состоит слово.\n\n"
    "Зачем это тебе: умение видеть, что перед тобой — законченная мысль или просто набор слов, "
    "различать части слова и части речи помогает грамотно писать, понимать чужие тексты и точно "
    "выражать свои мысли."
)

LESSON_RU_TEXT = {
    "topic": "§ 1. Текст",
    "context_theme": "newsroom",
    "explanation": (
        "Текст — это несколько предложений, объединённых общей темой и связанных по смыслу и "
        "грамматически, а не любой набор фраз подряд. Тема текста — это то, о чём в нём говорится. "
        "Основная мысль — это то, что автор хочет сказать читателю по этой теме, главный вывод. "
        "Заголовок обычно называет тему текста или указывает на его основную мысль, но не должен "
        "быть ни слишком широким (обо всём сразу), ни слишком узким (только об одной детали)."
    ),
    "explanation_game": (
        "Столетнее здание редакции «Вечернего вестника» наконец открыли после ремонта, и седой "
        "редактор Архип Кузьмич, последний из старой команды, набирает себе помощника на "
        "лето — тебя. Первое испытание он проводит прямо у входа: раскладывает на письменном столе "
        "стопку разрозненных карточек из уцелевшего архива и просит отделить настоящие газетные "
        "заметки от простого мусора — обрывков случайных фраз, которые кто-то давно использовал "
        "вместо закладок. «Текст — это не любые предложения подряд, — говорит Архип Кузьмич, — а те, "
        "что связаны одной темой и общей мыслью, как звенья одной цепи. У каждой настоящей заметки "
        "есть тема — то, о чём она рассказывает, — и основная мысль — то, ради чего её вообще "
        "написали. А заголовок должен точно указывать на это, не растекаясь мыслью по всей редакции "
        "и не сужаясь до одной случайной детали». Если справишься с разбором карточек, Архип "
        "Кузьмич пустит тебя дальше — к следующему шкафу архива."
    ),
    "questions": [
        {
            "text": "На столе — четыре карточки. На какой из них перед тобой настоящий связный текст, а не случайный набор фраз?",
            "options": [
                "«Дождь. Вторник. Кофе остыл. Лестница скрипит.»",
                "«Собака бежала быстро. Часы показывали пять. Гроза началась внезапно.»",
                "«Утром над рекой стоял густой туман. К полудню солнце разогнало его, и на воде заблестели солнечные блики. Рыбаки говорили, что такой туман — верный знак ясного дня.»",
                "«Зима. Мороз. Каток. Коньки. Снег.»"
            ],
            "correct": 2,
            "hint": "Проверь, есть ли между предложениями общая тема и связь по смыслу.",
            "explanation": "Только вариант про туман — связный текст: все предложения об одном и том же (утреннем тумане над рекой), они логически продолжают друг друга. Остальные — случайные обрывки без общей темы."
        },
        {
            "text": "Прочитай: «Старая типография пахла краской и бумагой. Наборщики вручную составляли строки из свинцовых литер. Ошибиться было легко — одна перевёрнутая буква портила весь лист». Какова тема этого текста?",
            "options": ["Погода в старом городе", "Свинец как металл", "Ошибки в диктанте", "Работа типографии и труд наборщиков"],
            "correct": 3,
            "hint": "Тема — это то, о чём говорится в тексте в целом, а не отдельная деталь.",
            "explanation": "Текст целиком посвящён работе старой типографии и труду наборщиков — это и есть его тема; свинец и ошибки — только детали этой темы."
        },
        {
            "text": "Тот же текст про типографию заканчивается фразой: «Поэтому наборщика чаще всего называли самым внимательным человеком в редакции». Какая здесь основная мысль, а не просто тема?",
            "options": ["Труд наборщика требовал огромной внимательности", "Типография пахла краской", "Свинец тяжелее бумаги", "В редакции было холодно"],
            "correct": 0,
            "hint": "Основная мысль — это вывод, ради которого текст написан, а не просто перечисление фактов.",
            "explanation": "Тема текста — работа типографии, а основная мысль — то, что этот труд требовал огромной внимательности; ради этой мысли текст и написан."
        },
        {
            "text": "Для текста про типографию и наборщиков какой заголовок подходит лучше всего?",
            "options": ["Редакция", "Труд наборщика в старой типографии", "Буква", "Свинец"],
            "correct": 1,
            "hint": "Хороший заголовок называет тему точно — не слишком широко и не слишком узко.",
            "explanation": "«Редакция» — слишком широко, «Буква» и «Свинец» — слишком узко, это лишь детали. Точнее всего — «Труд наборщика в старой типографии»."
        },
        {
            "text": "Архип Кузьмич дал тебе заметку с заголовком «Вечерний вестник». В самой заметке — всего два предложения: «Юлия проверила кассу. В кассе не хватало двух рублей». Подходит ли этот заголовок?",
            "options": [
                "Да, идеально подходит",
                "Да, потому что это старая газета",
                "Нет — заметка вообще не про газету, заголовок нужно менять на тему о кассе",
                "Нет — заметка слишком короткая для заголовка"
            ],
            "correct": 2,
            "hint": "Проверь: о чём реально говорится в тексте — совпадает ли это с заголовком?",
            "explanation": "Заголовок должен отражать тему самого текста. Здесь текст — про недостачу в кассе, а «Вечерний вестник» — просто название газеты, а не тема заметки. Заголовок нужно менять, например, на «Недостача в кассе»."
        }
    ],
    "boss_task": {
        "answer": "3",
        "text": (
            "Архип Кузьмич вручает тебе стопку из пяти карточек архива:\n"
            "1) «Пожар случился сорок лет назад. Огонь повредил архив редакции. Сейчас здание наконец восстанавливают.»\n"
            "2) «Стол. Чашка. Дождь. Три часа.»\n"
            "3) «После пожара уцелела лишь часть архива. Реставраторы разбирают документы по годам. К юбилею газеты часть материалов удастся напечатать снова.»\n"
            "4) «Плащ. Улица. Вторник. Гроза началась.»\n"
            "5) «Юбилейный выпуск решили посвятить истории самой редакции. Архип Кузьмич — последний, кто помнит те годы. Именно поэтому его рассказ так важен для будущего номера.»\n"
            "Сколько из этих пяти карточек — настоящий связный текст?"
        ),
        "solution": (
            "Ответ: 3. Карточки 1, 3 и 5 связаны одной темой — восстановлением архива редакции к "
            "юбилейному выпуску — и логически продолжают друг друга. Карточки 2 и 4 — случайные "
            "наборы слов без темы и связи."
        ),
        "hint1": "Сначала отметь карточки, где предложения продолжают одну и ту же мысль.",
        "hint2": "Проверь, есть ли у отмеченных карточек общая тема — восстановление архива.",
    },
    "coins_lesson": 55,
    "coins_boss": 35,
}

LESSON_RU_PHRASE_SENTENCE = {
    "topic": "§ 2. Словосочетание. Предложение",
    "context_theme": "newsroom",
    "explanation": (
        "Словосочетание — это два и более слова, связанных по смыслу и грамматически, но не "
        "выражающих законченной мысли (например, «старая тетрадь», «читать книгу»). Предложение — "
        "это слово или сочетание слов, выражающее законченную мысль и имеющее грамматическую "
        "основу — подлежащее и сказуемое (например, «Наборщик читал книгу»). Главное отличие: "
        "словосочетание только называет предмет, признак или действие, а предложение сообщает о "
        "чём-то целиком, с интонацией законченного высказывания."
    ),
    "explanation_game": (
        "Довольный тем, как ты разобрал карточки, Архип Кузьмич достаёт с полки пожелтевшую тетрадь "
        "корректора. В ней старый сотрудник помечал красным карандашом ошибки молодых "
        "журналистов — те путали словосочетания с предложениями. «Словосочетание — это два слова, "
        "связанных по смыслу, вроде „старый шкаф“ или „писать статью“, — оно только называет "
        "что-то, но не сообщает законченной мысли, — объясняет Архип Кузьмич. — А предложение — это "
        "уже целая мысль, у него есть грамматическая основа: подлежащее — о ком или о чём идёт "
        "речь, — и сказуемое — что оно делает или каково оно». Найди грамматические основы в старых "
        "пометках корректора — и получишь ключ от следующего шкафа."
    ),
    "questions": [
        {
            "text": "Какая из пар слов — словосочетание, а не предложение?",
            "options": ["Наборщик работал", "Старая типография", "Дверь скрипнула", "Архип Кузьмич улыбнулся"],
            "correct": 1,
            "hint": "Словосочетание не выражает законченной мысли — это просто предмет с признаком или действием.",
            "explanation": "«Старая типография» — словосочетание (признак + предмет), законченной мысли нет. Остальные варианты — предложения с грамматической основой (подлежащее + сказуемое)."
        },
        {
            "text": "В предложении «Юлия проверила старую кассу» найди грамматическую основу.",
            "options": ["старую кассу", "Юлия проверила", "проверила кассу", "Юлия старую"],
            "correct": 1,
            "hint": "Грамматическая основа — это подлежащее (кто?) и сказуемое (что делает?).",
            "explanation": "Подлежащее — «Юлия» (кто?), сказуемое — «проверила» (что сделала?). Вместе это грамматическая основа: «Юлия проверила»."
        },
        {
            "text": "Сравни: «Утренний туман» и «Туман рассеялся». Почему второе — предложение, а первое — только словосочетание?",
            "options": [
                "Потому что во втором больше слов",
                "Потому что во втором есть законченная мысль и грамматическая основа",
                "Потому что первое написано с ошибкой",
                "Разницы нет, оба варианта — предложения"
            ],
            "correct": 1,
            "hint": "Ищи, есть ли во фразе подлежащее и сказуемое, выражающие законченную мысль.",
            "explanation": "«Туман рассеялся» сообщает законченную мысль и имеет грамматическую основу (туман — подлежащее, рассеялся — сказуемое). «Утренний туман» — лишь словосочетание: признак + предмет, без сообщения о действии."
        },
        {
            "text": "Найди грамматическую основу в предложении «Старый редактор бережно хранил архив».",
            "options": ["бережно хранил", "редактор хранил", "старый редактор", "хранил архив"],
            "correct": 1,
            "hint": "Убери второстепенные слова (признаки, обстоятельства) — что останется главным?",
            "explanation": "Главные члены — «редактор» (подлежащее) и «хранил» (сказуемое). «Старый» и «бережно» — второстепенные слова, они не входят в грамматическую основу."
        },
        {
            "text": "В предложении «После долгого перерыва редакция снова начала работу» найди грамматическую основу.",
            "options": ["редакция начала", "долгого перерыва", "снова начала", "редакция работу"],
            "correct": 0,
            "hint": "Ищи, кто (что) совершает действие и что именно он делает — отбрось второстепенные слова.",
            "explanation": "Подлежащее — «редакция» (кто/что?), сказуемое — «начала» (что сделала?). «После долгого перерыва» — обстоятельство, «работу» — дополнение, в грамматическую основу они не входят."
        }
    ],
    "boss_task": {
        "answer": "2",
        "text": (
            "В тетради корректора — заметка: «Вечерняя типография наконец после долгого простоя вновь "
            "застучала печатными машинами». Найди грамматическую основу этого предложения и посчитай, "
            "сколько слов в неё входит."
        ),
        "solution": (
            "Ответ: 2. Грамматическая основа — «типография застучала»: подлежащее «типография» "
            "(кто/что?) и сказуемое «застучала» (что сделала?). Все остальные слова («вечерняя», "
            "«наконец», «после долгого простоя», «вновь», «печатными машинами») — второстепенные "
            "члены предложения."
        ),
        "hint1": "Сначала найди подлежащее — кто или что выполняет действие.",
        "hint2": "Затем найди сказуемое — что именно это подлежащее делает; обстоятельства времени и способа действия в основу не входят.",
    },
    "coins_lesson": 56,
    "coins_boss": 36,
}

LESSON_RU_WORD_STRUCTURE = {
    "topic": "§ 3. Состав слова. Орфограмма",
    "context_theme": "newsroom",
    "explanation": (
        "Слово состоит из значимых частей — морфем: корень (главная часть, хранящая общее "
        "лексическое значение всех однокоренных слов), приставка (стоит перед корнем и образует "
        "новое слово или оттенок значения), суффикс (стоит после корня, чаще всего перед окончанием, "
        "тоже образует новые слова или формы), окончание (изменяемая часть слова, показывающая его "
        "форму — число, падеж, лицо — и не входящая в основу слова). Орфограмма — это место в "
        "слове, где написание не совпадает с произношением напрямую и требует применения правила "
        "(например, безударная гласная, парная согласная на конце слова)."
    ),
    "explanation_game": (
        "За тетрадью корректора обнаруживается старая картотека наборщиков — карточки с разбором "
        "слов на части, которые помогали быстро находить нужный шрифт для похожих слов. «Каждое "
        "слово, — говорит Архип Кузьмич, — как дом с фундаментом: корень — это фундамент, в нём "
        "главный смысл. Приставка стоит перед корнем, как крыльцо, и меняет смысл слова. Суффикс — "
        "как надстроенный этаж после корня, тоже добавляет смысл. А окончание — самая изменчивая "
        "часть, она в основу слова не входит и показывает его форму: число, падеж». Там же, где "
        "буква в слове расходится с тем, что слышится на слух, наборщики красным подчёркивали "
        "место — это и называется орфограммой, слабым местом слова, где легко ошибиться."
    ),
    "questions": [
        {
            "text": "В слове «переход» найди корень.",
            "options": ["пере", "ход", "од", "переход"],
            "correct": 1,
            "hint": "Подбери однокоренные слова: ходить, выход, находка — что общего у них?",
            "explanation": "Корень — «ход» (общая часть со словами «ходить», «выход», «находка»). «Пере-» — это приставка."
        },
        {
            "text": "В слове «читатели» найди суффикс, образующий значение «тот, кто делает действие».",
            "options": ["чита", "тель", "и", "чит"],
            "correct": 1,
            "hint": "Суффикс стоит после корня и перед окончанием; сравни со словами «учитель», «писатель».",
            "explanation": "Суффикс «-тель-» образует существительные со значением «тот, кто выполняет действие»: читатель, учитель, писатель. Корень — «чита-», окончание — «-и»."
        },
        {
            "text": "Какое слово из перечисленных не имеет окончания (окончание нулевое)?",
            "options": ["книга", "окна", "стол", "реки"],
            "correct": 2,
            "hint": "Нулевое окончание не выражено буквами, но всё равно показывает форму слова — попробуй изменить слово по падежам.",
            "explanation": "У слова «стол» окончание нулевое: стол — столА — столУ, форма меняется, хотя в именительном падеже буквы окончания нет. В остальных словах окончания видны: -а, -а, -и."
        },
        {
            "text": "В каком слове есть орфограмма «безударная гласная в корне, проверяемая ударением»?",
            "options": ["стол", "вода", "дом", "март"],
            "correct": 1,
            "hint": "Найди слово, где безударный гласный звук можно проверить, поставив под ударение.",
            "explanation": "В слове «вода» безударная гласная «о» в корне проверяется словом «вОды» — под ударением. В остальных словах гласные в корне уже ударные, орфограммы там нет."
        },
        {
            "text": "Разбери слово «подводный» по составу: сколько в нём значимых частей (морфем), включая окончание?",
            "options": ["2", "3", "4", "5"],
            "correct": 2,
            "hint": "Найди приставку, корень, суффикс и окончание по отдельности.",
            "explanation": "«Подводный» = под- (приставка) + вод- (корень) + -н- (суффикс) + -ый (окончание) — четыре значимые части."
        }
    ],
    "boss_task": {
        "answer": "4",
        "text": "Слово «пришкольный» состоит из нескольких значимых частей. Сколько их всего, включая окончание?",
        "solution": (
            "Ответ: 4. «Пришкольный» = при- (приставка) + школь- (корень, как в слове «школа») + "
            "-н- (суффикс) + -ый (окончание). Всего четыре значимые части."
        ),
        "hint1": "Сначала отдели окончание — изменяемую часть в конце слова.",
        "hint2": "Затем найди корень (сравни со словом «школа»), а между ним и окончанием поищи приставку и суффикс.",
    },
    "coins_lesson": 57,
    "coins_boss": 37,
}

LESSON_RU_SPELLING_BASICS = {
    "topic": "§ 4. Правописание",
    "context_theme": "newsroom",
    "explanation": (
        "В начальной школе изучаются базовые орфографические правила: сочетания жи-ши пишутся с "
        "буквой и (жить, шить), ча-ща — с буквой а (чашка, роща), чу-щу — с буквой у (чудо, щука); "
        "безударные гласные в корне слова проверяются ударением — подбором однокоренного слова, где "
        "эта гласная становится ударной; парные звонкие и глухие согласные на конце слова и перед "
        "другими согласными также проверяются — нужно изменить слово так, чтобы после проверяемой "
        "согласной стояла гласная или сонорный согласный."
    ),
    "explanation_game": (
        "Следующая полка архива — ящик с бланками, где карандашом от руки восстановлены выцветшие "
        "от воды буквы старых заметок. Здесь пригодятся самые базовые правила: сочетания жи-ши "
        "всегда пишутся с и, ча-ща — с а, чу-щу — с у, как бы их ни произносили. А там, где "
        "безударная гласная или парная согласная вызывает сомнение, нужно подобрать проверочное "
        "слово — такое, где эта буква окажется под ударением или перед гласной. «Не доверяй слуху, "
        "— предупреждает Архип Кузьмич, — проверяй правилом»."
    ),
    "questions": [
        {
            "text": "Восстанови пропущенную букву: маш...на.",
            "options": ["и", "ы", "е", "я"],
            "correct": 0,
            "hint": "Вспомни правило жи-ши.",
            "explanation": "Сочетание «ши» всегда пишется с буквой и: машина. Правило жи-ши не зависит от произношения."
        },
        {
            "text": "Восстанови букву: ч...шка (посуда).",
            "options": ["у", "ю", "а", "я"],
            "correct": 2,
            "hint": "Вспомни правило ча-ща.",
            "explanation": "Сочетание «ча» всегда пишется с буквой а: чашка."
        },
        {
            "text": "Какое слово — проверочное для безударной гласной в слове «л...сной» (от слова «лес»)?",
            "options": ["лису", "лес", "лестница", "лесть"],
            "correct": 1,
            "hint": "Проверочное слово — то, где сомнительная гласная становится ударной.",
            "explanation": "«Лесной» проверяется словом «лес» — гласная «е» здесь под ударением. Значит, пишем «лесной»."
        },
        {
            "text": "Проверь слово «моро_» — какую букву нужно писать на конце?",
            "options": ["с", "з", "ц", "ш"],
            "correct": 1,
            "hint": "Подбери проверочное слово, где после сомнительной согласной стоит гласная: морозы, морозный.",
            "explanation": "Проверочное слово «морозы» — после «з» стоит гласная, звук слышен чётко. Значит, пишем «мороз» с буквой з, хотя на конце слышится «с»."
        },
        {
            "text": "В слове «гла...кий» (ровный, без шероховатостей) определи пропущенную согласную, подобрав проверочное слово.",
            "options": ["т", "д", "тт", "дд"],
            "correct": 1,
            "hint": "Подбери слово, где после сомнительной согласной идёт гласная: «гладок», «гладенький».",
            "explanation": "Проверочное слово «гладок» — после согласной идёт гласная «о», звук слышен чётко: это «д». Значит, пишем «гладкий», хотя слышится глухой звук."
        }
    ],
    "boss_task": {
        "answer": "сторожил",
        "text": (
            "Архип Кузьмич показывает размытую от воды строку: «Ст...рожил зд...ние ноч?ю». Первое "
            "слово пропущено — «ст_рожил» (охранял). Проверь безударную гласную и восстанови слово "
            "целиком."
        ),
        "solution": (
            "Ответ: сторожил. Безударная гласная в корне проверяется словом «сторож» — там она под "
            "ударением, значит, пишем «о»: сторожил."
        ),
        "hint1": "Подбери однокоренное слово, где сомнительная гласная окажется под ударением.",
        "hint2": "Проверочное слово — «сторож» (человек, который сторожит).",
    },
    "coins_lesson": 58,
    "coins_boss": 38,
}

LESSON_RU_PARTS_OF_SPEECH = {
    "topic": "§ 5. Части речи",
    "context_theme": "newsroom",
    "explanation": (
        "Часть речи — это группа слов, объединённых общим значением, вопросом и грамматическими "
        "признаками. Самостоятельные части речи называют предметы, признаки, действия и количество "
        "и могут быть членами предложения: имя существительное (предмет, кто? что?), имя "
        "прилагательное (признак предмета, какой?), глагол (действие, что делать?), имя числительное "
        "(количество, сколько?), местоимение (указывает на предмет или признак, не называя его), "
        "наречие (признак действия, как? когда?). Служебные части речи (предлог, союз, частица) не "
        "называют ничего сами по себе, а служат для связи слов и предложений или для оттенков "
        "смысла — и никогда не являются отдельными членами предложения."
    ),
    "explanation_game": (
        "Последнее испытание — картотечный ящик со старыми словами, вырезанными из разных заметок "
        "редакции, вперемешку, без единой системы. Архип Кузьмич просит разложить их по науке: "
        "самостоятельные части речи (существительное, прилагательное, глагол, числительное, "
        "местоимение, наречие) называют предметы, признаки, действия — и могут быть отдельными "
        "членами предложения. Служебные части речи (предлог, союз, частица) сами по себе ничего не "
        "называют, а только связывают слова и предложения между собой — быть отдельным членом "
        "предложения они не могут. Разложи слова верно — и Архип Кузьмич, довольный тем, как ты "
        "прошёл проверку по всем пяти испытаниям, вручит тебе ключ от главного архива редакции: "
        "пришло время учиться работать не только с текстами, но и с самими посетителями «Вечернего "
        "вестника»."
    ),
    "questions": [
        {
            "text": "Какое слово — имя существительное?",
            "options": ["редакция", "старый", "писать", "быстро"],
            "correct": 0,
            "hint": "Существительное отвечает на вопрос кто? или что? и называет предмет.",
            "explanation": "«Редакция» называет предмет и отвечает на вопрос «что?» — это существительное. «Старый» — прилагательное, «писать» — глагол, «быстро» — наречие."
        },
        {
            "text": "Какое слово — глагол?",
            "options": ["архивный", "хранение", "хранил", "бережно"],
            "correct": 2,
            "hint": "Глагол отвечает на вопрос что делал? что сделал? и называет действие.",
            "explanation": "«Хранил» отвечает на вопрос «что делал?» и называет действие — это глагол. «Хранение» — существительное, «архивный» — прилагательное, «бережно» — наречие."
        },
        {
            "text": "В предложении «Он бережно открыл старую тетрадь» найди местоимение.",
            "options": ["он", "бережно", "старую", "тетрадь"],
            "correct": 0,
            "hint": "Местоимение указывает на предмет, не называя его напрямую (он, она, это, кто-то).",
            "explanation": "«Он» указывает на человека, не называя его по имени, — это местоимение. Остальные слова — наречие, прилагательное и существительное."
        },
        {
            "text": "Какое слово из перечисленных — служебная часть речи (не может быть членом предложения)?",
            "options": ["редактор", "и", "хранил", "старинный"],
            "correct": 1,
            "hint": "Служебные части речи не называют предметы, признаки или действия — они только связывают слова.",
            "explanation": "«И» — союз, служебная часть речи: он ничего не называет, а только связывает слова или предложения, поэтому не может быть отдельным членом предложения. Остальные слова — самостоятельные части речи."
        },
        {
            "text": "В предложении «Пять сотрудников быстро разобрали старый архив» найди имя числительное и определи, что оно обозначает.",
            "options": [
                "«старый» — признак предмета",
                "«пять» — количество предметов",
                "«быстро» — признак действия",
                "«архив» — предмет"
            ],
            "correct": 1,
            "hint": "Числительное отвечает на вопрос сколько? и называет количество.",
            "explanation": "«Пять» отвечает на вопрос «сколько?» и называет количество сотрудников — это числительное. Остальные варианты описывают другие части речи верно, но это не числительные."
        }
    ],
    "boss_task": {
        "answer": "6",
        "text": (
            "Архип Кузьмич даёт последнее задание: разложить по частям речи предложение из старой "
            "заметки: «Три опытных наборщика молча работали в цехе». Сколько в этом предложении "
            "самостоятельных частей речи (не считая служебных)?"
        ),
        "solution": (
            "Ответ: 6. Самостоятельные части речи: «три» (числительное), «опытных» (прилагательное), "
            "«наборщика» (существительное), «молча» (наречие), «работали» (глагол), «цехе» "
            "(существительное) — итого шесть. Слово «в» — предлог, служебная часть речи, в счёт не "
            "входит."
        ),
        "hint1": "Выпиши все слова предложения и определи часть речи каждого.",
        "hint2": "Не забудь, что предлог «в» — служебная часть речи, он не считается самостоятельной.",
    },
    "coins_lesson": 60,
    "coins_boss": 40,
}

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
    """)
    migrate_add_column(conn, "lessons", "topic_id", "INTEGER")
    migrate_add_column(conn, "lessons", "lesson_type", "TEXT DEFAULT 'quiz'")
    migrate_add_column(conn, "lessons", "slides", "TEXT")
    migrate_add_column(conn, "sections", "intro", "TEXT")
    migrate_add_column(conn, "sections", "intro_seen_at", "TEXT")
    migrate_add_column(conn, "articles", "cover_image", "TEXT")
    migrate_add_column(conn, "articles", "manually_edited", "INTEGER DEFAULT 0")
    seed_curriculum_if_empty(conn, 5, "math", MATH_5_CURRICULUM)
    seed_curriculum_if_empty(conn, 5, "russian", RUSSIAN_5_CURRICULUM)
    seed_section_intro_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", SECTION_INTRO_RU_REVIEW)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 1. Текст", LESSON_RU_TEXT)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 2. Словосочетание. Предложение", LESSON_RU_PHRASE_SENTENCE)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 3. Состав слова. Орфограмма", LESSON_RU_WORD_STRUCTURE)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 4. Правописание", LESSON_RU_SPELLING_BASICS)
    seed_lesson_if_missing(conn, 5, "russian", "Повторение изученного в начальных классах", "§ 5. Части речи", LESSON_RU_PARTS_OF_SPEECH)
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
