"""Главное окно программы (customtkinter): боковая панель и страницы."""
import queue
import re
import threading
import time
import urllib.request
import webbrowser
from io import BytesIO
from tkinter import filedialog, messagebox

import customtkinter as ctk
import requests
import yt_dlp
from PIL import Image

import deps
import downloader
from app_config import APP_NAME, APP_VERSION, GITHUB_REPO, resource_dir
from downloader import AUDIO_FORMATS, VIDEO_HEIGHTS, Job, UserError
from settings import load_settings, net_options, save_settings

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Палитра: все цвета собраны здесь, чтобы менять оформление в одном месте.
BG = "#0b0d14"
SIDEBAR = "#10131d"
CARD = "#161a29"
CARD_HI = "#1e2338"
FIELD = "#0e1120"
BORDER = "#252b45"
ACCENT = "#7c5cff"
ACCENT_HI = "#6a48f0"
TEXT = "#eef0f8"
MUTED = "#8b92ad"
OK = "#34d399"
ERR = "#f87171"
BUSY = "#60a5fa"
DANGER = "#7f1d1d"
DANGER_HI = "#991b1b"
RADIUS = 16
TEST_URL = "https://www.youtube.com/generate_204"
PROXY_HELP = (
    "Прокси — это посредник: ваши запросы идут через его сервер. "
    "Помогает, если YouTube недоступен или сильно ограничивает скорость.\n\n"
    "Где взять прокси:\n"
    "1. Платные прокси-сервисы. Ищите по запросам «residential proxy» или «datacenter proxy». "
    "Обычно вы покупаете пакет и получаете адрес, порт, логин и пароль. Их и вводите в поля.\n"
    "2. Свой сервер (VPS) с SOCKS5 или HTTP-прокси, если умеете его настроить.\n"
    "3. Бесплатные общедоступные прокси не рекомендуем: они часто медленные и нестабильные, "
    "а через них могут видеть ваши данные.\n\n"
    "Как заполнить: в поле «Адрес» — только IP или домен (например 1.2.3.4). "
    "В «Порт» — число (например 8080). Логин и пароль — только если провайдер их выдал."
)

MODE_VIDEO = "Видео"
MODE_AUDIO = "Музыка"
STATUS_TEXT = {
    "waiting": "в очереди",
    "running": "загружается",
    "done": "готово",
    "error": "ошибка",
    "cancelled": "отменено",
}
STATUS_COLOR = {"waiting": MUTED, "running": BUSY, "done": OK, "error": ERR, "cancelled": MUTED}


# ---------- Вспомогательные функции оформления ----------


def card(parent, **kwargs):
    return ctk.CTkFrame(
        parent, fg_color=CARD, corner_radius=RADIUS, border_width=1, border_color=BORDER, **kwargs
    )


def primary(parent, text, command, height=42, **kwargs):
    return ctk.CTkButton(
        parent, text=text, command=command, height=height, corner_radius=12,
        fg_color=ACCENT, hover_color=ACCENT_HI,
        font=ctk.CTkFont(size=14, weight="bold"), **kwargs,
    )


def ghost(parent, text, command, height=38, **kwargs):
    return ctk.CTkButton(
        parent, text=text, command=command, height=height, corner_radius=12,
        fg_color=CARD_HI, hover_color="#2a3152", text_color=TEXT,
        border_width=1, border_color=BORDER, font=ctk.CTkFont(size=13), **kwargs,
    )


def field(parent, height=38, **kwargs):
    return ctk.CTkEntry(
        parent, height=height, corner_radius=12, fg_color=FIELD,
        border_color=BORDER, text_color=TEXT, **kwargs,
    )


def option_menu(parent, values, width=170):
    return ctk.CTkOptionMenu(
        parent, values=values, width=width, height=38, corner_radius=12,
        fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HI,
        dropdown_fg_color=CARD_HI, dropdown_hover_color="#2a3152", text_color=TEXT,
    )


def segmented(parent, values, command=None, width=260):
    return ctk.CTkSegmentedButton(
        parent, values=values, command=command, width=width, height=38, corner_radius=12,
        fg_color=FIELD, selected_color=ACCENT, selected_hover_color=ACCENT_HI,
        unselected_color=FIELD, unselected_hover_color=CARD_HI, text_color=TEXT,
        font=ctk.CTkFont(size=13, weight="bold"),
    )


def heading(parent, title, subtitle):
    box = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(
        anchor="w"
    )
    ctk.CTkLabel(box, text=subtitle, font=ctk.CTkFont(size=14), text_color=MUTED).pack(
        anchor="w", pady=(2, 0)
    )
    return box


