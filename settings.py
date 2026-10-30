"""Настройки программы. Сохраняются в settings.json рядом с программой."""
import json
from pathlib import Path

from app_config import app_dir

SETTINGS_FILE = app_dir() / "settings.json"

DEFAULTS = {
    "download_dir": str(Path.home() / "Downloads"),
    "proxy": "",
    "mode": "Видео",
    "video_quality": 1080,
    "audio_format": "mp3 (320 kbps)",
}


def load_settings() -> dict:
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        # Файла нет или он повреждён — используем значения по умолчанию.
        pass
    return settings


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        # Например, программа лежит в защищённой папке. Тогда просто не сохраняем.
        pass
