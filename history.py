"""История загрузок. Хранится в history.json рядом с программой."""
import json
from datetime import datetime

from app_config import app_dir

HISTORY_FILE = app_dir() / "history.json"
MAX_ITEMS = 500


def load_history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def add_history(url: str, folder: str, kind: str) -> None:
    items = load_history()
    items.insert(0, {
        "url": url,
        "folder": folder,
        "kind": kind,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
    })
    try:
        HISTORY_FILE.write_text(json.dumps(items[:MAX_ITEMS], ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # Не критично: загрузка уже готова, просто не запишем в историю.
        pass


def clear_history() -> None:
    try:
        HISTORY_FILE.write_text("[]", encoding="utf-8")
    except OSError:
        pass