def caption(parent, text):
    return ctk.CTkLabel(
        parent, text=text.upper(), font=ctk.CTkFont(size=11, weight="bold"),
        text_color=MUTED, anchor="w",
    )


def chip(parent, text):
    return ctk.CTkLabel(
        parent, text=f"  {text}  ", fg_color=CARD_HI, corner_radius=8, height=26,
        text_color=TEXT, font=ctk.CTkFont(size=12),
    )


def format_speed(bytes_per_sec: float) -> str:
    return f"{bytes_per_sec / 1024 / 1024:.2f} МБ/с"


def format_eta(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_duration(seconds: int | None) -> str:
    return format_eta(seconds) if seconds else "—"


# ---------- Главное окно ----------


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1080x800")
        self.minsize(980, 720)
        self.configure(fg_color=BG)
        self._set_icon()

        self.events = queue.Queue()  # сообщения от фоновых потоков к окну
        self.jobs_queue = queue.Queue()  # задачи для рабочего потока
        self.jobs: list[Job] = []
        self.active_job: Job | None = None
        self.info = None
        self.thumb_image = None
        self.nav_buttons = {}
        self.pages = {}
        self.folder_var = ctk.StringVar(value=self.settings["download_dir"])
        self.ffmpeg_dir = deps.ensure_ffmpeg()

        self._build_shell()
        self._build_download_page()
        self._build_queue_page()
        self._build_settings_page()
        self._build_about_page()
        self._apply_settings()
        self.show_page("download")

        threading.Thread(target=self._worker, daemon=True).start()
        if self.settings["check_app_update"]:
            threading.Thread(target=self._check_app_update, daemon=True).start()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_icon(self):
        try:
            self.iconbitmap(str(resource_dir() / "icon.ico"))
        except Exception:
            # Иконки нет (например, при запуске из исходников) — ничего страшного.
            pass

    # ---------- Каркас: боковая панель и область страниц ----------

    def _build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=236, corner_radius=0, fg_color=SIDEBAR)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)

        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.pack(fill="x", padx=20, pady=(28, 28))
        ctk.CTkLabel(
            logo, text="▶", width=44, height=44, corner_radius=12, fg_color=ACCENT,
            text_color="white", font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            logo, text="YT Downloader", text_color=TEXT,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(side="left", padx=12)

        nav = [
            ("download", "⬇   Загрузка"),
            ("queue", "☰   Очередь"),
            ("settings", "⚙   Настройки"),
            ("about", "ⓘ   О программе"),
        ]
        for key, text in nav:
            button = ctk.CTkButton(
                side, text=text, anchor="w", height=46, corner_radius=12,
                fg_color="transparent", hover_color=CARD_HI, text_color=MUTED,
                font=ctk.CTkFont(size=15),
                command=lambda k=key: self.show_page(k),
            )
            button.pack(fill="x", padx=14, pady=3)
            self.nav_buttons[key] = button

        ctk.CTkLabel(
            side, text=f"yt-dlp {yt_dlp.version.__version__}",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        ).pack(side="bottom", pady=(0, 18))

        content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew", padx=28, pady=(24, 16))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.content = content

        self.status_label = ctk.CTkLabel(
            content, text="Готово к работе", text_color=MUTED, anchor="w",
            wraplength=760, justify="left", font=ctk.CTkFont(size=13),
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=4, pady=(10, 0))

    def _new_page(self, key):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = page
        return page

    def show_page(self, key):
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(
                fg_color=CARD_HI if active else "transparent",
                text_color=TEXT if active else MUTED,
            )

    def _status(self, text: str, kind: str = "info"):
        color = {"error": ERR, "ok": OK}.get(kind, MUTED)
        self.status_label.configure(text=text, text_color=color)

    # ---------- Страница «Загрузка» ----------

    def _build_download_page(self):
        page = self._new_page("download")
        page.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(page, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        heading(top, "Что скачаем?", "Вставьте ссылку на видео, Shorts или плейлист").grid(
            row=0, column=0, sticky="w"
        )
        self.mode_switch = segmented(top, [MODE_VIDEO, MODE_AUDIO], self._on_mode_change, 260)
        self.mode_switch.grid(row=0, column=1, sticky="e")

        url_card = card(page)
        url_card.grid(row=1, column=0, sticky="ew", pady=(22, 14))
        url_card.grid_columnconfigure(0, weight=1)
        self.url_entry = field(url_card, height=44, placeholder_text="https://www.youtube.com/watch?v=…")
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(18, 10), pady=18)
        ghost(url_card, "📋  Вставить", self._paste, height=44, width=140).grid(
            row=0, column=1, padx=(0, 10), pady=18
        )
        primary(url_card, "🔍  Получить форматы", self._fetch_clicked, height=44, width=210).grid(
            row=0, column=2, padx=(0, 18), pady=18
        )

        preview = card(page)
        preview.grid(row=2, column=0, sticky="ew")
        preview.grid_columnconfigure(1, weight=1)
        self.thumb_label = ctk.CTkLabel(
            preview, text="🎬", font=ctk.CTkFont(size=48), width=320, height=180,
            corner_radius=12, fg_color=FIELD, text_color=MUTED,
        )
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=18, pady=18)

        self.title_label = ctk.CTkLabel(
            preview, text="Здесь появится название и обложка",
            font=ctk.CTkFont(size=19, weight="bold"), text_color=TEXT,
            anchor="w", justify="left", wraplength=520,
        )
        self.title_label.grid(row=0, column=1, sticky="ew", padx=(6, 18), pady=(20, 6))

        self.chips_frame = ctk.CTkFrame(preview, fg_color="transparent")
        self.chips_frame.grid(row=1, column=1, sticky="w", padx=(6, 18))

        options = ctk.CTkFrame(preview, fg_color="transparent")
        options.grid(row=2, column=1, sticky="w", padx=(6, 18), pady=(14, 20))
        self.option_label = ctk.CTkLabel(options, text="Качество", text_color=MUTED)
        self.option_label.pack(side="left", padx=(0, 10))
        self.quality_menu = option_menu(options, [f"{h}p" for h in VIDEO_HEIGHTS], 160)
        self.audio_menu = option_menu(options, list(AUDIO_FORMATS), 200)

        folder = card(page)
        folder.grid(row=3, column=0, sticky="ew", pady=14)
        folder.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder, text="📁  Сохранять в", text_color=MUTED).grid(
            row=0, column=0, padx=(18, 10), pady=14
        )
        ctk.CTkLabel(
            folder, textvariable=self.folder_var, text_color=TEXT, anchor="w",
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=1, sticky="ew")
        ghost(folder, "Изменить", self._choose_folder, width=120).grid(
            row=0, column=2, padx=18, pady=14
        )

        primary(page, "＋  Добавить в очередь", self._add_to_queue, height=52).grid(
            row=4, column=0, sticky="ew", pady=(6, 0)
        )

    def _paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            # В буфере ничего нет или там не текст.
            self._status("В буфере обмена нет текста", "error")
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or None)
        if folder:
            self.folder_var.set(folder)
            self.settings["download_dir"] = folder
            save_settings(self.settings)

    def _on_mode_change(self, _value):
        self._show_options()

    def _show_options(self):
        is_video = self.mode_switch.get() == MODE_VIDEO
        self.option_label.configure(text="Качество" if is_video else "Формат")
        self.quality_menu.pack_forget()
        self.audio_menu.pack_forget()
        (self.quality_menu if is_video else self.audio_menu).pack(side="left")

    def _url(self) -> str:
        return self.url_entry.get().strip()

    def _valid_url(self, url: str) -> bool:
        if re.match(r"^https?://\S+$", url):
            return True
        self._status("Неверная ссылка: адрес должен начинаться с https://", "error")
        return False

    def _fetch_clicked(self):
        url = self._url()
        if not self._valid_url(url):
            return
        self._status("Получаю информацию о ссылке…")
        threading.Thread(
            target=self._fetch_preview, args=(url, net_options(self.settings)), daemon=True
        ).start()

    def _add_to_queue(self):
        url = self._url()
        if not self._valid_url(url):
            return
        out_dir = self.folder_var.get().strip()
        if not out_dir:
            self._status("Укажите папку для сохранения", "error")
            return
        job = Job(
            url=url,
            mode="video" if self.mode_switch.get() == MODE_VIDEO else "audio",
            out_dir=out_dir,
            net=net_options(self.settings),
            height=int(self.quality_menu.get().rstrip("p")),
            audio_format=self.audio_menu.get(),
        )
        self._remember_download()
        self.jobs.append(job)
        self.jobs_queue.put(job)
        self.url_entry.delete(0, "end")
        self._refresh_queue()
        self._status(f"Добавлено в очередь. Задач в списке: {len(self.jobs)}", "ok")
        self.show_page("queue")

    def _show_preview(self, info, thumb: bytes | None):
        self.info = info
        self.thumb_image = None
        if thumb:
            try:
                image = Image.open(BytesIO(thumb)).convert("RGB")
                self.thumb_image = ctk.CTkImage(light_image=image, dark_image=image, size=(320, 180))
                self.thumb_label.configure(image=self.thumb_image, text="")
            except Exception:
                self.thumb_label.configure(image=None, text="🎬", font=ctk.CTkFont(size=48))
        else:
            self.thumb_label.configure(image=None, text="🎬", font=ctk.CTkFont(size=48))

        self.title_label.configure(text=info.title)
        for widget in self.chips_frame.winfo_children():
            widget.destroy()
        if info.is_playlist:
            chip(self.chips_frame, "Плейлист").pack(side="left", padx=(0, 8))
            chip(self.chips_frame, f"видео: {info.count}").pack(side="left")
        else:
            chip(self.chips_frame, f"⏱ {format_duration(info.duration)}").pack(side="left", padx=(0, 8))
            choices = downloader.quality_choices(info.heights)
            self.quality_menu.configure(values=[f"{h}p" for h in choices])
            preferred = int(self.settings["video_quality"])
            best = next((h for h in choices if h <= preferred), choices[-1])
            self.quality_menu.set(f"{best}p")
        self._status("Информация получена. Выберите качество и добавьте в очередь.", "ok")

    def _remember_download(self):
        self.settings.update(
            download_dir=self.folder_var.get().strip() or self.settings["download_dir"],
            mode=self.mode_switch.get(),
            video_quality=int(self.quality_menu.get().rstrip("p")),
            audio_format=self.audio_menu.get(),
        )
        save_settings(self.settings)

    def _apply_settings(self):
        mode = self.settings["mode"]
        self.mode_switch.set(mode if mode in (MODE_VIDEO, MODE_AUDIO) else MODE_VIDEO)
        self.quality_menu.set(f"{self.settings['video_quality']}p")
        audio = self.settings["audio_format"]
        self.audio_menu.set(audio if audio in AUDIO_FORMATS else next(iter(AUDIO_FORMATS)))
        self._show_options()
        self._load_settings_form()

    # ---------- Страница «Очередь» ----------

    def _build_queue_page(self):
        page = self._new_page("queue")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)
        heading(page, "Очередь", "Загрузки идут по очереди, одна за другой").grid(
            row=0, column=0, sticky="w"
        )

        active = card(page)
        active.grid(row=1, column=0, sticky="ew", pady=(20, 14))
        active.grid_columnconfigure(0, weight=1)
        self.stage_label = ctk.CTkLabel(
            active, text="Сейчас ничего не качается", text_color=TEXT,
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        )
        self.stage_label.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        self.progress_bar = ctk.CTkProgressBar(
            active, height=12, corner_radius=8, fg_color=FIELD, progress_color=ACCENT
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=20)
        self.stats_label = ctk.CTkLabel(active, text="", text_color=MUTED, anchor="w")
        self.stats_label.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 18))
        self.cancel_btn = ctk.CTkButton(
            active, text="Отменить", width=130, height=40, corner_radius=12,
            fg_color=DANGER, hover_color=DANGER_HI, state="disabled",
            command=self._cancel_active,
        )
        self.cancel_btn.grid(row=0, column=1, rowspan=3, padx=20)

        toolbar = ctk.CTkFrame(page, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="new")
        ctk.CTkLabel(
            toolbar, text="СПИСОК ЗАДАЧ", font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED
        ).pack(side="left")
        ghost(toolbar, "Очистить завершённые", self._clear_finished, width=200).pack(side="right")

        self.queue_frame = ctk.CTkScrollableFrame(
            page, fg_color="transparent", corner_radius=0
        )
        self.queue_frame.grid(row=2, column=0, sticky="nsew", pady=(40, 0))
        self._refresh_queue()

    def _refresh_queue(self):
        for widget in self.queue_frame.winfo_children():
            widget.destroy()
        if not self.jobs:
            ctk.CTkLabel(
                self.queue_frame, text="Очередь пуста. Добавьте ссылку на странице «Загрузка».",
                text_color=MUTED,
            ).pack(anchor="w", padx=8, pady=20)
            return
        for number, job in enumerate(reversed(self.jobs), start=1):
            row = card(self.queue_frame)
            row.pack(fill="x", padx=4, pady=5)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row, text="●", text_color=STATUS_COLOR[job.status], font=ctk.CTkFont(size=18)
            ).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=14)
            kind = "Видео" if job.mode == "video" else f"Музыка · {job.audio_format}"
            ctk.CTkLabel(
                row, text=job.url[:95], text_color=TEXT, anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
            ).grid(row=0, column=1, sticky="ew", pady=(12, 0))
            details = kind
            if job.status == "error" and job.message:
                details = job.message
            ctk.CTkLabel(
                row, text=details, text_color=ERR if job.status == "error" else MUTED,
                anchor="w", wraplength=680, justify="left", font=ctk.CTkFont(size=12),
            ).grid(row=1, column=1, sticky="ew", pady=(2, 12))
            ctk.CTkLabel(
                row, text=STATUS_TEXT[job.status], text_color=STATUS_COLOR[job.status],
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=0, column=2, rowspan=2, padx=18)

    def _clear_finished(self):
        self.jobs = [j for j in self.jobs if j.status in ("waiting", "running")]
        self._refresh_queue()

    def _cancel_active(self):
        if self.active_job is not None:
            self.active_job.cancel.set()
            self._status("Отменяю загрузку…")

    def _show_progress(self, job: Job, progress: downloader.Progress):
        if job is not self.active_job:
            return
        self.stage_label.configure(text=f"{progress.stage}: {job.url[:80]}")
        if progress.percent is not None:
            self.progress_bar.set(min(progress.percent, 100) / 100)
        parts = [f"{progress.percent:.1f}%" if progress.percent is not None else "подготовка…"]
        if progress.speed:
            parts.append(f"скорость {format_speed(progress.speed)}")
        if progress.eta is not None:
            parts.append(f"осталось {format_eta(progress.eta)}")
        self.stats_label.configure(text="    •    ".join(parts))

    def _finish_job(self, job: Job):
        if job is self.active_job:
            self.active_job = None
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(1 if job.status == "done" else 0)
        self.stage_label.configure(text=f"Задача: {STATUS_TEXT[job.status]}")
        self.stats_label.configure(text="")
        self._refresh_queue()
        if job.status == "done":
            self._status(f"Готово! Файлы сохранены в: {job.message}", "ok")
        elif job.status == "error":
            self._status(job.message, "error")
        else:
            self._status(f"Загрузка: {job.message or 'отменена'}")

    # ---------- Страница «Настройки» ----------

    def _build_settings_page(self):
        page = self._new_page("settings")
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)
        heading(scroll, "Настройки", "Прокси, сеть и обновления").grid(row=0, column=0, sticky="w")

        # Папка
        self.folder_card = card(scroll)
        self.folder_card.grid(row=1, column=0, sticky="ew", pady=(20, 14))
        self.folder_card.grid_columnconfigure(0, weight=1)
        caption(self.folder_card, "Папка для загрузок").grid(
            row=0, column=0, sticky="w", padx=20, pady=(18, 6)
        )
        field(self.folder_card, textvariable=self.folder_var).grid(
            row=1, column=0, sticky="ew", padx=(20, 10), pady=(0, 18)
        )
        ghost(self.folder_card, "Выбрать папку", self._choose_folder, width=160).grid(
            row=1, column=1, padx=(0, 20), pady=(0, 18)
        )

        # Прокси
        proxy = card(scroll)
        proxy.grid(row=2, column=0, sticky="ew", pady=14)
        proxy.grid_columnconfigure((0, 1), weight=1)
        head = ctk.CTkFrame(proxy, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 6))
        caption(head, "Прокси").pack(side="left")
        self.proxy_switch = ctk.CTkSwitch(
            head, text="Использовать прокси", progress_color=ACCENT, text_color=TEXT,
            button_color=TEXT, button_hover_color=MUTED,
        )
        self.proxy_switch.pack(side="right")
        self.proxy_type = segmented(proxy, ["HTTP", "SOCKS5"], width=200)
        self.proxy_type.grid(row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(6, 14))

        ctk.CTkLabel(proxy, text="Адрес (IP или домен)", text_color=MUTED, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=(20, 10))
        ctk.CTkLabel(proxy, text="Порт", text_color=MUTED, anchor="w").grid(
            row=2, column=1, sticky="ew", padx=(10, 20))
        self.host_entry = field(proxy, placeholder_text="например 1.2.3.4")
        self.host_entry.grid(row=3, column=0, sticky="ew", padx=(20, 10), pady=(4, 12))
        self.port_entry = field(proxy, placeholder_text="например 8080")
        self.port_entry.grid(row=3, column=1, sticky="ew", padx=(10, 20), pady=(4, 12))

        ctk.CTkLabel(proxy, text="Логин (если есть)", text_color=MUTED, anchor="w").grid(
            row=4, column=0, sticky="ew", padx=(20, 10))
        ctk.CTkLabel(proxy, text="Пароль (если есть)", text_color=MUTED, anchor="w").grid(
            row=4, column=1, sticky="ew", padx=(10, 20))
        self.user_entry = field(proxy)
        self.user_entry.grid(row=5, column=0, sticky="ew", padx=(20, 10), pady=(4, 12))
        self.pass_entry = field(proxy, show="•")
        self.pass_entry.grid(row=5, column=1, sticky="ew", padx=(10, 20), pady=(4, 12))

        actions = ctk.CTkFrame(proxy, fg_color="transparent")
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 6))
        ghost(actions, "Проверить прокси", self._test_proxy_clicked, width=180).pack(side="left")
        self.help_btn = ghost(actions, "Где взять прокси? ▾", self._toggle_proxy_help, width=180)
        self.help_btn.pack(side="left", padx=10)
        self.proxy_result = ctk.CTkLabel(proxy, text="", text_color=MUTED, anchor="w",
                                         wraplength=640, justify="left")
        self.proxy_result.grid(row=7, column=0, columnspan=2, sticky="ew", padx=20, pady=(6, 0))

        self.help_box = ctk.CTkFrame(proxy, fg_color=FIELD, corner_radius=12)
        self.help_box.grid(row=8, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 18))
        self.help_box.grid_remove()  # скрыто, пока не нажали кнопку
        ctk.CTkLabel(
            self.help_box, text=PROXY_HELP, text_color=TEXT, justify="left", anchor="w",
            wraplength=720, font=ctk.CTkFont(size=13),
        ).pack(padx=18, pady=16, anchor="w")

        # Сеть
        network = card(scroll)
        network.grid(row=3, column=0, sticky="ew", pady=14)
        network.grid_columnconfigure((0, 1), weight=1)
        caption(network, "Сеть").grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(network, text="Ожидание ответа, секунд (5–300)", text_color=MUTED, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=(20, 10))
        ctk.CTkLabel(network, text="Повторы при сбое (0–20)", text_color=MUTED, anchor="w").grid(
            row=1, column=1, sticky="ew", padx=(10, 20))
        self.timeout_entry = field(network)
        self.timeout_entry.grid(row=2, column=0, sticky="ew", padx=(20, 10), pady=(4, 18))
        self.retries_entry = field(network)
        self.retries_entry.grid(row=2, column=1, sticky="ew", padx=(10, 20), pady=(4, 18))

        # Обновления
        updates = card(scroll)
        updates.grid(row=4, column=0, sticky="ew", pady=14)
        caption(updates, "Обновления").pack(anchor="w", padx=20, pady=(18, 8))
        self.auto_ytdlp_switch = ctk.CTkSwitch(
            updates, text="Обновлять yt-dlp при запуске (рекомендуется)", progress_color=ACCENT,
            text_color=TEXT, button_color=TEXT, button_hover_color=MUTED,
        )
        self.auto_ytdlp_switch.pack(anchor="w", padx=20, pady=6)
        self.check_app_switch = ctk.CTkSwitch(
            updates, text="Проверять новые версии программы на GitHub", progress_color=ACCENT,
            text_color=TEXT, button_color=TEXT, button_hover_color=MUTED,
        )
        self.check_app_switch.pack(anchor="w", padx=20, pady=(6, 18))

        primary(scroll, "💾  Сохранить настройки", self._save_settings_clicked, height=46).grid(
            row=5, column=0, sticky="ew", pady=(10, 20))

    def _toggle_proxy_help(self):
        if self.help_box.winfo_ismapped():
            self.help_box.grid_remove()
            self.help_btn.configure(text="Где взять прокси? ▾")
        else:
            self.help_box.grid()
            self.help_btn.configure(text="Где взять прокси? ▴")

    def _load_settings_form(self):
        s = self.settings
        self.proxy_switch.select() if s["proxy_enabled"] else self.proxy_switch.deselect()
        self.proxy_type.set(s["proxy_type"] if s["proxy_type"] in ("HTTP", "SOCKS5") else "HTTP")
        self._set_entry(self.host_entry, s["proxy_host"])
        self._set_entry(self.port_entry, s["proxy_port"])
        self._set_entry(self.user_entry, s["proxy_user"])
        self._set_entry(self.pass_entry, s["proxy_pass"])
        self._set_entry(self.timeout_entry, s["timeout"])
        self._set_entry(self.retries_entry, s["retries"])
        self.auto_ytdlp_switch.select() if s["auto_update_ytdlp"] else self.auto_ytdlp_switch.deselect()
        self.check_app_switch.select() if s["check_app_update"] else self.check_app_switch.deselect()

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, str(value))

    def _proxy_form(self) -> dict:
        return {
            "proxy_enabled": bool(self.proxy_switch.get()),
            "proxy_type": self.proxy_type.get(),
            "proxy_host": self.host_entry.get().strip(),
            "proxy_port": self.port_entry.get().strip(),
            "proxy_user": self.user_entry.get().strip(),
            "proxy_pass": self.pass_entry.get(),
        }

    def _check_form(self) -> dict | None:
        """Проверяет поля настроек. Возвращает значения или None, если есть ошибка."""
        form = self._proxy_form()
        try:
            timeout = int(self.timeout_entry.get())
            retries = int(self.retries_entry.get())
        except ValueError:
            self._status("Таймаут и повторы должны быть числами", "error")
            return None
        if not (5 <= timeout <= 300) or not (0 <= retries <= 20):
            self._status("Таймаут: от 5 до 300 секунд. Повторы: от 0 до 20", "error")
            return None
        if form["proxy_enabled"] and not form["proxy_host"]:
            self._status("Включён прокси, но адрес не указан", "error")
            return None
        if form["proxy_port"] and not form["proxy_port"].isdigit():
            self._status("Порт прокси — это число, например 8080", "error")
            return None
        form.update(timeout=timeout, retries=retries)
        form.update(
            auto_update_ytdlp=bool(self.auto_ytdlp_switch.get()),
            check_app_update=bool(self.check_app_switch.get()),
        )
        return form

    def _save_settings_clicked(self):
        form = self._check_form()
        if form is None:
            return
        self.settings.update(form)
        self.settings["download_dir"] = self.folder_var.get().strip() or self.settings["download_dir"]
        save_settings(self.settings)
        self._status("Настройки сохранены. Прокси и сеть применятся к следующей загрузке.", "ok")

    def _test_proxy_clicked(self):
        form = self._check_form()
        if form is None:
            return
        if not form["proxy_enabled"]:
            self.proxy_result.configure(text="Сначала включите прокси переключателем выше.", text_color=ERR)
            return
        self.proxy_result.configure(text="Проверяю соединение через прокси…", text_color=MUTED)
        net = net_options({**self.settings, **form})
        threading.Thread(target=self._proxy_test_worker, args=(net,), daemon=True).start()

    # ---------- Страница «О программе» ----------

    def _build_about_page(self):
        page = self._new_page("about")
        heading(page, "О программе", "YT Downloader — простая загрузка видео и музыки").pack(anchor="w")

        info = card(page)
        info.pack(fill="x", pady=(20, 14))
        ctk.CTkLabel(info, text=f"Версия {APP_VERSION}", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(info, text=f"Версия yt-dlp: {yt_dlp.version.__version__}", text_color=MUTED).pack(
            anchor="w", padx=24)
        ctk.CTkLabel(info, text="Автор: screpka228", text_color=TEXT).pack(anchor="w", padx=24, pady=(10, 0))
        ctk.CTkLabel(
            info, text="Лицензия: MIT с обязательным указанием автора. Ссылка на исходный код — ниже.",
            text_color=MUTED, wraplength=700, justify="left",
        ).pack(anchor="w", padx=24, pady=(4, 18))

        buttons = ctk.CTkFrame(info, fg_color="transparent")
        buttons.pack(anchor="w", padx=24, pady=(0, 22))
        primary(buttons, "Открыть на GitHub", lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}"),
                width=200).pack(side="left")
        self.update_btn = ghost(buttons, "Проверить обновления", self._manual_update_clicked, width=200)
        self.update_btn.pack(side="left", padx=12)

    def _manual_update_clicked(self):
        self.update_btn.configure(state="disabled", text="Проверяю…")
        threading.Thread(target=self._manual_update, daemon=True).start()

    # ---------- Закрытие ----------

    def _on_close(self):
        if self.active_job is not None and not messagebox.askyesno(
            "Закрыть программу?", "Сейчас идёт загрузка. Всё равно закрыть программу?"
        ):
            return
        if self.active_job is not None:
            self.active_job.cancel.set()
        self._remember_download()
        self.destroy()

    # ---------- Фоновые потоки ----------

    def _fetch_preview(self, url: str, net: dict):
        try:
            info = downloader.fetch_info(url, net, self.ffmpeg_dir)
        except UserError as exc:
            self.events.put(("preview_err", str(exc)))
            return
        except Exception as exc:
            self.events.put(("preview_err", f"Непредвиденная ошибка: {exc}"))
            return

        thumb = None
        if info.thumbnail:
            try:
                request = urllib.request.Request(info.thumbnail, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    thumb = response.read()
            except Exception:
                # Без обложки тоже можно работать.
                thumb = None
        self.events.put(("preview_ok", info, thumb))

    def _worker(self):
        """Рабочий поток: качает задачи из очереди одну за другой."""
        while True:
            job = self.jobs_queue.get()
            if job.cancel.is_set():
                job.status = "cancelled"
                self.events.put(("finished", job))
                continue
            job.status = "running"
            self.events.put(("started", job))
            try:
                downloader.run_job(
                    job, self.ffmpeg_dir, lambda p, j=job: self.events.put(("progress", j, p))
                )
                job.status = "done"
                job.message = job.out_dir
            except downloader.Cancelled:
                job.status = "cancelled"
                job.message = "отменено пользователем"
            except UserError as exc:
                job.status = "error"
                job.message = str(exc)
            except Exception as exc:
                job.status = "error"
                job.message = f"Непредвиденная ошибка: {exc}"
            self.events.put(("finished", job))

    def _proxy_test_worker(self, net: dict):
        proxies = {"http": net["proxy"], "https": net["proxy"]} if net["proxy"] else None
        started = time.monotonic()
        try:
            response = requests.get(TEST_URL, proxies=proxies, timeout=net["timeout"])
        except requests.exceptions.ProxyError:
            text = "Не удалось подключиться к прокси. Проверьте адрес, порт, логин и пароль."
            self.events.put(("proxy_test", False, text))
            return
        except requests.exceptions.Timeout:
            text = f"Прокси не ответил за {net['timeout']} сек. Попробуйте другой или увеличьте таймаут."
            self.events.put(("proxy_test", False, text))
            return
        except requests.RequestException as exc:
            self.events.put(("proxy_test", False, f"Ошибка соединения: {exc}"))
            return
        ms = int((time.monotonic() - started) * 1000)
        if response.status_code < 400:
            text = f"Прокси работает. Ответ за {ms} мс, YouTube доступен."
            self.events.put(("proxy_test", True, text))
        else:
            self.events.put(("proxy_test", False, f"YouTube ответил ошибкой {response.status_code}."))

    def _check_app_update(self):
        try:
            found = deps.check_app_update()
        except Exception:
            return  # нет сети — молча пропускаем
        if found:
            self.events.put(("app_update", *found))

    def _manual_update(self):
        messages = []
        try:
            new_version = deps.download_newer_ytdlp()
            if new_version:
                messages.append(f"yt-dlp обновлён до {new_version}. Перезапустите программу.")
            else:
                messages.append("yt-dlp уже последней версии.")
        except Exception:
            messages.append("Не удалось проверить yt-dlp (возможно, нет интернета).")

        try:
            found = deps.check_app_update()
        except Exception:
            messages.append("Не удалось проверить обновления программы.")
        else:
            if found:
                self.events.put(("app_update", *found))
            else:
                messages.append(f"Программа последней версии ({APP_VERSION}).")
        self.events.put(("manual_done", " ".join(messages)))

    # ---------- Обработка сообщений из фоновых потоков ----------

    def _poll_events(self):
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _handle_event(self, event: tuple):
        kind = event[0]
        if kind == "preview_ok":
            self._show_preview(event[1], event[2])
        elif kind == "preview_err":
            self._status(event[1], "error")
        elif kind == "started":
            self.active_job = event[1]
            self.cancel_btn.configure(state="normal")
            self.progress_bar.set(0)
            self._refresh_queue()
        elif kind == "progress":
            self._show_progress(event[1], event[2])
        elif kind == "finished":
            self._finish_job(event[1])
        elif kind == "proxy_test":
            self.proxy_result.configure(text=event[2], text_color=OK if event[1] else ERR)
        elif kind == "app_update":
            self._offer_app_update(event[1], event[2])
        elif kind == "manual_done":
            self.update_btn.configure(state="normal", text="Проверить обновления")
            self._status(event[1], "ok")

    def _offer_app_update(self, latest: str, url: str):
        if messagebox.askyesno(
            "Доступна новая версия",
            f"Вышла новая версия программы: {latest} (у вас {APP_VERSION}).\n\n"
            "Открыть страницу загрузки?",
        ):
            webbrowser.open(url)
