"""Обновления и вспомогательные файлы: yt-dlp (PyPI), программа (GitHub Releases), ffmpeg.

Важно: модуль не импортирует yt_dlp, чтобы можно было подменить библиотеку до импорта.
"""
import importlib.machinery
import importlib.metadata
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

import requests

from app_config import APP_VERSION, GITHUB_REPO, data_dir

TIMEOUT = 10
YTDLP_ROOT = data_dir() / "ytdlp"
FFMPEG_DIR = data_dir() / "ffmpeg"


def parse_version(text: str) -> tuple:
    """'2025.10.22' -> (2025, 10, 22), '1.2.0' -> (1, 2, 0)."""
    return tuple(int(part) for part in re.findall(r"\d+", text))


def _bundled_ytdlp_version() -> str:
    """Версия yt-dlp, которая вшита в программу (или установлена через pip)."""
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return "0"


def _newest_override() -> Path | None:
    """Самая новая скачанная версия yt-dlp, если она новее вшитой. Иначе None."""
    if not YTDLP_ROOT.exists():
        return None
    best, best_ver = None, parse_version(_bundled_ytdlp_version())
    for folder in YTDLP_ROOT.iterdir():
        if (folder / "yt_dlp" / "__init__.py").exists():
            ver = parse_version(folder.name)
            if ver > best_ver:
                best, best_ver = folder, ver
    return best


def _current_ytdlp_version() -> tuple:
    newest = _newest_override()
    return parse_version(newest.name) if newest else parse_version(_bundled_ytdlp_version())


def install_ytdlp_override() -> None:
    """Подключает скачанную более новую yt-dlp вместо вшитой.

    Вызывать ДО первого импорта yt_dlp. Старые скачанные версии удаляются.
    """
    newest = _newest_override()
    if YTDLP_ROOT.exists():
        for folder in YTDLP_ROOT.iterdir():
            if folder != newest:
                shutil.rmtree(folder, ignore_errors=True)
    if newest is None:
        return

    root = str(newest)

    class _OverrideFinder:
        """Заставляет Python брать модули yt_dlp из скачанной папки, а не из .exe."""

        @staticmethod
        def find_spec(fullname, path=None, target=None):
            if fullname != "yt_dlp" and not fullname.startswith("yt_dlp."):
                return None
            if fullname == "yt_dlp":
                search = [root]
            else:
                search = sys.modules[fullname.rpartition(".")[0]].__path__
            return importlib.machinery.PathFinder.find_spec(fullname, search)

    sys.meta_path.insert(0, _OverrideFinder)


def _latest_ytdlp_wheel() -> tuple[str, str]:
    resp = requests.get("https://pypi.org/pypi/yt-dlp/json", timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    for file in data["urls"]:
        if file["filename"].endswith("-py3-none-any.whl"):
            return data["info"]["version"], file["url"]
    raise RuntimeError("не найден файл установки yt-dlp")


def download_newer_ytdlp() -> str | None:
    """Скачивает yt-dlp с PyPI, если там версия новее текущей.

    Возвращает новую версию или None, если обновление не понадобилось.
    Новая версия начнёт работать после перезапуска программы.
    """
    latest, url = _latest_ytdlp_wheel()
    if parse_version(latest) <= _current_ytdlp_version():
        return None

    blob = requests.get(url, timeout=60).content
    YTDLP_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = YTDLP_ROOT / f"{latest}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = [name for name in archive.namelist() if name.startswith("yt_dlp/")]
        archive.extractall(tmp, members=members)

    target = YTDLP_ROOT / latest
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return latest


def update_ytdlp_at_startup() -> None:
    """Тихо обновляет yt-dlp при запуске. Нет сети — работаем с тем, что есть."""
    try:
        download_newer_ytdlp()
    except Exception:
        # Любая ошибка сети или файлов не должна мешать запуску программы.
        pass


def check_app_update() -> tuple[str, str] | None:
    """Ищет новый релиз программы на GitHub. Возвращает (версия, ссылка) или None."""
    resp = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json"},
        timeout=TIMEOUT,
    )
    if resp.status_code == 404:  # релизов ещё нет
        return None
    resp.raise_for_status()
    data = resp.json()
    latest = data.get("tag_name", "").lstrip("vV")
    if latest and parse_version(latest) > parse_version(APP_VERSION):
        return latest, data["html_url"]
    return None


def ensure_ffmpeg() -> str | None:
    """Копирует ffmpeg из пакета imageio-ffmpeg в папку данных. Возвращает путь к папке."""
    try:
        import imageio_ffmpeg

        source = Path(imageio_ffmpeg.get_ffmpeg_exe())
        FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
        target = FFMPEG_DIR / "ffmpeg.exe"
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
        return str(FFMPEG_DIR)
    except Exception:
        # Без ffmpeg yt-dlp попробует найти его в системе; иначе покажем ошибку при загрузке.
        return None
