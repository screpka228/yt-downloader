package com.screpka228.ytdownloader

import android.app.Application
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL

/** Запускается один раз: готовит yt-dlp и ffmpeg, которые входят в библиотеку. */
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        YoutubeDL.getInstance().init(this)
        FFmpeg.getInstance().init(this)
    }
}
