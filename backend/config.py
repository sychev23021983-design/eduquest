import os

# Конфигурация из переменных окружения — общие константы, на которые опираются
# db.py (DB_PATH), auth.py (SECRET_KEY) и роутеры (UPLOAD_DIR, SUBJECT_LABELS).
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
