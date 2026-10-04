"""Attach reviewed skill images without altering task text or existing images.

Run inside the backend container; the manifest and images must be staged first.
The default is a dry run. --apply creates a SQLite backup before any writes.
"""
import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    database = Path(os.environ.get("DB_PATH", "/app/data/eduquest.db"))
    uploads = Path(os.environ.get("UPLOAD_DIR", "/app/data/uploads"))
    conn = sqlite3.connect(database)
    try:
        conn.row_factory = sqlite3.Row
        pending = []
        for item in rows:
            image = uploads / "images" / f"skill-{item['id']}.png"
            if not image.is_file():
                continue
            if image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError(f"Invalid PNG for skill {item['id']}")
            current = conn.execute("SELECT * FROM skills WHERE id=?", (item["id"],)).fetchone()
            if not current or not current["active"] or current["content"] != item["content"] or current["category_id"] != item["category_id"]:
                raise RuntimeError(f"Task changed since manifest: {item['id']}")
            expected = f"/uploads/images/skill-{item['id']}.png"
            if current["image_url"] == expected:
                continue
            if current["image_url"]:
                raise RuntimeError(f"Existing image will not be replaced: {item['id']}")
            pending.append((expected, item["id"], item["content"]))
        print(json.dumps({"manifest": len(rows), "pending": len(pending), "apply": args.apply}))
        if args.apply and pending:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = database.with_name(f"eduquest.before-skill-images-{stamp}.db")
            backup = sqlite3.connect(backup_path)
            conn.backup(backup)
            backup.close()
            with conn:
                for url, skill_id, content in pending:
                    changed = conn.execute("UPDATE skills SET image_url=? WHERE id=? AND content=? AND coalesce(image_url,'')=''", (url, skill_id, content)).rowcount
                    if changed != 1:
                        raise RuntimeError(f"Concurrent edit: {skill_id}")
            print(json.dumps({"updated": len(pending), "backup": str(backup_path), "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0]}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
