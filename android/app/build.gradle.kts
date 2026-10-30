import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Ключ подписи лежит ВНЕ репозитория (см. README в android/). Один и тот же ключ нужен
// для всех обновлений: иначе Android откажется ставить новую версию поверх старой.
val keysFile = File(System.getProperty("user.home"), ".yt-downloader-keys/keystore.properties")
val keys = Properties().apply {
    if (keysFile.exists()) keysFile.inputStream().use { load(it) }
}

android {
    namespace = "com.screpka228.ytdownloader"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.screpka228.ytdownloader" // менять нельзя после первого релиза
        minSdk = 26
        targetSdk = 35
        versionCode = 1 // при каждом выпуске увеличивайте на 1
        versionName = "1.0.0"
    }

    signingConfigs {
        create("release") {
            if (keys.isNotEmpty()) {
                storeFile = File(keys.getProperty("storeFile"))
                storePassword = keys.getProperty("storePassword")
                keyAlias = keys.getProperty("keyAlias")
                keyPassword = keys.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keys.isNotEmpty()) signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // Готовые yt-dlp и ffmpeg для Android (без собственного обхода блокировок).
    val youtubedlVersion = "0.18.1"
    implementation("io.github.junkfood02.youtubedl-android:library:$youtubedlVersion")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:$youtubedlVersion")

    implementation(platform("androidx.compose:compose-bom:2024.09.02"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.activity:activity-compose:1.9.2")
}
