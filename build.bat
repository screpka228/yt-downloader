@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] Устанавливаю зависимости...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto error

echo [2/3] Создаю иконку...
python make_icon.py
if errorlevel 1 goto error

echo [3/3] Собираю YTDownloader.exe (это займёт несколько минут)...
python -m PyInstaller --noconfirm --onefile --windowed --name YTDownloader ^
  --icon icon.ico --add-data "icon.ico;." ^
  --collect-all customtkinter --collect-all imageio_ffmpeg --collect-all yt_dlp ^
  --copy-metadata yt-dlp main.py
if errorlevel 1 goto error

echo.
echo Готово! Файл: dist\YTDownloader.exe
pause
exit /b 0

:error
echo.
echo Что-то пошло не так. Посмотрите сообщения выше.
pause
exit /b 1
