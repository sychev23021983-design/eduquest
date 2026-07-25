import sqlite3, re, json

from config import DB_PATH

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
