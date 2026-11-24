package com.tiktoksummarizer

import java.util.concurrent.CopyOnWriteArrayList

/** Shared state between CaptureService (producer) and BubbleService (UI). */
object Bus {
    const val IDLE = "idle"
    const val RECORDING = "recording"
    const val PROCESSING = "processing"
    const val DONE = "done"
    const val ERROR = "error"

    @Volatile var state = IDLE
    @Volatile var statusText = "Sẵn sàng"
    @Volatile var summary: String? = null
    @Volatile var transcript: String? = null
    @Volatile var error: String? = null

    val listeners = CopyOnWriteArrayList<() -> Unit>()

    fun setState(s: String, msg: String) {
        state = s
        statusText = msg
        listeners.forEach { runCatching { it() } }
    }

    fun finishOk(summary: String, transcript: String) {
        this.summary = summary
        this.transcript = transcript
        error = null
        setState(DONE, "Xong")
    }

    fun finishError(msg: String) {
        error = msg
        setState(ERROR, msg)
    }

    fun reset() {
        summary = null
        transcript = null
        error = null
        setState(IDLE, "Sẵn sàng")
    }
}
