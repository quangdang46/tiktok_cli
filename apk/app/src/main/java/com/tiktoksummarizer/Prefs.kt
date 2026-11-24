package com.tiktoksummarizer

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "tts_prefs"
    private lateinit var sp: SharedPreferences

    fun init(ctx: Context) {
        sp = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    }

    var groqKey: String
        get() = sp.getString("groq_key", "") ?: ""
        set(v) = sp.edit().putString("groq_key", v).apply()

    var geminiKey: String
        get() = sp.getString("gemini_key", "") ?: ""
        set(v) = sp.edit().putString("gemini_key", v).apply()

    var geminiModel: String
        get() = sp.getString("gemini_model", "gemini-2.5-flash-lite") ?: "gemini-2.5-flash-lite"
        set(v) = sp.edit().putString("gemini_model", v).apply()

    var summaryLanguage: String
        get() = sp.getString("summary_lang", "Tiếng Việt") ?: "Tiếng Việt"
        set(v) = sp.edit().putString("summary_lang", v).apply()
}
