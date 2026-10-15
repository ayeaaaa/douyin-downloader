package com.ayeaaaa.dydl

import android.annotation.SuppressLint
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var prefs: SharedPreferences

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences("dydl", MODE_PRIVATE)
        webView = findViewById(R.id.webview)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            mediaPlaybackRequiresUserGesture = false
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                val url = request.url.toString()
                // 站内导航保持在 WebView 内
                return !(url.startsWith("http://") || url.startsWith("https://"))
            }
        }

        findViewById<Button>(R.id.btn_settings).setOnClickListener { showServerDialog() }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun serverUrl(): String =
        (prefs.getString("server", "") ?: "").trim().trimEnd('/')

    private fun handleIntent(intent: Intent?) {
        val sharedText = if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)
        } else {
            null
        }

        val server = serverUrl()
        if (server.isEmpty()) {
            showServerDialog()
            return
        }
        when {
            !sharedText.isNullOrBlank() -> {
                val encoded = Uri.encode(sharedText)
                webView.loadUrl("$server/?text=$encoded")
            }
            webView.url == null -> webView.loadUrl("$server/")
        }
    }

    private fun showServerDialog() {
        val input = EditText(this).apply {
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setText(serverUrl())
            hint = getString(R.string.server_hint)
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.server_title)
            .setMessage(R.string.server_message)
            .setView(input)
            .setPositiveButton(R.string.server_save) { _, _ ->
                val value = input.text.toString().trim().trimEnd('/')
                prefs.edit().putString("server", value).apply()
                if (value.isNotEmpty()) {
                    webView.loadUrl("$value/")
                }
            }
            .setNegativeButton(R.string.server_cancel, null)
            .show()
    }
}
