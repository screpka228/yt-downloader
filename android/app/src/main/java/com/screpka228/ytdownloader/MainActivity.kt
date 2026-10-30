package com.screpka228.ytdownloader

import android.os.Bundle
import android.os.Environment
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) { DownloadScreen() }
            }
        }
    }
}

@Composable
fun DownloadScreen() {
    var url by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("Вставьте ссылку на видео") }
    var progress by remember { mutableFloatStateOf(0f) }
    var busy by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("YT Downloader", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Ссылка: YouTube, TikTok, Rutube, VK и другие") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            enabled = !busy && url.startsWith("https://"),
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                busy = true
                progress = 0f
                status = "Загрузка…"
                thread {
                    try {
                        val outDir = Environment.getExternalStoragePublicDirectory(
                            Environment.DIRECTORY_DOWNLOADS,
                        ).absolutePath
                        val request = YoutubeDLRequest(url).apply {
                            addOption("-o", "$outDir/%(title)s.%(ext)s")
                            addOption("-f", "bv*[height<=1080]+ba/b[height<=1080]")
                            addOption("--merge-output-format", "mp4")
                        }
                        YoutubeDL.getInstance().execute(request, null) { value, _, _ ->
                            progress = value / 100f
                        }
                        status = "Готово: сохранено в Загрузки"
                    } catch (e: Exception) {
                        status = "Ошибка: ${e.message ?: "неизвестная"}"
                    } finally {
                        busy = false
                    }
                }
            },
        ) { Text("Скачать") }
        LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
        Text(status)
    }
}
