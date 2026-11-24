package com.tiktoksummarizer

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.File
import kotlin.concurrent.thread

/**
 * Foreground service (type mediaProjection) that captures device audio
 * via AudioPlaybackCapture and writes it to a WAV file, then runs the
 * Groq STT + Gemini summary pipeline.
 */
class CaptureService : Service() {

    companion object {
        const val ACTION_START = "com.tiktoksummarizer.START_CAPTURE"
        const val ACTION_STOP = "com.tiktoksummarizer.STOP_CAPTURE"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        private const val CHANNEL_ID = "tts_capture"
        private const val NOTIF_ID = 42
    }

    private var projection: MediaProjection? = null
    private var recorder: AudioRecord? = null
    private var writer: WavUtil.Writer? = null
    private var captureThread: Thread? = null
    @Volatile private var recording = false

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopCapture()
            ACTION_START -> startCapture(intent)
        }
        return START_NOT_STICKY
    }

    private fun startCapture(intent: Intent) {
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA) ?: return
        if (resultCode != Activity.RESULT_OK) {
            Bus.finishError("Không được cấp quyền ghi màn hình")
            stopSelf()
            return
        }

        startForegroundWithType()
        Bus.setState(Bus.RECORDING, "Đang ghi âm TikTok… (bấm bubble để dừng)")

        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val proj = mpm.getMediaProjection(resultCode, data)
        projection = proj

        proj.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                // User revoked consent from system UI — treat as stop.
                stopCapture()
            }
        }, null)

        val config = AudioPlaybackCaptureConfiguration.Builder(proj)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .build()

        val format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(WavUtil.SAMPLE_RATE)
            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
            .build()

        val minBuf = AudioRecord.getMinBufferSize(
            WavUtil.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val rec = AudioRecord.Builder()
            .setAudioPlaybackCaptureConfig(config)
            .setAudioFormat(format)
            .setBufferSizeInBytes(maxOf(minBuf * 2, 8192))
            .build()
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            Bus.finishError("Không khởi tạo được AudioRecord")
            stopSelf()
            return
        }
        recorder = rec

        val out = File(filesDir, "tts_capture.wav")
        out.delete()
        writer = WavUtil.Writer(out)
        recording = true
        rec.startRecording()

        captureThread = thread(name = "tts-capture") {
            val buf = ByteArray(4096)
            try {
                while (recording) {
                    val n = rec.read(buf, 0, buf.size)
                    if (n > 0) writer?.write(buf, n)
                }
            } catch (_: Exception) { }
        }
    }

    private fun stopCapture() {
        if (!recording) { stopSelf(); return }
        recording = false
        captureThread?.join(2000)
        runCatching { recorder?.stop() }
        runCatching { recorder?.release() }
        runCatching { writer?.close() }
        recorder = null
        writer = null
        projection?.stop()
        projection = null

        val wav = File(filesDir, "tts_capture.wav")
        process(wav)
    }

    private fun process(wav: File) {
        if (wav.length() < 1000) {
            Bus.finishError("Audio trống — video có thể không có tiếng, hoặc TikTok không cho capture.")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }
        Bus.setState(Bus.PROCESSING, "Đang phiên âm + tóm tắt…")
        scope.launch {
            try {
                val transcript = ApiClient.transcribe(wav, Prefs.groqKey)
                if (transcript.isBlank()) throw Exception("Transcript rỗng (video không có lời?)")
                val summary = ApiClient.summarize(
                    transcript, Prefs.geminiKey, Prefs.geminiModel, Prefs.summaryLanguage
                )
                Bus.finishOk(summary, transcript)
            } catch (e: Exception) {
                Bus.finishError(e.message ?: e.toString())
            } finally {
                wav.delete()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun startForegroundWithType() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "TikTok Summarizer", NotificationManager.IMPORTANCE_LOW)
        )
        val pi = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        val notif: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("TikTok Summarizer")
            .setContentText("Đang ghi âm — bấm bubble để dừng")
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    override fun onDestroy() {
        if (recording) stopCapture()
        super.onDestroy()
    }
}
