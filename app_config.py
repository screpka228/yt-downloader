"""Общие константы и пути приложения."""
import os
import sys
from pathlib import Path

APP_NAME = "YT Downloader"
APP_VERSION = "1.1.0"
GITHUB_REPO = "screpka228/yt-downloader"


def app_dir() -> Path:
    """Папка с программой (рядом с .exe). Здесь лежит settings.json."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Папка с файлами, вшитыми в .exe (иконка и т.п.)."""
    return Path(getattr(sys, "_MEIPASS", app_dir()))


def data_dir() -> Path:
    """Служебная папка в %APPDATA% (обновления yt-dlp, ffmpeg)."""
    base = Path(os.environ.get("APPDATA") or Path.home())
    path = base / "YTDownloader"
    path.mkdir(parents=True, exist_ok=True)
    return path
