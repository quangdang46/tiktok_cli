package com.tiktoksummarizer

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import android.Manifest
import android.content.pm.PackageManager

class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        Prefs.init(this)

        val groq = findViewById<EditText>(R.id.groqKey)
        val gemini = findViewById<EditText>(R.id.geminiKey)
        groq.setText(Prefs.groqKey)
        gemini.setText(Prefs.geminiKey)

        val status = findViewById<TextView>(R.id.status)

        fun refreshStatus() {
            val ok = mutableListOf<String>()
            if (Settings.canDrawOverlays(this)) ok += "overlay ✓"
            if (Prefs.groqKey.isNotBlank() && Prefs.geminiKey.isNotBlank()) ok += "keys ✓"
            status.text = if (ok.isEmpty()) "Chưa cấu hình xong" else ok.joinToString("  ·  ")
        }

        findViewById<Button>(R.id.btnOverlay).setOnClickListener {
            if (!Settings.canDrawOverlays(this)) {
                startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            } else toast("Đã có quyền overlay")
        }

        findViewById<Button>(R.id.btnUsage).setOnClickListener {
            startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
        }

        findViewById<Button>(R.id.btnMic).setOnClickListener {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }

        findViewById<Button>(R.id.btnStart).setOnClickListener {
            Prefs.groqKey = groq.text.toString().trim()
            Prefs.geminiKey = gemini.text.toString().trim()
            when {
                !Settings.canDrawOverlays(this) -> toast("Cần cấp quyền overlay trước (bước 1)")
                Prefs.groqKey.isBlank() || Prefs.geminiKey.isBlank() -> toast("Nhập đủ 2 API key")
                else -> {
                    startForegroundService(Intent(this, BubbleService::class.java))
                    toast("Bubble đã hiện — mở TikTok rồi bấm vào bubble")
                    finish()
                }
            }
        }

        refreshStatus()
    }

    override fun onResume() { super.onResume(); }
    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()
}
