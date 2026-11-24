package com.tiktoksummarizer

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Handler
import android.os.Looper

/**
 * Polls UsageStats to detect which app is in the foreground.
 * Requires PACKAGE_USAGE_STATS ("Usage access") granted by the user.
 */
class ForegroundWatcher(private val ctx: Context) {

    private val handler = Handler(Looper.getMainLooper())
    private var lastCheck = System.currentTimeMillis()
    private var running = false

    var onForeground: ((pkg: String?) -> Unit)? = null
    private var lastPkg: String? = null

    private val poll = object : Runnable {
        override fun run() {
            val pkg = queryForeground()
            if (pkg != lastPkg) {
                lastPkg = pkg
                onForeground?.invoke(pkg)
            }
            handler.postDelayed(this, 800)
        }
    }

    fun start() {
        if (running) return
        running = true
        lastCheck = System.currentTimeMillis()
        handler.post(poll)
    }

    fun stop() {
        running = false
        handler.removeCallbacks(poll)
    }

    private fun queryForeground(): String? {
        val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        val events = usm.queryEvents(lastCheck, now)
        lastCheck = now
        val ev = UsageEvents.Event()
        var pkg: String? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(ev)
            if (ev.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                pkg = ev.packageName
            }
        }
        return pkg
    }
}
