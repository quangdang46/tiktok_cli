package com.tiktoksummarizer

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.app.NotificationCompat

/**
 * Foreground service owning the overlay bubble + result panel.
 * Bubble tap → (if TikTok is foreground) request MediaProjection consent
 * → CaptureService records → summary appears in the panel.
 */
class BubbleService : Service() {

    companion object {
        private const val CHANNEL_ID = "tts_bubble"
        private const val NOTIF_ID = 7
        private val TIKTOK_PKGS = setOf(
            "com.zhiliaoapp.musically",   // TikTok global
            "com.ss.android.ugc.trill",   // TikTok (newer pkg)
            "com.ss.android.ugc.aweme"    // Douyin
        )
    }

    private lateinit var wm: WindowManager
    private var bubble: TextView? = null
    private var panel: View? = null
    private var panelBody: TextView? = null
    private var watcher: ForegroundWatcher? = null
    @Volatile private var tiktokForeground = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundWithType()
        showBubble()
        startWatcher()
        Bus.listeners.add(::refreshPanel)
        refreshPanel()
        return START_STICKY
    }

    // ---------- overlay views ----------

    private fun showBubble() {
        wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val tv = TextView(this).apply {
            text = "📝"
            textSize = 22f
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(0xFFFE2C55.toInt())
            }
            elevation = 12f
        }
        val params = WindowManager.LayoutParams(
            dp(56), dp(56),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = resources.displayMetrics.widthPixels - dp(76)
            y = resources.displayMetrics.heightPixels / 2
        }
        attachDrag(tv, params)
        wm.addView(tv, params)
        bubble = tv
    }

    private fun showPanel() {
        if (panel != null) return
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = GradientDrawable().apply {
                cornerRadius = dp(16).toFloat()
                setColor(0xFF161616.toInt())
            }
            setPadding(dp(16), dp(12), dp(16), dp(12))
        }
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        head.addView(TextView(this).apply {
            text = "TikTok Summary"
            setTextColor(Color.WHITE)
            textSize = 15f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(TextView(this).apply {
            text = "✕"
            setTextColor(0xFFAAAAAA.toInt())
            textSize = 18f
            setPadding(dp(10), 0, 0, 0)
            setOnClickListener { removePanel() }
        })
        root.addView(head)

        val scroll = ScrollView(this)
        panelBody = TextView(this).apply {
            setTextColor(0xFFEEEEEE.toInt())
            textSize = 14f
            setPadding(0, dp(10), 0, dp(10))
        }
        scroll.addView(panelBody)
        root.addView(scroll, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
        ))

        val params = WindowManager.LayoutParams(
            dp(380), dp(420),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.END
            y = dp(24)
        }
        wm.addView(root, params)
        panel = root
    }

    private fun removePanel() {
        panel?.let { runCatching { wm.removeView(it) } }
        panel = null
        panelBody = null
        Bus.reset()
    }

    private fun refreshPanel() {
        val body = panelBody ?: return
        when (Bus.state) {
            Bus.IDLE -> body.text = "Sẵn sàng."
            Bus.RECORDING -> body.text = Bus.statusText
            Bus.PROCESSING -> body.text = Bus.statusText
            Bus.DONE -> body.text = "${Bus.summary}\n\n── Transcript ──\n${Bus.transcript}"
            Bus.ERROR -> body.text = "Lỗi: ${Bus.error}"
        }
    }

    private fun attachDrag(view: View, params: WindowManager.LayoutParams) {
        var dx = 0f; var dy = 0f; var sx = 0f; var sy = 0f; var moved = false
        view.setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    sx = e.rawX; sy = e.rawY; dx = params.x.toFloat(); dy = params.y.toFloat(); moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val mx = e.rawX - sx; val my = e.rawY - sy
                    if (kotlin.math.abs(mx) + kotlin.math.abs(my) > 12) moved = true
                    params.x = (dx + mx).toInt(); params.y = (dy + my).toInt()
                    runCatching { wm.updateViewLayout(v, params) }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!moved) onBubbleTap()
                    true
                }
                else -> false
            }
        }
    }

    private fun onBubbleTap() {
        when (Bus.state) {
            Bus.IDLE -> {
                if (!tiktokForeground) {
                    Bus.setState(Bus.ERROR, "Hãy mở app TikTok trước rồi bấm lại")
                    showPanel()
                } else {
                    // Ask for MediaProjection consent via transparent activity
                    val i = Intent(this, ConsentActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    startActivity(i)
                }
            }
            Bus.RECORDING -> {
                startService(Intent(this, CaptureService::class.java).setAction(CaptureService.ACTION_STOP))
            }
            Bus.PROCESSING -> { /* wait */ }
            Bus.DONE, Bus.ERROR -> { showPanel(); Bus.reset() }
        }
        if (Bus.state == Bus.IDLE || Bus.state == Bus.RECORDING || Bus.state == Bus.PROCESSING) {
            showPanel()
        }
        refreshPanel()
    }

    // ---------- foreground detection ----------

    private fun startWatcher() {
        watcher = ForegroundWatcher(this).also { w ->
            w.onForeground = { pkg ->
                tiktokForeground = pkg in TIKTOK_PKGS
                bubble?.alpha = if (tiktokForeground) 1f else 0.55f
            }
            w.start()
        }
    }

    // ---------- service plumbing ----------

    private fun startForegroundWithType() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "TikTok Summarizer", NotificationManager.IMPORTANCE_LOW)
        )
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val notif: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("TikTok Summarizer")
            .setContentText("Bubble đang hiển thị")
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(
                NOTIF_ID, notif,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    override fun onDestroy() {
        Bus.listeners.remove(::refreshPanel)
        watcher?.stop()
        bubble?.let { runCatching { wm.removeView(it) } }
        panel?.let { runCatching { wm.removeView(it) } }
        super.onDestroy()
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}
