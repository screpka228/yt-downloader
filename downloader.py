"""Работа с yt-dlp: получение информации о ссылке и загрузка файлов."""
import threading
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import YoutubeDLError

VIDEO_HEIGHTS = [2160, 1440, 1080, 720, 480, 360]
# Название для меню -> (кодек для ffmpeg, битрейт или None)
AUDIO_FORMATS = {
    "mp3 (320 kbps)": ("mp3", "320"),
    "m4a": ("m4a", None),
    "opus": ("opus", None),
}


class Cancelled(Exception):
    """Загрузку отменил пользователь."""


class UserError(Exception):
    """Ошибка с понятным текстом для пользователя."""


@dataclass
class VideoInfo:
    url: str
    title: str
    is_playlist: bool
    count: int
    duration: int | None
    heights: list[int]
    thumbnail: str | None


@dataclass
class Progress:
    percent: float | None
    speed: float | None
    eta: int | None
    stage: str


@dataclass
class Job:
    url: str
    mode: str  # "video" или "audio"
    out_dir: str
    proxy: str
    height: int = 1080
    audio_format: str = "mp3 (320 kbps)"
    status: str = "waiting"  # waiting, running, done, error, cancelled
    message: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)


def _base_opts(proxy: str, ffmpeg_dir: str | None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": ffmpeg_dir,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
    }
    if proxy:
        opts["proxy"] = proxy
    return opts


def translate_error(exc: Exception) -> str:
    """Переводит техническую ошибку yt-dlp в понятное сообщение на русском."""
    text = str(exc).lower()
    rules = [
        (("unsupported url",),
         "Неверная или не поддерживаемая ссылка."),
        # Это правило должно идти раньше «not available», иначе совпадёт и там.
        (("requested format is not available",),
         "Для этого видео нет выбранного качества. Выберите качество пониже."),
        (("video unavailable", "not available", "has been removed", "removed by"),
         "Видео недоступно: оно удалено, скрыто или не открывается в вашем регионе."),
        (("private video", "sign in", "login required", "members only", "confirm your age"),
         "Видео закрытое или требует входа в аккаунт (возрастное ограничение). Такие видео программа пока не скачивает."),
        (("http error 403", "http error 429", "too many requests"),
         "Сервер временно ограничил доступ (403/429). Подождите немного или смените прокси."),
        (("unable to download webpage", "getaddrinfo", "name or service not known",
          "network is unreachable", "timed out", "temporary failure", "failed to resolve",
          "connection", "proxy", "no route to host"),
         "Нет подключения к интернету, сервер недоступен или прокси не работает."),
        (("ffmpeg", "ffprobe"),
         "Не найден ffmpeg, без него нельзя склеить или конвертировать файл. Перезапустите программу."),
    ]
    for keys, message in rules:
        if any(key in text for key in keys):
            return message
    return f"Ошибка загрузки: {exc}"


def quality_choices(heights: list[int]) -> list[int]:
    """Список качеств для меню: стандартные, не выше максимума, который есть у видео."""
    if not heights:
        return list(VIDEO_HEIGHTS)
    top = heights[0]
    return [h for h in VIDEO_HEIGHTS if h <= top] or [top]


def fetch_info(url: str, proxy: str, ffmpeg_dir: str | None) -> VideoInfo:
    """Получает название, длительность, превью и доступные качества без скачивания."""
    opts = _base_opts(proxy, ffmpeg_dir) | {"skip_download": True, "extract_flat": "in_playlist"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except YoutubeDLError as exc:
        raise UserError(translate_error(exc)) from exc

    if info is None:
        raise UserError("Не удалось получить данные по этой ссылке.")

    if info.get("_type") in ("playlist", "multi_video"):
        entries = [entry for entry in info.get("entries") or [] if entry]
        thumb = info.get("thumbnail") or next(
            (entry.get("thumbnail") for entry in entries if entry.get("thumbnail")), None
        )
        return VideoInfo(url, info.get("title") or "Плейлист", True, len(entries), None, [], thumb)

    heights = sorted(
        {
            f["height"]
            for f in info.get("formats") or []
            if f.get("height") and f.get("vcodec") != "none"
        },
        reverse=True,
    )
    return VideoInfo(
        url,
        info.get("title") or "Без названия",
        False,
        1,
        info.get("duration"),
        heights,
        info.get("thumbnail"),
    )


class _ArtistFromUploader(PostProcessor):
    """Если исполнитель не указан, в тег исполнителя пишем название канала."""

    def run(self, info):
        if not info.get("artist") and info.get("uploader"):
            info["artist"] = info["uploader"]
        return [], info


def _make_hook(job: Job, on_progress):
    def hook(data: dict):
        if job.cancel.is_set():
            raise Cancelled()
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            done = data.get("downloaded_bytes") or 0
            percent = done * 100 / total if total else None
            on_progress(Progress(percent, data.get("speed"), data.get("eta"), "Загрузка"))
        elif status == "finished":
            on_progress(Progress(100.0, None, None, "Обработка (склейка и конвертация)"))

    return hook


def run_job(job: Job, ffmpeg_dir: str | None, on_progress) -> None:
    """Скачивает видео или плейлист. Блокирующая функция, вызывать из отдельного потока."""
    out_dir = Path(job.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Для плейлиста создаётся подпапка с его названием, для одного видео — нет.
    template = "%(playlist_title&{}/|)s%(playlist_index&{} - |)s%(title)s.%(ext)s"

    opts = _base_opts(job.proxy, ffmpeg_dir) | {
        "outtmpl": str(out_dir / template),
        "progress_hooks": [_make_hook(job, on_progress)],
        "windowsfilenames": True,
    }

    if job.mode == "video":
        opts |= {
            "format": f"bv*[height<={job.height}]+ba/b[height<={job.height}]",
            # Для 4K mp4 не всегда подходит (кодеки VP9/Opus), тогда yt-dlp сохранит mkv.
            "merge_output_format": "mp4/mkv",
        }
    else:
        codec, bitrate = AUDIO_FORMATS[job.audio_format]
        extract = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if bitrate:
            extract["preferredquality"] = bitrate
        opts |= {
            "format": "ba/b",
            "writethumbnail": True,
            "postprocessors": [
                extract,
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail"},
            ],
        }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if job.mode == "audio":
                ydl.add_post_processor(_ArtistFromUploader(), when="pre_process")
            ydl.download([job.url])
    except YoutubeDLError as exc:
        raise UserError(translate_error(exc)) from exc
