"""Главное окно программы (customtkinter)."""
import queue
import re
import threading
import urllib.request
import webbrowser
from io import BytesIO
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp
from PIL import Image

import deps
import downloader
from app_config import APP_NAME, APP_VERSION, resource_dir
from downloader import AUDIO_FORMATS, VIDEO_HEIGHTS, Job, UserError
from settings import load_settings, save_settings

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MODE_VIDEO = "Видео"
MODE_AUDIO = "Музыка"
COLOR_OK = "#4ade80"
COLOR_ERR = "#f87171"
COLOR_MUTED = "#9ca3af"
STATUS_TEXT = {
    "waiting": "в очереди",
    "running": "загружается",
    "done": "готово",
    "error": "ошибка",
    "cancelled": "отменено",
}
STATUS_COLOR = {
    "waiting": COLOR_MUTED,
    "running": "#60a5fa",
    "done": COLOR_OK,
    "error": COLOR_ERR,
    "cancelled": COLOR_MUTED,
}


def format_speed(bytes_per_sec: float) -> str:
    return f"{bytes_per_sec / 1024 / 1024:.2f} МБ/с"


def format_eta(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    return format_eta(seconds)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("920x780")
        self.minsize(860, 680)
        self._set_icon()

        self.events = queue.Queue()  # сообщения от фоновых потоков к окну
        self.jobs_queue = queue.Queue()  # очередь задач для рабочего потока
        self.jobs: list[Job] = []
        self.active_job: Job | None = None
        self.info = None
        self.thumb_image = None
        self.ffmpeg_dir = deps.ensure_ffmpeg()

        self._build_ui()
        self._apply_settings()
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._check_app_update, daemon=True).start()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- Интерфейс ----------

    def _set_icon(self):
        try:
            self.iconbitmap(str(resource_dir() / "icon.ico"))
        except Exception:
            # Иконки нет (например, при запуске из исходников) — ничего страшного.
            pass

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(8, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(16, 4), sticky="ew")
        ctk.CTkLabel(
            header, text="YT Downloader", font=ctk.CTkFont(size=24, weight="bold")
        ).pack(side="left")
        self.update_btn = ctk.CTkButton(
            header, text="Проверить обновления", width=190, command=self._manual_update_clicked
        )
        self.update_btn.pack(side="right")
        self.version_label = ctk.CTkLabel(
            header, text=f"yt-dlp {yt_dlp.version.__version__}", text_color=COLOR_MUTED
        )
        self.version_label.pack(side="right", padx=12)

        self.mode_switch = ctk.CTkSegmentedButton(
            self, values=[MODE_VIDEO, MODE_AUDIO], command=self._on_mode_change, width=260
        )
        self.mode_switch.grid(row=1, column=0, padx=20, pady=(8, 8), sticky="w")

        url_row = ctk.CTkFrame(self, fg_color="transparent")
        url_row.grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        url_row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            url_row, height=38, placeholder_text="Вставьте ссылку на видео или плейлист"
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            url_row, text="Вставить из буфера", width=170, command=self._paste
        ).grid(row=0, column=1, padx=(0, 8))
        self.fetch_btn = ctk.CTkButton(
            url_row, text="Получить форматы", width=160, command=self._fetch_clicked
        )
        self.fetch_btn.grid(row=0, column=2)

        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=3, column=0, padx=20, pady=6, sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        self.thumb_label = ctk.CTkLabel(
            card, text="Превью появится здесь", width=256, height=144,
            corner_radius=8, fg_color=("gray75", "gray25"),
        )
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=12, pady=12)
        self.title_label = ctk.CTkLabel(
            card, text="Вставьте ссылку и нажмите «Получить форматы»",
            font=ctk.CTkFont(size=16, weight="bold"), anchor="w", justify="left", wraplength=540,
        )
        self.title_label.grid(row=0, column=1, sticky="ew", padx=(4, 12), pady=(12, 2))
        self.meta_label = ctk.CTkLabel(card, text="", text_color=COLOR_MUTED, anchor="w")
        self.meta_label.grid(row=1, column=1, sticky="ew", padx=(4, 12))
        self.options_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.options_frame.grid(row=2, column=1, sticky="w", padx=(4, 12), pady=(6, 12))
        self.option_label = ctk.CTkLabel(self.options_frame, text="Качество:")
        self.option_label.pack(side="left", padx=(0, 8))
        self.quality_menu = ctk.CTkOptionMenu(
            self.options_frame, values=[f"{h}p" for h in VIDEO_HEIGHTS], width=150
        )
        self.audio_menu = ctk.CTkOptionMenu(
            self.options_frame, values=list(AUDIO_FORMATS), width=180
        )

        setup = ctk.CTkFrame(self, fg_color="transparent")
        setup.grid(row=4, column=0, padx=20, pady=6, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(setup, text="Папка:").grid(row=0, column=0, padx=(0, 8))
        self.folder_entry = ctk.CTkEntry(setup, height=34)
        self.folder_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(
            setup, text="Выбрать папку", width=150, command=self._choose_folder
        ).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkLabel(setup, text="Прокси:").grid(row=1, column=0, padx=(0, 8), pady=(8, 0))
        self.proxy_entry = ctk.CTkEntry(
            setup, height=34,
            placeholder_text="необязательно, например http://адрес:порт",
        )
        self.proxy_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        self.add_btn = ctk.CTkButton(
            self, text="＋ Добавить в очередь", height=42,
            font=ctk.CTkFont(size=15, weight="bold"), command=self._add_to_queue,
        )
        self.add_btn.grid(row=5, column=0, padx=20, pady=(10, 6), sticky="ew")

        progress_card = ctk.CTkFrame(self, corner_radius=12)
        progress_card.grid(row=6, column=0, padx=20, pady=6, sticky="ew")
        progress_card.grid_columnconfigure(0, weight=1)
        self.stage_label = ctk.CTkLabel(progress_card, text="Нет активной загрузки", anchor="w")
        self.stage_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        self.progress_bar = ctk.CTkProgressBar(progress_card)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=12)
        self.stats_label = ctk.CTkLabel(progress_card, text="", text_color=COLOR_MUTED, anchor="w")
        self.stats_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 10))
        self.cancel_btn = ctk.CTkButton(
            progress_card, text="Отмена", width=110,
            fg_color="#7f1d1d", hover_color="#991b1b",
            command=self._cancel_active, state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, rowspan=3, padx=12)

        ctk.CTkLabel(
            self, text="Очередь загрузок", font=ctk.CTkFont(weight="bold"), anchor="w"
        ).grid(row=7, column=0, sticky="w", padx=22)
        self.queue_frame = ctk.CTkScrollableFrame(self, corner_radius=12)
        self.queue_frame.grid(row=8, column=0, padx=20, pady=(2, 6), sticky="nsew")
        self.status_label = ctk.CTkLabel(
            self, text="Готово к работе", text_color=COLOR_MUTED, anchor="w", wraplength=860
        )
        self.status_label.grid(row=9, column=0, padx=22, pady=(0, 12), sticky="ew")

        self._refresh_queue()

    def _apply_settings(self):
        mode = self.settings["mode"]
        self.mode_switch.set(mode if mode in (MODE_VIDEO, MODE_AUDIO) else MODE_VIDEO)
        self.folder_entry.insert(0, self.settings["download_dir"])
        self.proxy_entry.insert(0, self.settings["proxy"])
        self.quality_menu.set(f"{self.settings['video_quality']}p")
        audio = self.settings["audio_format"]
        self.audio_menu.set(audio if audio in AUDIO_FORMATS else next(iter(AUDIO_FORMATS)))
        self._show_options()

    def _show_options(self):
        is_video = self.mode_switch.get() == MODE_VIDEO
        self.option_label.configure(text="Качество:" if is_video else "Формат:")
        self.quality_menu.pack_forget()
        self.audio_menu.pack_forget()
        (self.quality_menu if is_video else self.audio_menu).pack(side="left")

    def _on_mode_change(self, _value):
        self._show_options()

    def _status(self, text: str, kind: str = "info"):
        color = {"error": COLOR_ERR, "ok": COLOR_OK}.get(kind, COLOR_MUTED)
        self.status_label.configure(text=text, text_color=color)

    def _url(self) -> str:
        return self.url_entry.get().strip()

    def _valid_url(self, url: str) -> bool:
        if re.match(r"^https?://\S+$", url):
            return True
        self._status("Неверная ссылка: адрес должен начинаться с https://", "error")
        return False

    # ---------- Кнопки ----------

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
        folder = filedialog.askdirectory(initialdir=self.folder_entry.get() or None)
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)
            self._remember_settings()

    def _fetch_clicked(self):
        url = self._url()
        if not self._valid_url(url):
            return
        self.fetch_btn.configure(state="disabled", text="Получаю…")
        self._status("Получаю информацию о ссылке…")
        threading.Thread(
            target=self._fetch_preview, args=(url, self.proxy_entry.get().strip()), daemon=True
        ).start()

    def _add_to_queue(self):
        url = self._url()
        if not self._valid_url(url):
            return
        out_dir = self.folder_entry.get().strip()
        if not out_dir:
            self._status("Укажите папку для сохранения", "error")
            return
        job = Job(
            url=url,
            mode="video" if self.mode_switch.get() == MODE_VIDEO else "audio",
            out_dir=out_dir,
            proxy=self.proxy_entry.get().strip(),
            height=int(self.quality_menu.get().rstrip("p")),
            audio_format=self.audio_menu.get(),
        )
        self._remember_settings()
        self.jobs.append(job)
        self.jobs_queue.put(job)
        self.url_entry.delete(0, "end")
        self._refresh_queue()
        self._status(f"Добавлено в очередь. Всего задач: {len(self.jobs)}", "ok")

    def _cancel_active(self):
        if self.active_job is not None:
            self.active_job.cancel.set()
            self._status("Отменяю загрузку…")

    def _manual_update_clicked(self):
        self.update_btn.configure(state="disabled", text="Проверяю…")
        threading.Thread(target=self._manual_update, daemon=True).start()

    def _on_close(self):
        if self.active_job is not None and not messagebox.askyesno(
            "Закрыть программу?", "Сейчас идёт загрузка. Всё равно закрыть программу?"
        ):
            return
        if self.active_job is not None:
            self.active_job.cancel.set()
        self._remember_settings()
        self.destroy()

    # ---------- Настройки ----------

    def _remember_settings(self):
        self.settings.update(
            download_dir=self.folder_entry.get().strip() or self.settings["download_dir"],
            proxy=self.proxy_entry.get().strip(),
            mode=self.mode_switch.get(),
            video_quality=int(self.quality_menu.get().rstrip("p")),
            audio_format=self.audio_menu.get(),
        )
        save_settings(self.settings)

    # ---------- Фоновые потоки ----------

    def _fetch_preview(self, url: str, proxy: str):
        try:
            info = downloader.fetch_info(url, proxy, self.ffmpeg_dir)
        except UserError as exc:
            self.events.put(("preview_err", str(exc)))
            return
        except Exception as exc:
            self.events.put(("preview_err", f"Непредвиденная ошибка: {exc}"))
            return

        thumb = None
        if info.thumbnail:
            try:
                request = urllib.request.Request(
                    info.thumbnail, headers={"User-Agent": "Mozilla/5.0"}
                )
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
            self.fetch_btn.configure(state="normal", text="Получить форматы")
            self._show_preview(event[1], event[2])
        elif kind == "preview_err":
            self.fetch_btn.configure(state="normal", text="Получить форматы")
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
        elif kind == "app_update":
            self._offer_app_update(event[1], event[2])
        elif kind == "manual_done":
            self.update_btn.configure(state="normal", text="Проверить обновления")
            self.version_label.configure(text=f"yt-dlp {yt_dlp.version.__version__}")
            self._status(event[1])

    def _show_preview(self, info, thumb: bytes | None):
        self.info = info
        if thumb:
            try:
                image = Image.open(BytesIO(thumb)).convert("RGB")
                self.thumb_image = ctk.CTkImage(light_image=image, dark_image=image, size=(256, 144))
                self.thumb_label.configure(image=self.thumb_image, text="")
            except Exception:
                self.thumb_label.configure(image=None, text="Нет превью")
        else:
            self.thumb_label.configure(image=None, text="Нет превью")

        self.title_label.configure(text=info.title)
        if info.is_playlist:
            self.meta_label.configure(text=f"Плейлист • видео в нём: {info.count}")
        else:
            self.meta_label.configure(text=f"Длительность: {format_duration(info.duration)}")
            choices = downloader.quality_choices(info.heights)
            self.quality_menu.configure(values=[f"{h}p" for h in choices])
            preferred = int(self.settings["video_quality"])
            self.quality_menu.set(f"{next((h for h in choices if h <= preferred), choices[-1])}p")
        self._status("Информация получена. Выберите качество и добавьте в очередь.", "ok")

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
        self.stats_label.configure(text="   •   ".join(parts))

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

    def _refresh_queue(self):
        for widget in self.queue_frame.winfo_children():
            widget.destroy()
        if not self.jobs:
            ctk.CTkLabel(self.queue_frame, text="Очередь пуста", text_color=COLOR_MUTED).pack(
                anchor="w", padx=12, pady=8
            )
            return
        for number, job in enumerate(self.jobs, start=1):
            text = f"{number}. {job.url[:90]}  —  {STATUS_TEXT[job.status]}"
            if job.status == "error" and job.message:
                text += f"\n    {job.message}"
            ctk.CTkLabel(
                self.queue_frame, text=text, anchor="w", justify="left",
                text_color=STATUS_COLOR[job.status], wraplength=780,
            ).pack(fill="x", padx=12, pady=4)

    def _offer_app_update(self, latest: str, url: str):
        if messagebox.askyesno(
            "Доступна новая версия",
            f"Вышла новая версия программы: {latest} (у вас {APP_VERSION}).\n\n"
            "Открыть страницу загрузки?",
        ):
            webbrowser.open(url)
