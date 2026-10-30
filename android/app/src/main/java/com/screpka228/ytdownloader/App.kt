package com.screpka228.ytdownloader

import android.app.Application
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL

/** Запускается один раз: готовит yt-dlp и ffmpeg, которые входят в библиотеку. */
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        // Если движок не поднялся, приложение всё равно открывается и показывает причину,
        // а не падает сразу после запуска.
        try {
            YoutubeDL.getInstance().init(this)
            FFmpeg.getInstance().init(this)
        } catch (e: Exception) {
            Log.e(TAG, "Не удалось инициализировать yt-dlp/ffmpeg", e)
            initError = e.message ?: e.javaClass.simpleName
        }
    }

    companion object {
        private const val TAG = "YTDownloader"

        /** Текст ошибки запуска движка или null, если всё в порядке. */
        @Volatile
        var initError: String? = null
    }
}
