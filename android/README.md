# YT Downloader для Android

Отдельная версия под Android на Kotlin и Jetpack Compose. Использует готовую библиотеку
[youtubedl-android](https://github.com/yausername/youtubedl-android) (yt-dlp и ffmpeg для Android).
Своего обхода блокировок здесь нет.

## Ключ подписи (важно)

Android не ставит обновление поверх приложения, подписанного другим ключом. Поэтому:

1. Ключ создан один раз и лежит **вне репозитория**: `C:\Users\RASKAT\.yt-downloader-keys\`
   (файлы `release.jks` и `keystore.properties`).
2. Скопируйте эту папку в надёжное место (флешка, менеджер паролей). Если ключ потеряется,
   обновить уже установленное приложение будет нельзя, придётся ставить с новым именем пакета.
3. Ключ и пароли никогда не коммитятся. Папка `.yt-downloader-keys` не входит в репозиторий.
4. `applicationId` (`com.screpka228.ytdownloader`) не меняйте после первого релиза.
5. При каждом выпуске увеличивайте `versionCode` в `app/build.gradle.kts`.

## Сборка

Нужен Android Studio (Ladybug или новее) с JDK 17.

1. Откройте папку `android/` в Android Studio.
2. Build → Generate Signed App Bundle / APK, или `./gradlew assembleRelease`.
3. Файл `app-release.apk` появится в `app/build/outputs/apk/release/`.

Этот каркас пока не собран и не запущен на устройстве: Android SDK на компьютере не установлен.
