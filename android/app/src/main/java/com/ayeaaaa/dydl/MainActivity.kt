package com.ayeaaaa.dydl

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.URLUtil
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

/**
 * Standalone mode: the app runs its own web UI + API locally.
 *
 * - [LocalServer] serves the UI and the /api endpoints on 127.0.0.1
 * - [SignerController] keeps a hidden WebView that signs requests and
 *   fetches the douyin detail API through its own network stack
 * - [CookieStore] persists user cookies and syncs them into the WebView
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var signer: SignerController
    private lateinit var cookieStore: CookieStore
    private lateinit var server: LocalServer
    private var bootstrapRequested = false
    private var uiShim = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        uiShim = loadUiShim()
        cookieStore = CookieStore(this)
        signer = SignerController(this)
        signer.create()
        server = LocalServer(this, signer, cookieStore)
        val port = server.start()

        webView = findViewById(R.id.webview)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                val url = request.url.toString()
                return !(url.startsWith("http://") || url.startsWith("https://"))
            }

            override fun onPageFinished(view: WebView, url: String) {
                // Runtime shim for the frozen UI (blob downloads -> local server).
                view.evaluateJavascript(uiShim, null)
            }
        }
        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            startSystemDownload(url, userAgent, contentDisposition, mimeType)
        }

        val settingsButton = findViewById<Button>(R.id.btn_settings)
        settingsButton.setOnClickListener { runBootstrap() }

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

        webView.loadUrl("http://127.0.0.1:$port/")
        cookieStore.syncToWebView()
        maybeBootstrap()
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    override fun onDestroy() {
        super.onDestroy()
        server.stop()
        signer.destroy()
    }

    private fun loadUiShim(): String {
        return try {
            assets.open("www/_ui-shim.js").use { it.readBytes().toString(Charsets.UTF_8) }
        } catch (e: Exception) {
            ""
        }
    }

    private fun maybeBootstrap() {
        if (bootstrapRequested) return
        if (signer.hasUifid()) return
        if (cookieStore.status().optInt("entries", 0) > 0) return
        runBootstrap()
    }

    private fun runBootstrap() {
        bootstrapRequested = true
        Toast.makeText(this, "正在初始化(生成设备标识)…", Toast.LENGTH_SHORT).show()
        signer.bootstrap { ok ->
            if (ok) {
                webView.reload()
            }
        }
    }

    private fun handleIntent(intent: Intent?) {
        val sharedText = if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)
        } else {
            null
        }
        if (!sharedText.isNullOrBlank()) {
            webView.loadUrl("http://127.0.0.1:${server.port}/?text=" + Uri.encode(sharedText))
        }
    }

    private fun startSystemDownload(
        url: String,
        userAgent: String?,
        contentDisposition: String?,
        mimeType: String?,
    ) {
        try {
            val request = DownloadManager.Request(Uri.parse(url))
            request.setNotificationVisibility(
                DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
            )
            request.setMimeType(mimeType)
            if (!userAgent.isNullOrBlank()) {
                request.addRequestHeader("User-Agent", userAgent)
            }
            val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
            request.setTitle(name)
            val manager = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            manager.enqueue(request)
            Toast.makeText(this, "已加入系统下载: $name", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "下载失败: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}
