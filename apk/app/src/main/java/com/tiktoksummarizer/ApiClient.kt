package com.tiktoksummarizer

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

object ApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    /** Groq Whisper STT — accepts wav/mp4/etc, multilingual incl. Vietnamese. */
    suspend fun transcribe(wav: File, apiKey: String, model: String = "whisper-large-v3-turbo"): String =
        withContext(Dispatchers.IO) {
            val body = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", wav.name, wav.asRequestBody("audio/wav".toMediaType()))
                .addFormDataPart("model", model)
                .addFormDataPart("response_format", "verbose_json")
                .build()
            val req = Request.Builder()
                .url("https://api.groq.com/openai/v1/audio/transcriptions")
                .header("Authorization", "Bearer $apiKey")
                .post(body)
                .build()
            client.newCall(req).execute().use { res ->
                if (!res.isSuccessful) throw Exception("Groq STT HTTP ${res.code}: ${res.body?.string()?.take(200)}")
                val json = JSONObject(res.body!!.string())
                json.optString("text").ifEmpty {
                    val segs = json.optJSONArray("segments")
                    buildString {
                        for (i in 0 until (segs?.length() ?: 0)) append(segs!!.getJSONObject(i).optString("text"))
                    }
                }
            }
        }

    /** Gemini generateContent — transcript → summary. */
    suspend fun summarize(
        transcript: String,
        apiKey: String,
        model: String,
        language: String
    ): String = withContext(Dispatchers.IO) {
        val prompt = """
            |You are summarizing a TikTok video for a viewer who wants the key points fast.
            |Transcript:
            |${transcript.take(24000)}
            |
            |Respond IN $language. Format:
            |- One-line gist (1 sentence)
            |- Key points (3-6 bullets)
            |- Tone/topic tags (3-5 words)
        """.trimMargin()

        val payload = JSONObject()
            .put("contents", org.json.JSONArray().put(
                JSONObject().put("parts", org.json.JSONArray().put(JSONObject().put("text", prompt)))
            ))
            .put("generationConfig", JSONObject().put("temperature", 0.3))

        val req = Request.Builder()
            .url("https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent?key=$apiKey")
            .post(payload.toString().toRequestBody("application/json".toMediaType()))
            .build()
        client.newCall(req).execute().use { res ->
            if (!res.isSuccessful) throw Exception("Gemini HTTP ${res.code}: ${res.body?.string()?.take(200)}")
            val json = JSONObject(res.body!!.string())
            val parts = json.getJSONArray("candidates").getJSONObject(0)
                .getJSONObject("content").getJSONArray("parts")
            buildString {
                for (i in 0 until parts.length()) append(parts.getJSONObject(i).optString("text"))
            }
        }
    }
}
