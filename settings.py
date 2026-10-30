"""Настройки программы. Сохраняются в settings.json рядом с программой."""
import json
from pathlib import Path
from urllib.parse import quote

from app_config import app_dir

SETTINGS_FILE = app_dir() / "settings.json"

DEFAULTS = {
    # Загрузка
    "download_dir": str(Path.home() / "Downloads"),
    "mode": "Видео",
    "video_quality": 1080,
    "audio_format": "mp3 (320 kbps)",
    # Прокси
    "proxy_enabled": False,
    "proxy_type": "HTTP",  # HTTP или SOCKS5
    "proxy_host": "",
    "proxy_port": "",
    "proxy_user": "",
    "proxy_pass": "",
    # Сеть
    "timeout": 20,  # секунд на одно соединение
    "retries": 3,  # сколько раз повторять при сбое
    # Обновления
    "auto_update_ytdlp": True,
    "check_app_update": True,
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


def proxy_url(settings: dict) -> str:
    """Собирает адрес прокси вида http://логин:пароль@хост:порт. Пусто, если прокси выключен."""
    host = settings.get("proxy_host", "").strip()
    if not settings.get("proxy_enabled") or not host:
        return ""
    scheme = "socks5" if settings.get("proxy_type") == "SOCKS5" else "http"
    auth = ""
    user = settings.get("proxy_user", "")
    if user:
        auth = quote(user, safe="")
        password = settings.get("proxy_pass", "")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    port = settings.get("proxy_port", "")
    return f"{scheme}://{auth}{host}" + (f":{port}" if port else "")


def net_options(settings: dict) -> dict:
    """Сетевые настройки для yt-dlp и проверки соединения."""
    return {
        "proxy": proxy_url(settings),
        "timeout": int(settings["timeout"]),
        "retries": int(settings["retries"]),
    }
