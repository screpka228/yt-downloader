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
    "container": "mp4",
    # Прокси: builtin (встроенный обход DPI), HTTP, SOCKS5 или off (без прокси)
    "proxy_mode": "off",  # встроенный обход включается пользователем или по запросу при сбое
    "proxy_host": "",
    "proxy_port": "",
    "proxy_user": "",
    "proxy_pass": "",
    # Встроенный прокси
    "dpi_port": 1080,
    "dpi_method": "tlsrec+split",
    "dpi_all_hosts": False,
    # Сеть
    "timeout": 20,  # секунд на одно соединение
    "retries": 3,  # сколько раз повторять при сбое
    # Обновления
    "auto_update_ytdlp": True,
    "check_app_update": True,
    # Дополнительно при загрузке
    "subs_langs": [],  # коды языков субтитров, пусто — без субтитров
    "subs_embed": False,
    "thumb_enabled": False,
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


def external_proxy_url(settings: dict) -> str:
    """Адрес внешнего HTTP или SOCKS5 прокси с логином и паролем. Пусто для других режимов."""
    mode = settings.get("proxy_mode")
    host = settings.get("proxy_host", "").strip()
    if mode not in ("HTTP", "SOCKS5") or not host:
        return ""
    scheme = "socks5" if mode == "SOCKS5" else "http"
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


def net_options(settings: dict, dpi_port: int | None = None) -> dict:
    """Сетевые настройки для yt-dlp и проверок.

    dpi_port — фактический порт запущенного встроенного прокси (None, если он не запущен).
    """
    if settings.get("proxy_mode") == "builtin":
        proxy = f"http://127.0.0.1:{dpi_port}" if dpi_port else ""
    else:
        proxy = external_proxy_url(settings)
    return {
        "proxy": proxy,
        "timeout": int(settings["timeout"]),
        "retries": int(settings["retries"]),
    }
