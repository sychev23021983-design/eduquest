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

SUBJECT_LABELS = {
    "math":    "Математика",
    "russian": "Русский язык",
    "science": "Окружающий мир",
    "history": "История",
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

def seed_lesson_if_missing(conn, grade: int, subject: str, section_title: str, topic_title: str, lesson: dict):
    """Создаёт урок для темы (по названию раздела+темы), если у темы ещё нет ни одного активного урока."""
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
        (subject,grade,topic,topic_id,context_theme,explanation,explanation_game,questions,boss_task,coins_lesson,coins_boss)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (subject, grade, lesson["topic"], topic_id, lesson.get("context_theme", "detective"),
         lesson.get("explanation", ""), lesson.get("explanation_game", ""),
         json.dumps(lesson["questions"], ensure_ascii=False),
         json.dumps(lesson["boss_task"], ensure_ascii=False) if lesson.get("boss_task") else None,
         lesson.get("coins_lesson", 50), lesson.get("coins_boss", 30)))

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

**2. Действия с натуральными числами**

- **Сложение и вычитание:** свойства действий (переместительное, сочетательное) и их применение для упрощения вычислений.
- **Умножение и деление:** свойства умножения (включая распределительное); деление нацело и деление с остатком.
- **Степень числа:** понятие степени с натуральным показателем; квадрат и куб числа.
- **Порядок действий:** правила выполнения операций в числовых выражениях со скобками и без.

**3. Выражения и уравнения**

- **Числовые и буквенные выражения:** составление выражений по условию задачи и нахождение их значений при заданных переменных.
- **Уравнения:** понятия «уравнение» и «корень уравнения»; решение уравнений на основе зависимостей между компонентами действий.
- **Формулы:** использование буквенных формул (например, формулы пути s=v⋅t).

**4. Обыкновенные дроби**

- **Понятие дроби:** числитель и знаменатель; изображение дробей на координатном луче.
- **Виды дробей:** правильные и неправильные дроби; понятие смешанного числа.
- **Основное свойство дроби:** сокращение дробей и приведение их к новому знаменателю.
- **Действия с дробями:** сравнение, сложение и вычитание дробей с одинаковыми знаменателями; действия со смешанными числами; умножение и деление дробей.
- **Задачи на дроби:** нахождение части от числа, нахождение числа по его части и определение дробного отношения двух чисел.

**5. Геометрические фигуры и величины**

- **Основные объекты:** точка, прямая, луч, отрезок, плоскость.
- **Измерения:** измерение длины отрезка; единицы измерения длины.
- **Ломаная и многоугольники:** вершины, стороны, понятие периметра многоугольника.
- **Углы:** виды углов (острый, прямой, тупой, развернутый); измерение и построение углов с помощью транспортира.
- **Взаимное расположение прямых:** параллельные и перпендикулярные прямые.
- **Площадь:** формулы площади прямоугольника и квадрата; площадь прямоугольного треугольника; единицы измерения площади (ар, гектар).
- **Объем:** прямоугольный параллелепипед и куб; площадь поверхности и объем; единицы измерения объема.

**6. Анализ данных и текстовые задачи**

- **Работа с информацией:** представление данных в таблицах и столбчатых диаграммах.
- **Среднее арифметическое:** нахождение среднего значения нескольких чисел.
- **Типовые задачи:** задачи на движение (встречное, в противоположных направлениях, по течению и против течения реки); задачи на взвешивание и переливание.
"""

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
    """)
    migrate_add_column(conn, "lessons", "topic_id", "INTEGER")
    migrate_add_column(conn, "sections", "intro", "TEXT")
    migrate_add_column(conn, "sections", "intro_seen_at", "TEXT")
    seed_curriculum_if_empty(conn, 5, "math", MATH_5_CURRICULUM)
    seed_section_intro_if_missing(conn, 5, "math", "Натуральные числа", SECTION_INTRO_NATURAL_NUMBERS)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Цифры и натуральные числа", LESSON_NATURAL_DIGITS)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Сравнение натуральных чисел", LESSON_NATURAL_COMPARE)
    seed_lesson_if_missing(conn, 5, "math", "Натуральные числа", "Округление чисел", LESSON_ROUNDING)
    conn.commit()
    conn.close()

