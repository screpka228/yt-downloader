"""Главное окно программы (customtkinter): боковая панель и страницы."""
import os
import queue
import re
import threading
import time
import urllib.request
import webbrowser
from io import BytesIO
from tkinter import BooleanVar, filedialog, messagebox

import customtkinter as ctk
import requests
import yt_dlp
from PIL import Image

import deps
import downloader
from app_config import APP_NAME, APP_VERSION, GITHUB_REPO, data_dir, resource_dir
from dpi_proxy import METHODS, DpiProxy, configure_file_logging, probe
from downloader import AUDIO_FORMATS, VIDEO_HEIGHTS, Job, UserError
from history import add_history, clear_history, load_history
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
TEST_URLS = ["https://www.youtube.com/generate_204", "https://redirector.googlevideo.com/generate_204"]
PROXY_LABELS = {
    "builtin": "Встроенный (обход DPI)",
    "HTTP": "HTTP",
    "SOCKS5": "SOCKS5",
    "off": "Без прокси",
}
LABEL_TO_PROXY = {label: key for key, label in PROXY_LABELS.items()}
METHOD_LABELS = {
    "tlsrec+split": "tlsrec + split (рекомендуется)",
    "split": "split",
    "tlsrec": "tlsrec",
    "none": "без обхода (для проверки)",
}
LABEL_TO_METHOD = {label: key for key, label in METHOD_LABELS.items()}
PROXY_HELP = (
    "Встроенный режим (по умолчанию) не требует внешних серверов и VPN. Программа сама запускает "
    "прокси на вашем компьютере и при подключении к YouTube разрезает служебный пакет так, "
    "что провайдерский DPI не видит название сайта. Видео идёт напрямую с серверов Google. "
    "Сначала попробуйте этот режим и нажмите «Автоподбор».\n\n"
    "Внешний прокси нужен, только если встроенный не помогает.\n"
    "Где взять внешний прокси:\n"
    "1. Платные прокси-сервисы. Ищите по запросам «residential proxy» или «datacenter proxy». "
    "Обычно вы покупаете пакет и получаете адрес, порт, логин и пароль.\n"
    "2. Свой сервер (VPS) с SOCKS5 или HTTP-прокси, если умеете его настроить.\n"
    "3. Бесплатные общедоступные прокси не рекомендуем: они часто медленные и нестабильные, "
    "а через них могут видеть ваши данные.\n\n"
    "В поле «Адрес» — только IP или домен (например 1.2.3.4). В «Порт» — число (например 8080). "
    "Логин и пароль — только если провайдер их выдал."
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


def bind_clipboard_keys(entry):
    """Ctrl+V/C/X/A работают на любой раскладке.

    На русской раскладке V — это «М», и стандартные сочетания не срабатывают.
    Поэтому смотрим на физическую клавишу (код), а не на букву.
    """
    events = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>"}

    def on_ctrl(event):
        if event.keycode in events:
            event.widget.event_generate(events[event.keycode])
            return "break"
        if event.keycode == 65:  # A — выделить всё
            event.widget.select_range(0, "end")
            return "break"
        return None

    entry._entry.bind("<Control-Key>", on_ctrl)


def field(parent, height=38, **kwargs):
    entry = ctk.CTkEntry(
        parent, height=height, corner_radius=12, fg_color=FIELD,
        border_color=BORDER, text_color=TEXT, **kwargs,
    )
    bind_clipboard_keys(entry)
    return entry


def option_menu(parent, values, width=170, command=None):
    return ctk.CTkOptionMenu(
        parent, values=values, width=width, height=38, corner_radius=12,
        fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HI,
        dropdown_fg_color=CARD_HI, dropdown_hover_color="#2a3152", text_color=TEXT,
        command=command,
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


def format_size(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.2f} ГБ"
    return f"{size / 1024**2:.0f} МБ"


SUB_NAMES = {
    "ru": "Русский", "en": "Английский", "de": "Немецкий", "fr": "Французский",
    "es": "Испанский", "it": "Итальянский", "pt": "Португальский", "uk": "Украинский",
    "tr": "Турецкий", "ja": "Японский", "ko": "Корейский", "zh": "Китайский",
}


def subtitle_label(code: str, auto: bool) -> str:
    name = SUB_NAMES.get(code.split("-")[0], code)
    return f"{name} ({code}){' — авто' if auto else ''}"


class SubtitleDialog(ctk.CTkToplevel):
    """Окно выбора языков субтитров. on_done(список кодов, встраивать?) вызывается при «Готово»."""

    def __init__(self, master, langs, selected, embed, on_done):
        super().__init__(master)
        self.title("Субтитры")
        self.geometry("460x580")
        self.configure(fg_color=CARD)
        self.transient(master)
        self.grab_set()
        self.on_done = on_done
        self.vars = {}

        ctk.CTkLabel(self, text="Субтитры", font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT).pack(
            anchor="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            self, text="Отметьте нужные языки. Если ничего не отмечено, субтитры не скачиваются.",
            text_color=MUTED, wraplength=400, justify="left",
        ).pack(anchor="w", padx=22)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=22, pady=12)
        ghost(bar, "Выбрать все", self._select_all, width=150).pack(side="left")
        ghost(bar, "Снять все", self._clear_all, width=150).pack(side="left", padx=10)

        listing = ctk.CTkScrollableFrame(self, fg_color=FIELD, corner_radius=12)
        listing.pack(fill="both", expand=True, padx=22)
        if not langs:
            ctk.CTkLabel(listing, text="У этого видео нет субтитров.", text_color=MUTED).pack(
                anchor="w", padx=12, pady=12)
        for code, auto in langs:
            var = BooleanVar(value=code in selected)
            ctk.CTkCheckBox(
                listing, text=subtitle_label(code, auto), variable=var, fg_color=ACCENT,
                hover_color=ACCENT_HI, text_color=TEXT,
            ).pack(anchor="w", padx=12, pady=5)
            self.vars[code] = var

        self.embed_var = BooleanVar(value=embed)
        ctk.CTkSwitch(
            self, text="Встроить субтитры в видеофайл (mp4/mkv)", variable=self.embed_var,
            progress_color=ACCENT, text_color=TEXT, button_color=TEXT, button_hover_color=MUTED,
        ).pack(anchor="w", padx=22, pady=(14, 6))
        ctk.CTkLabel(
            self, text="Отдельные файлы .vtt сохраняются в любом случае.",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=22)
        primary(self, "Готово", self._done, height=44).pack(fill="x", padx=22, pady=18)

    def _select_all(self):
        for var in self.vars.values():
            var.set(True)

    def _clear_all(self):
        for var in self.vars.values():
            var.set(False)

    def _done(self):
        selected = [code for code, var in self.vars.items() if var.get()]
        self.on_done(selected, bool(self.embed_var.get()))
        self.destroy()


# ---------- Главное окно ----------


class App(ctk.CTk):
    _last_queue_refresh = 0.0

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1080x800")
        self.minsize(980, 720)
        self.configure(fg_color=BG)
        self._set_icon()
        self._setup_dpi_logging()

        self.events = queue.Queue()  # сообщения от фоновых потоков к окну
        self.jobs_queue = queue.Queue()  # задачи для рабочего потока
        self.jobs: list[Job] = []
        self.active_job: Job | None = None
        self.info = None
        self.thumb_image = None
        self.nav_buttons = {}
        self.pages = {}
        self._fetch_after_id = None
        self._last_fetched = ""
        self.sub_selection = list(self.settings["subs_langs"])
        self.sub_embed = bool(self.settings["subs_embed"])
        self.folder_var = ctk.StringVar(value=self.settings["download_dir"])
        self.ffmpeg_dir = deps.ensure_ffmpeg()
        self.dpi = DpiProxy(
            port=int(self.settings["dpi_port"]),
            method=self.settings["dpi_method"],
            all_hosts=bool(self.settings["dpi_all_hosts"]),
        )
        self.dpi_error = ""
        if self.settings["proxy_mode"] == "builtin":
            self._start_dpi()

        self._build_shell()
        self._build_download_page()
        self._build_queue_page()
        self._build_history_page()
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

    def _setup_dpi_logging(self):
        try:
            configure_file_logging(data_dir() / "logs" / "dpi_proxy.log")
        except OSError:
            # Лог не критичен: без него прокси работает так же.
            pass

    # ---------- Встроенный прокси ----------

    def _start_dpi(self) -> None:
        try:
            self.dpi.start()
            self.dpi_error = ""
        except OSError as exc:
            self.dpi_error = str(exc)

    def _dpi_port(self) -> int | None:
        return self.dpi.port if self.dpi.running else None

    def _current_net(self) -> dict:
        return net_options(self.settings, self._dpi_port())

    def _apply_dpi(self, cfg: dict) -> None:
        """Приводит встроенный прокси в соответствие с настройками cfg (запуск, остановка, метод)."""
        self.dpi.method = cfg["dpi_method"]
        self.dpi.all_hosts = bool(cfg["dpi_all_hosts"])
        if cfg["proxy_mode"] != "builtin":
            self.dpi.stop()
            self.dpi_error = ""
        elif not self.dpi.running or self.dpi.preferred_port != int(cfg["dpi_port"]):
            self.dpi.stop()
            self.dpi.preferred_port = int(cfg["dpi_port"])
            self._start_dpi()
        self._refresh_dpi_status()

    def _refresh_dpi_status(self) -> None:
        if self.dpi.running:
            self.dpi_status.configure(text=f"●  Работает на 127.0.0.1:{self.dpi.port}", text_color=OK)
        elif self.dpi_error:
            self.dpi_status.configure(text=f"●  Не запущен: {self.dpi_error}", text_color=ERR)
        else:
            self.dpi_status.configure(text="●  Не запущен", text_color=MUTED)

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
            ("history", "🕘   История"),
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
        if key == "history":
            self._refresh_history()
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
        self.url_var = ctk.StringVar()
        self.url_var.trace_add("write", self._on_url_changed)
        self.url_entry = field(
            url_card, height=44, placeholder_text="https://www.youtube.com/watch?v=…",
            textvariable=self.url_var,
        )
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
        self.options_frame = options
        options.grid_remove()  # качество и формат появятся после того, как дана ссылка
        self.option_label = ctk.CTkLabel(options, text="Качество", text_color=MUTED)
        self.option_label.pack(side="left", padx=(0, 10))
        self.quality_menu = option_menu(
            options, [f"{h}p" for h in VIDEO_HEIGHTS], 160, command=lambda _v: self._update_size()
        )
        self.audio_menu = option_menu(
            options, list(AUDIO_FORMATS), 200, command=lambda _v: self._update_size()
        )
        self.container_menu = option_menu(options, ["mp4", "mkv"], 110)
        self.sub_btn = ghost(options, "🗒  Субтитры", self._open_subtitles, width=140)
        self.sub_label = ctk.CTkLabel(options, text="", text_color=MUTED, font=ctk.CTkFont(size=13))
        self.size_label = ctk.CTkLabel(options, text="", text_color=MUTED, font=ctk.CTkFont(size=13))

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
        self.size_label.pack_forget()
        self.container_menu.pack_forget()
        (self.quality_menu if is_video else self.audio_menu).pack(side="left")
        self.sub_btn.pack_forget()
        self.sub_label.pack_forget()
        if is_video:
            self.container_menu.pack(side="left", padx=(10, 0))
            self.sub_btn.pack(side="left", padx=(14, 0))
            self.sub_label.pack(side="left", padx=10)
        self.size_label.pack(side="left", padx=14)
        self._update_size()
        self._update_sub_label()

    def _open_subtitles(self):
        if self.info is None or self.info.is_playlist:
            self._status("Сначала вставьте ссылку на одно видео, тогда появится список языков", "error")
            return
        SubtitleDialog(self, self.info.sub_langs, self.sub_selection, self.sub_embed, self._set_subtitles)

    def _set_subtitles(self, selected: list, embed: bool):
        self.sub_selection = selected
        self.sub_embed = embed
        self.settings.update(subs_langs=selected, subs_embed=embed)
        save_settings(self.settings)
        self._update_sub_label()

    def _update_sub_label(self):
        if not self.sub_selection:
            self.sub_label.configure(text="Субтитры: нет")
            return
        text = f"Субтитры: {', '.join(self.sub_selection)}"
        self.sub_label.configure(text=text + (" • в файл" if self.sub_embed else ""))

    def _update_size(self):
        """Оценка размера файла для выбранного качества или формата."""
        info = self.info
        if info is None or info.is_playlist:
            self.size_label.configure(text="")
            return
        if self.mode_switch.get() == MODE_AUDIO:
            if self.audio_menu.get().startswith("mp3") and info.duration:
                size = info.duration * 320000 // 8  # 320 kbps
            else:
                size = info.audio_size
        else:
            height = int(self.quality_menu.get().rstrip("p"))
            video = info.sizes.get(height)
            size = video + info.audio_size if video and info.audio_size else video
        self.size_label.configure(text=f"≈ {format_size(size)}" if size else "размер неизвестен")

    def _url(self) -> str:
        return self.url_entry.get().strip()

    def _valid_url(self, url: str) -> bool:
        if re.match(r"^https?://\S+$", url):
            return True
        self._status("Неверная ссылка: адрес должен начинаться с https://", "error")
        return False

    def _on_url_changed(self, *_):
        """Ссылка изменилась (вставка, ввод): через короткую паузу получаем форматы сами."""
        if self._fetch_after_id is not None:
            self.after_cancel(self._fetch_after_id)
        self._fetch_after_id = self.after(700, self._auto_fetch)

    def _auto_fetch(self):
        self._fetch_after_id = None
        url = self._url()
        if re.match(r"^https?://\S+$", url) and url != self._last_fetched:
            self._last_fetched = url
            self._fetch_clicked()

    def _fetch_clicked(self):
        url = self._url()
        if not self._valid_url(url):
            return
        if not self._builtin_ready():
            return
        self._status("Получаю информацию о ссылке…")
        threading.Thread(
            target=self._fetch_preview, args=(url, self._current_net()), daemon=True
        ).start()

    def _builtin_ready(self) -> bool:
        """Если выбран встроенный прокси, он должен быть запущен. Иначе сообщаем об ошибке."""
        if self.settings["proxy_mode"] == "builtin" and not self.dpi.running:
            self._status(f"Встроенный прокси не запущен: {self.dpi_error or 'причина неизвестна'}. "
                         "Откройте «Настройки» и проверьте порт.", "error")
            return False
        return True

    def _add_to_queue(self):
        url = self._url()
        if not self._valid_url(url) or not self._builtin_ready():
            return
        out_dir = self.folder_var.get().strip()
        if not out_dir:
            self._status("Укажите папку для сохранения", "error")
            return
        job = Job(
            url=url,
            mode="video" if self.mode_switch.get() == MODE_VIDEO else "audio",
            out_dir=out_dir,
            net=self._current_net(),
            height=int(self.quality_menu.get().rstrip("p")),
            audio_format=self.audio_menu.get(),
            container=self.container_menu.get(),
            subtitles=list(self.sub_selection) if self.mode_switch.get() == MODE_VIDEO else [],
            embed_subs=self.sub_embed,
            thumbnail=bool(self.settings["thumb_enabled"]),
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
        self.options_frame.grid()
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
        self._update_size()
        self._update_sub_label()
        self._status("Информация получена. Выберите качество и добавьте в очередь.", "ok")

    def _remember_download(self):
        self.settings.update(
            download_dir=self.folder_var.get().strip() or self.settings["download_dir"],
            mode=self.mode_switch.get(),
            video_quality=int(self.quality_menu.get().rstrip("p")),
            audio_format=self.audio_menu.get(),
            container=self.container_menu.get(),
        )
        save_settings(self.settings)

    def _apply_settings(self):
        mode = self.settings["mode"]
        self.mode_switch.set(mode if mode in (MODE_VIDEO, MODE_AUDIO) else MODE_VIDEO)
        self.quality_menu.set(f"{self.settings['video_quality']}p")
        audio = self.settings["audio_format"]
        self.audio_menu.set(audio if audio in AUDIO_FORMATS else next(iter(AUDIO_FORMATS)))
        self.container_menu.set(self.settings["container"] if self.settings["container"] in ("mp4", "mkv") else "mp4")
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
        for job in reversed(self.jobs):
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
            if job.status == "running":
                details = job.progress or "Подготовка…"
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
        line = "    •    ".join(parts)
        self.stats_label.configure(text=line)
        job.progress = f"{progress.stage}: {line}"
        # Очередь обновляем не чаще раза в полсекунды, чтобы окно не тормозило.
        if time.monotonic() - self._last_queue_refresh > 0.5:
            self._last_queue_refresh = time.monotonic()
            self._refresh_queue()

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
        if job.status == "error" and job.network_error:
            self._offer_bypass(lambda j=job: self._requeue(j))

    def _requeue(self, job: Job):
        """Ставит задачу в очередь заново с текущими сетевыми настройками."""
        job.net = self._current_net()
        job.status = "waiting"
        job.message = ""
        job.network_error = False
        job.cancel.clear()
        self.jobs_queue.put(job)
        self._refresh_queue()
        self._status("Повторяю загрузку с встроенным обходом…")

    def _offer_bypass(self, retry):
        """Сеть или блокировка: предлагаем включить встроенный обход и повторить действие."""
        if self.settings["proxy_mode"] == "builtin":
            self._status("Сетевая ошибка, хотя встроенный обход включён. Попробуйте «Автоподбор метода» в настройках.", "error")
            return
        if not messagebox.askyesno(
            "Не удалось подключиться",
            "Похоже, сеть блокирует YouTube.\n\n"
            "Включить встроенный обход блокировок? Внешние серверы и VPN не нужны. "
            "Программа запустит локальный прокси на вашем компьютере и повторит действие.",
        ):
            return
        self.settings["proxy_mode"] = "builtin"
        save_settings(self.settings)
        self._load_settings_form()
        self._apply_dpi(self.settings)
        if self.dpi.running:
            retry()
        else:
            self._status(f"Встроенный прокси не запустился: {self.dpi_error}", "error")

    # ---------- Страница «История» ----------

    def _build_history_page(self):
        page = self._new_page("history")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        heading(top, "История", "Что вы уже скачали").grid(row=0, column=0, sticky="w")
        ghost(top, "Очистить историю", self._clear_history, width=180).grid(row=0, column=1, sticky="e")
        self.history_frame = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        self.history_frame.grid(row=1, column=0, sticky="nsew", pady=(20, 0))

    def _refresh_history(self):
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        items = load_history()
        if not items:
            ctk.CTkLabel(
                self.history_frame, text="Пока пусто. Скачанные файлы появятся здесь.", text_color=MUTED
            ).pack(anchor="w", padx=8, pady=20)
            return
        for item in items:
            row = card(self.history_frame)
            row.pack(fill="x", padx=4, pady=5)
            row.grid_columnconfigure(0, weight=1)
            kind = "Видео" if item["kind"] == "video" else "Музыка"
            ctk.CTkLabel(
                row, text=item["url"][:90], text_color=TEXT, anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
            ).grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 0))
            ctk.CTkLabel(
                row, text=f"{kind}  •  {item['date']}  •  {item['folder']}", text_color=MUTED,
                anchor="w", wraplength=680, justify="left", font=ctk.CTkFont(size=12),
            ).grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 14))
            ghost(row, "Открыть папку", lambda f=item["folder"]: self._open_folder(f), width=150).grid(
                row=0, column=1, rowspan=2, padx=18)

    def _open_folder(self, folder: str):
        if os.path.isdir(folder):
            os.startfile(folder)
        else:
            self._status("Эта папка уже не существует", "error")

    def _clear_history(self):
        if messagebox.askyesno("Очистить историю?", "Список загрузок будет удалён. Сами файлы останутся на диске."):
            clear_history()
            self._refresh_history()

    # ---------- Страница «Настройки» ----------

    def _build_settings_page(self):
        page = self._new_page("settings")
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)
        heading(scroll, "Настройки", "Прокси, сеть и обновления").grid(row=0, column=0, sticky="w")

        # Папка
        folder_card = card(scroll)
        folder_card.grid(row=1, column=0, sticky="ew", pady=(20, 14))
        folder_card.grid_columnconfigure(0, weight=1)
        caption(folder_card, "Папка для загрузок").grid(
            row=0, column=0, sticky="w", padx=20, pady=(18, 6)
        )
        field(folder_card, textvariable=self.folder_var).grid(
            row=1, column=0, sticky="ew", padx=(20, 10), pady=(0, 18)
        )
        ghost(folder_card, "Выбрать папку", self._choose_folder, width=160).grid(
            row=1, column=1, padx=(0, 20), pady=(0, 6)
        )
        self.thumb_switch = ctk.CTkSwitch(
            folder_card, text="Сохранять обложку видео отдельным файлом", progress_color=ACCENT,
            text_color=TEXT, button_color=TEXT, button_hover_color=MUTED,
        )
        self.thumb_switch.grid(row=3, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 18))

        # Прокси
        proxy = card(scroll)
        proxy.grid(row=2, column=0, sticky="ew", pady=14)
        proxy.grid_columnconfigure((0, 1), weight=1)
        caption(proxy, "Прокси").grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(18, 6))
        self.mode_seg = segmented(proxy, list(PROXY_LABELS.values()), self._on_proxy_mode, width=560)
        self.mode_seg.grid(row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 12))

        # Блок встроенного прокси
        self.builtin_frame = ctk.CTkFrame(proxy, fg_color="transparent")
        self.builtin_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20)
        self.builtin_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.dpi_status = ctk.CTkLabel(self.builtin_frame, text="", anchor="w", font=ctk.CTkFont(size=13, weight="bold"))
        self.dpi_status.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(self.builtin_frame, text="Порт (1024–65535)", text_color=MUTED, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(self.builtin_frame, text="Метод обхода", text_color=MUTED, anchor="w").grid(
            row=1, column=1, sticky="ew", padx=(0, 10))
        self.dpi_port_entry = field(self.builtin_frame)
        self.dpi_port_entry.grid(row=2, column=0, sticky="ew", padx=(0, 10), pady=(4, 10))
        self.dpi_method_menu = option_menu(self.builtin_frame, list(METHOD_LABELS.values()), 260)
        self.dpi_method_menu.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(4, 10))
        self.dpi_all_switch = ctk.CTkSwitch(
            self.builtin_frame, text="Применять ко всем сайтам", progress_color=ACCENT,
            text_color=TEXT, button_color=TEXT, button_hover_color=MUTED,
        )
        self.dpi_all_switch.grid(row=2, column=2, sticky="w", pady=(4, 10))
        ctk.CTkLabel(
            self.builtin_frame,
            text="Обход действует только для YouTube и связанных доменов, остальные сайты идут напрямую.",
            text_color=MUTED, anchor="w", wraplength=700, justify="left", font=ctk.CTkFont(size=12),
        ).grid(row=3, column=0, columnspan=3, sticky="ew")

        # Блок внешнего прокси
        self.external_frame = ctk.CTkFrame(proxy, fg_color="transparent")
        self.external_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20)
        self.external_frame.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(self.external_frame, text="Адрес (IP или домен)", text_color=MUTED, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(self.external_frame, text="Порт", text_color=MUTED, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(10, 0))
        self.host_entry = field(self.external_frame, placeholder_text="например 1.2.3.4")
        self.host_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(4, 12))
        self.port_entry = field(self.external_frame, placeholder_text="например 8080")
        self.port_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(4, 12))
        ctk.CTkLabel(self.external_frame, text="Логин (если есть)", text_color=MUTED, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(self.external_frame, text="Пароль (если есть)", text_color=MUTED, anchor="w").grid(
            row=2, column=1, sticky="ew", padx=(10, 0))
        self.user_entry = field(self.external_frame)
        self.user_entry.grid(row=3, column=0, sticky="ew", padx=(0, 10), pady=(4, 12))
        self.pass_entry = field(self.external_frame, show="•")
        self.pass_entry.grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=(4, 12))

        # Общие кнопки и результат
        actions = ctk.CTkFrame(proxy, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(6, 0))
        ghost(actions, "Проверить", self._test_clicked, width=150).pack(side="left")
        self.autopick_btn = ghost(actions, "Автоподбор метода", self._autopick_clicked, width=190)
        self.autopick_btn.pack(side="left", padx=10)
        self.help_btn = ghost(actions, "Где взять прокси? ▾", self._toggle_proxy_help, width=180)
        self.help_btn.pack(side="left")
        self.proxy_result = ctk.CTkLabel(proxy, text="", text_color=MUTED, anchor="w",
                                         wraplength=720, justify="left")
        self.proxy_result.grid(row=4, column=0, columnspan=2, sticky="ew", padx=20, pady=(8, 0))

        self.help_box = ctk.CTkFrame(proxy, fg_color=FIELD, corner_radius=12)
        self.help_box.grid(row=5, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 18))
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

    def _on_proxy_mode(self, _label):
        self._show_proxy_frames()

    def _show_proxy_frames(self):
        mode = LABEL_TO_PROXY[self.mode_seg.get()]
        self.builtin_frame.grid_remove()
        self.external_frame.grid_remove()
        if mode == "builtin":
            self.builtin_frame.grid()
        elif mode in ("HTTP", "SOCKS5"):
            self.external_frame.grid()
        self.autopick_btn.configure(state="normal" if mode == "builtin" else "disabled")

    def _toggle_proxy_help(self):
        if self.help_box.winfo_ismapped():
            self.help_box.grid_remove()
            self.help_btn.configure(text="Где взять прокси? ▾")
        else:
            self.help_box.grid()
            self.help_btn.configure(text="Где взять прокси? ▴")

    def _load_settings_form(self):
        s = self.settings
        self.mode_seg.set(PROXY_LABELS.get(s["proxy_mode"], PROXY_LABELS["builtin"]))
        self._show_proxy_frames()
        self._set_entry(self.dpi_port_entry, s["dpi_port"])
        self.dpi_method_menu.set(METHOD_LABELS.get(s["dpi_method"], METHOD_LABELS["tlsrec+split"]))
        self.dpi_all_switch.select() if s["dpi_all_hosts"] else self.dpi_all_switch.deselect()
        self._set_entry(self.host_entry, s["proxy_host"])
        self._set_entry(self.port_entry, s["proxy_port"])
        self._set_entry(self.user_entry, s["proxy_user"])
        self._set_entry(self.pass_entry, s["proxy_pass"])
        self._set_entry(self.timeout_entry, s["timeout"])
        self._set_entry(self.retries_entry, s["retries"])
        self.auto_ytdlp_switch.select() if s["auto_update_ytdlp"] else self.auto_ytdlp_switch.deselect()
        self.check_app_switch.select() if s["check_app_update"] else self.check_app_switch.deselect()
        self.thumb_switch.select() if s["thumb_enabled"] else self.thumb_switch.deselect()
        self._refresh_dpi_status()

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, str(value))

    def _form(self) -> dict | None:
        """Читает и проверяет поля настроек. Возвращает значения или None при ошибке."""
        mode = LABEL_TO_PROXY[self.mode_seg.get()]
        form = {
            "proxy_mode": mode,
            "proxy_host": self.host_entry.get().strip(),
            "proxy_port": self.port_entry.get().strip(),
            "proxy_user": self.user_entry.get().strip(),
            "proxy_pass": self.pass_entry.get(),
            "dpi_method": LABEL_TO_METHOD[self.dpi_method_menu.get()],
            "dpi_all_hosts": bool(self.dpi_all_switch.get()),
        }
        try:
            form["dpi_port"] = int(self.dpi_port_entry.get())
            timeout = int(self.timeout_entry.get())
            retries = int(self.retries_entry.get())
        except ValueError:
            self._status("Порт, таймаут и повторы должны быть числами", "error")
            return None
        if not (1024 <= form["dpi_port"] <= 65535):
            self._status("Порт встроенного прокси: от 1024 до 65535", "error")
            return None
        if not (5 <= timeout <= 300) or not (0 <= retries <= 20):
            self._status("Таймаут: от 5 до 300 секунд. Повторы: от 0 до 20", "error")
            return None
        if mode in ("HTTP", "SOCKS5"):
            if not form["proxy_host"]:
                self._status("Укажите адрес внешнего прокси", "error")
                return None
            if form["proxy_port"] and not form["proxy_port"].isdigit():
                self._status("Порт прокси — это число, например 8080", "error")
                return None
        form.update(
            timeout=timeout,
            retries=retries,
            auto_update_ytdlp=bool(self.auto_ytdlp_switch.get()),
            check_app_update=bool(self.check_app_switch.get()),
            thumb_enabled=bool(self.thumb_switch.get()),
        )
        return form

    def _save_settings_clicked(self):
        form = self._form()
        if form is None:
            return
        self.settings.update(form)
        self.settings["download_dir"] = self.folder_var.get().strip() or self.settings["download_dir"]
        save_settings(self.settings)
        self._apply_dpi(self.settings)
        self._status("Настройки сохранены.", "ok")

    def _test_clicked(self):
        form = self._form()
        if form is None:
            return
        if form["proxy_mode"] == "builtin":
            self._apply_dpi(form)
            if not self.dpi.running:
                self.proxy_result.configure(text=f"Прокси не запущен: {self.dpi_error}", text_color=ERR)
                return
        net = net_options({**self.settings, **form}, self._dpi_port())
        self.proxy_result.configure(text="Проверяю соединение…", text_color=MUTED)
        threading.Thread(target=self._probe_worker, args=(net["proxy"], net["timeout"]), daemon=True).start()

    def _autopick_clicked(self):
        form = self._form()
        if form is None:
            return
        self._apply_dpi(form)
        if not self.dpi.running:
            self.proxy_result.configure(text=f"Прокси не запущен: {self.dpi_error}", text_color=ERR)
            return
        self.proxy_result.configure(text="Подбираю метод: проверяю каждый по очереди…", text_color=MUTED)
        self.autopick_btn.configure(state="disabled")
        threading.Thread(target=self._autopick_worker, daemon=True).start()

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
        self.dpi.stop()
        self.destroy()

    # ---------- Фоновые потоки ----------

    def _fetch_preview(self, url: str, net: dict):
        try:
            info = downloader.fetch_info(url, net, self.ffmpeg_dir)
        except UserError as exc:
            self.events.put(("preview_err", str(exc), exc.network))
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
                add_history(job.url, job.out_dir, job.mode)
            except downloader.Cancelled:
                job.status = "cancelled"
                job.message = "отменено пользователем"
            except UserError as exc:
                job.status = "error"
                job.message = str(exc)
                job.network_error = exc.network
            except Exception as exc:
                job.status = "error"
                job.message = f"Непредвиденная ошибка: {exc}"
            self.events.put(("finished", job))

    @staticmethod
    def _summarize(results) -> tuple[bool, str]:
        parts, ok_all = [], True
        for url, ok, ms, note in results:
            name = "YouTube" if "youtube" in url else "googlevideo"
            ok_all = ok_all and ok
            parts.append(f"{name}: {'✓ ' + str(ms) + ' мс' if ok else '✗ ' + note}")
        return ok_all, "   •   ".join(parts)

    def _probe_worker(self, proxy: str, timeout: int):
        ok, text = self._summarize(probe(proxy, TEST_URLS, timeout=timeout))
        self.events.put(("proxy_test", ok, text))

    def _autopick_worker(self):
        for method in ("tlsrec+split", "tlsrec", "split"):
            self.dpi.method = method
            ok, text = self._summarize(probe(f"http://127.0.0.1:{self.dpi.port}", TEST_URLS, timeout=10))
            if ok:
                self.events.put(("autopick", method, True, f"Подобран метод «{METHOD_LABELS[method]}». {text}"))
                return
        self.events.put(("autopick", None, False,
                         "Ни один метод не сработал. Возможно, проблема не в DPI (нет сети или блокировка по IP)."))

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
            if event[2]:
                self._offer_bypass(self._fetch_clicked)
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
        elif kind == "autopick":
            _, method, ok, text = event
            if method:
                self.settings["dpi_method"] = method
                save_settings(self.settings)
                self.dpi_method_menu.set(METHOD_LABELS[method])
            elif self.dpi.running:
                self.dpi.method = self.settings["dpi_method"]
            self.proxy_result.configure(text=text, text_color=OK if ok else ERR)
            self.autopick_btn.configure(state="normal")
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
