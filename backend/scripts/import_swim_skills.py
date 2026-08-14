#!/usr/bin/env python3
"""Импортирует учебный контент Swim-trainer в раздел «Навыки» Eduquest.

По умолчанию выполняется только проверка. Для внесения изменений нужен флаг
--apply. Перед записью автоматически создаётся резервная копия базы Eduquest.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


EXPECTED_COUNTS = {"brain": 168, "creative": 8, "facts": 91}
CATEGORY_TITLES = {
    "brain": "Блок 2. Мозг",
    "creative": "Блок 3. Творчество",
    "facts": "Блок 4. Познавательно",
}


def text(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def source_rows(conn: sqlite3.Connection) -> dict[str, list[dict[str, str | int | None]]]:
    brain = [
        {
            "source_table": "exercises",
            "source_id": row["id"],
            "content": text(row["title"], row["instructions"]),
            "hint1": row["tips"],
            "answer": row["swim_benefit"],
        }
        for row in conn.execute(
            """
            SELECT id, title, instructions, tips, swim_benefit
            FROM exercises
            WHERE active=1 AND category LIKE 'brain_%'
            ORDER BY id
            """
        )
    ]
    creative = [
        {
            "source_table": "creative_tasks",
            "source_id": row["id"],
            "content": text(row["title"], row["description"]),
            "hint1": None,
            "answer": None,
        }
        for row in conn.execute(
            "SELECT id, title, description FROM creative_tasks WHERE active=1 ORDER BY id"
        )
    ]
    facts = [
        {
            "source_table": "facts",
            "source_id": row["id"],
            "content": text(row["title"], row["body"]),
            "hint1": None,
            "answer": None,
        }
        for row in conn.execute(
            "SELECT id, title, body FROM facts WHERE active=1 ORDER BY id"
        )
    ]
    return {"brain": brain, "creative": creative, "facts": facts}


def require_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(skills)")}
    if "content" not in columns:
        raise RuntimeError("В Eduquest ещё нет поля content. Сначала разверните новую версию приложения.")


def ensure_category(conn: sqlite3.Connection, title: str, order_index: int) -> int:
    row = conn.execute("SELECT id FROM skill_categories WHERE title=?", (title,)).fetchone()
    if row:
        conn.execute("UPDATE skill_categories SET active=1 WHERE id=?", (row[0],))
        return row[0]
    cursor = conn.execute(
        "INSERT INTO skill_categories (title, order_index, active) VALUES (?,?,1)",
        (title, order_index),
    )
    return cursor.lastrowid


def import_content(source_path: Path, target_path: Path, apply: bool) -> None:
    if not source_path.is_file():
        raise FileNotFoundError(f"Не найдена база Swim-trainer: {source_path}")
    if not target_path.is_file():
        raise FileNotFoundError(f"Не найдена база Eduquest: {target_path}")

    with sqlite3.connect(source_path) as source:
        source.row_factory = sqlite3.Row
        batches = source_rows(source)

    for name, expected in EXPECTED_COUNTS.items():
        actual = len(batches[name])
        if actual != expected:
            raise RuntimeError(f"{name}: ожидалось {expected} записей, найдено {actual}. Импорт остановлен.")

    if not apply:
        print("Проверка пройдена. Будут импортированы:")
        for name, rows in batches.items():
            print(f"  {CATEGORY_TITLES[name]}: {len(rows)}")
        print("Изменения не внесены. Повторите команду с --apply.")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = target_path.with_name(f"{target_path.stem}.before-swim-import-{stamp}{target_path.suffix}")
    shutil.copy2(target_path, backup_path)
    print(f"Резервная копия: {backup_path}")

    with sqlite3.connect(target_path) as target:
        target.row_factory = sqlite3.Row
        require_schema(target)
        target.execute("BEGIN IMMEDIATE")
        target.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_import_log (
                source_app TEXT NOT NULL,
                source_table TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                skill_id INTEGER NOT NULL,
                imported_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (source_app, source_table, source_id)
            )
            """
        )

        for index, (name, rows) in enumerate(batches.items(), start=2):
            category_id = ensure_category(target, CATEGORY_TITLES[name], index)
            max_order = target.execute(
                "SELECT COALESCE(MAX(order_index), 0) FROM skills WHERE category_id=?", (category_id,)
            ).fetchone()[0]
            added = skipped = 0
            for row in rows:
                exists = target.execute(
                    """
                    SELECT 1 FROM skill_import_log
                    WHERE source_app='swim-trainer' AND source_table=? AND source_id=?
                    """,
                    (row["source_table"], row["source_id"]),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                max_order += 1
                cursor = target.execute(
                    """
                    INSERT INTO skills (category_id, content, hint1, answer, order_index, active)
                    VALUES (?,?,?,?,?,1)
                    """,
                    (category_id, row["content"], row["hint1"], row["answer"], max_order),
                )
                target.execute(
                    """
                    INSERT INTO skill_import_log (source_app, source_table, source_id, skill_id)
                    VALUES ('swim-trainer',?,?,?)
                    """,
                    (row["source_table"], row["source_id"], cursor.lastrowid),
                )
                added += 1
            print(f"{CATEGORY_TITLES[name]}: добавлено {added}, уже было импортировано {skipped}")

        target.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Путь к data/swim.db")
    parser.add_argument("--target", type=Path, required=True, help="Путь к data/eduquest.db")
    parser.add_argument("--apply", action="store_true", help="Выполнить импорт после проверки")
    args = parser.parse_args()
    import_content(args.source, args.target, args.apply)


if __name__ == "__main__":
    main()
