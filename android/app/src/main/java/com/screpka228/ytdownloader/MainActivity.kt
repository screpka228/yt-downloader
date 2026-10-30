package com.screpka228.ytdownloader

import android.os.Bundle
import android.os.Environment
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlin.concurrent.thread

private val Accent = Color(0xFFE53935)
private val Background = Color(0xFF0F0F14)
private val CardColor = Color(0xFF1B1B24)
private val TextPrimary = Color(0xFFF2F2F5)
private val TextMuted = Color(0xFF9A9AA8)

private val DarkScheme = darkColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    background = Background,
    onBackground = TextPrimary,
    surface = Background,
    onSurface = TextPrimary,
    surfaceVariant = CardColor,
    onSurfaceVariant = TextMuted,
    outline = Color(0xFF3A3A48),
)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = DarkScheme) {
                Surface(modifier = Modifier.fillMaxSize(), color = Background) { DownloadScreen() }
            }
        }
    }
}

@Composable
fun DownloadScreen() {
    var url by remember { mutableStateOf("") }
    var status by remember {
        mutableStateOf(App.initError?.let { "Движок не запустился: $it" } ?: "Вставьте ссылку на видео")
    }
    var progress by remember { mutableFloatStateOf(0f) }
    var busy by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "YT Downloader",
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                    color = TextPrimary,
                )
                Text(
                    "Видео с YouTube, TikTok, Rutube, VK и других сайтов",
                    fontSize = 13.sp,
                    color = TextMuted,
                )
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = CardColor),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("Ссылка на видео") },
                    placeholder = { Text("https://…") },
                    singleLine = true,
                    enabled = !busy,
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Accent,
                        unfocusedBorderColor = Color(0xFF3A3A48),
                        focusedLabelColor = Accent,
                        cursorColor = Accent,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    enabled = !busy && url.startsWith("https://"),
                    modifier = Modifier.fillMaxWidth().height(54.dp),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Accent,
                        contentColor = Color.White,
                        disabledContainerColor = Color(0xFF3A2A2A),
                        disabledContentColor = TextMuted,
                    ),
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
                                status = "Готово: сохранено в папку «Загрузки»"
                            } catch (e: Exception) {
                                status = "Ошибка: ${e.message ?: "неизвестная"}"
                            } finally {
                                busy = false
                            }
                        }
                    },
                ) {
                    Text("Скачать", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = CardColor),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        status,
                        color = TextPrimary,
                        fontSize = 14.sp,
                        modifier = Modifier.weight(1f),
                    )
                    if (busy || progress > 0f) {
                        Text(
                            "${(progress * 100).toInt()}%",
                            color = Accent,
                            fontWeight = FontWeight.Bold,
                            fontSize = 14.sp,
                        )
                    }
                }
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier.fillMaxWidth().height(6.dp),
                    color = Accent,
                    trackColor = Color(0xFF2A2A36),
                )
            }
        }
    }
}
