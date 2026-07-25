import os, re, json, asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends

from config import SUBJECT_LABELS
from db import get_conn
from auth import require_parent, require_any
from telegram_service import tg_send
from models.lessons import StartLessonIn, FinishLessonIn
from models.misc import MistakeIn

router = APIRouter(prefix="/api")


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


@router.post("/progress/start")
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

@router.post("/progress/finish")
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

@router.get("/progress")
def get_progress(role: str = Depends(require_any)):
    conn = get_conn()
    rows = conn.execute("""SELECT p.*, l.topic, l.subject FROM progress p
        LEFT JOIN lessons l ON p.lesson_id=l.id
        ORDER BY p.started_at DESC LIMIT 50""").fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Ошибки и материал для урока-закрепления ─────────────────────────────────

@router.post("/mistakes")
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

@router.get("/lessons/{lesson_id}/reinforcement-prompt")
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

@router.get("/mistakes")
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
