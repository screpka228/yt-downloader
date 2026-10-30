"""Точка входа. Сначала обновляем yt-dlp, потом открываем окно."""
import deps
from settings import load_settings


def main() -> None:
    if load_settings()["auto_update_ytdlp"]:
        deps.update_ytdlp_at_startup()  # скачиваем более новую yt-dlp, если она есть
    deps.install_ytdlp_override()  # и подключаем её вместо встроенной
    from gui import App

    App().mainloop()


if __name__ == "__main__":
    main()