# ── Telegram ──────────────────────────────────────────────────────────────────

async def tg_send(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID",   "")
    if not token or not chat or token == "YOUR_BOT_TOKEN_HERE":
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            )
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
                "SELECT id, topic FROM lessons WHERE topic_id=? AND active=1 ORDER BY created_at", (t["id"],)
            ).fetchall()
            lesson_ids = [l["id"] for l in t_lessons]
            completed = False
            if lesson_ids:
                placeholders = ",".join("?" * len(lesson_ids))
                cnt = conn.execute(
                    f"SELECT COUNT(*) as n FROM progress WHERE lesson_id IN ({placeholders}) AND finished_at IS NOT NULL",
                    lesson_ids
                ).fetchone()["n"]
                completed = cnt > 0
            topic_list.append({
                **dict(t),
                "lessons": [dict(l) for l in t_lessons],
                "lesson_count": len(t_lessons),
                "completed": completed,
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
    q, params = "SELECT * FROM lessons WHERE active=1", []
    if subject:
        q += " AND subject=?"; params.append(subject)
    if topic_id:
        q += " AND topic_id=?"; params.append(topic_id)
    rows = conn.execute(q + " ORDER BY created_at DESC", params).fetchall()
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

# ── Progress ──────────────────────────────────────────────────────────────────

class StartLessonIn(BaseModel):
    lesson_id: int

class FinishLessonIn(BaseModel):
    progress_id: int
    score: int
    boss_done: bool = False

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
    # Монеты за урок пропорциональны результату
    # 5/5 = 100%, 4/5 = 80%, ..., 0/5 = 10% (минимум за попытку)
    max_score = 5
    ratio = max(data.score / max_score, 0.1) if max_score > 0 else 0.1
    base_coins = lesson["coins_lesson"] if lesson else 50
    lesson_coins = max(round(base_coins * ratio), 5)  # минимум 5 монет
    boss_coins = (lesson["coins_boss"] if lesson else 30) if data.boss_done else 0
    coins = lesson_coins + boss_coins
    conn.execute("UPDATE progress SET finished_at=datetime('now'),score=?,boss_done=?,coins_earned=? WHERE id=?",
                 (data.score, 1 if data.boss_done else 0, coins, data.progress_id))
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
    return {"coins_earned": coins}

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
    weak    = conn.execute("""SELECT l.topic, l.subject, AVG(p.score*1.0/p.max_score) as avg, COUNT(*) as attempts
        FROM progress p JOIN lessons l ON p.lesson_id=l.id WHERE p.finished_at IS NOT NULL
        GROUP BY l.id HAVING avg < 0.6 AND attempts >= 1 ORDER BY avg ASC LIMIT 5""").fetchall()
    conn.close()
    return {
        "total_lessons": total, "balance": earned - spent,
        "total_coins_earned": earned, "streak_days": streak["days"] if streak else 0,
        "avg_score": round(avg_row["a"] * 100) if avg_row["a"] else 0,
        "by_subject": [dict(r) for r in by_subj],
        "week_activity": [dict(r) for r in week],
        "weak_topics": [dict(r) for r in weak],
    }

# ── Coins & Rewards ───────────────────────────────────────────────────────────

@app.get("/api/coins/balance")
def get_balance(role: str = Depends(require_any)):
    conn = get_conn()
    earned = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM coins WHERE type='earned'").fetchone()["s"]
    spent  = conn.execute("SELECT COALESCE(SUM(cost_coins),0) as s FROM rewards WHERE status='approved'").fetchone()["s"]
    conn.close()
    return {"balance": earned - spent, "earned": earned, "spent": spent}

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
    conn.commit(); conn.close()
    child = os.environ.get("CHILD_NAME", "Тимофей")
    asyncio.create_task(tg_send(
        f"🎁 <b>{child} запрашивает награду!</b>\n"
        f"{data.name} · {data.cost_coins} монет 🪙\n"
        f"http://147.45.42.169:8090"
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
