package com.ayeaaaa.dydl

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * Runs the signing stack (webmssdk / secsdk / bdms / slardar / verifycenter)
 * inside a hidden WebView.
 *
 * The signer page is served under https://www.douyin.com/__signer/ via
 * [shouldInterceptRequest], so it shares the douyin.com origin: real cookies,
 * real environment data, and same-origin fetch through the WebView's network
 * stack (Chrome TLS).
 */
class SignerController(private val context: Context) {

    lateinit var webView: WebView
        private set

    private val pending = ConcurrentHashMap<String, (JSONObject) -> Unit>()
    private val ids = AtomicInteger(0)

    @Volatile
    var ready = false
        private set

    @Volatile
    private var bootstrapDone = false
    private var bootstrapCallback: ((Boolean) -> Unit)? = null

    @SuppressLint("SetJavaScriptEnabled")
    fun create() {
        webView = WebView(context)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            cacheMode = WebSettings.LOAD_DEFAULT
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest
            ): WebResourceResponse? {
                val url = request.url.toString()
                if (url.startsWith(SIGNER_PREFIX)) {
                    return serveAsset(url)
                }
                return null
            }

            override fun onPageFinished(view: WebView, url: String) {
                when {
                    url.startsWith(SIGNER_PREFIX) -> {
                        ready = true
                        bootstrapCallback?.let { cb ->
                            bootstrapCallback = null
                            cb(true)
                        }
                    }
                    url.startsWith("https://www.douyin.com") && bootstrapInProgress -> {
                        // let the page scripts generate UIFID_TEMP / ttwid, then reload signer
                        webView.postDelayed({
                            CookieManager.getInstance().flush()
                            bootstrapInProgress = false
                            loadSignerPage()
                        }, 6000)
                    }
                }
            }
        }
        webView.addJavascriptInterface(SignerBridge(), "AndroidSigner")
        loadSignerPage()
    }

    @Volatile
    private var bootstrapInProgress = false

    /** Visit douyin.com once so the site generates ttwid / UIFID_TEMP / s_v_web_id. */
    fun bootstrap(callback: (Boolean) -> Unit) {
        bootstrapCallback = callback
        bootstrapInProgress = true
        webView.post { webView.loadUrl("https://www.douyin.com/") }
    }

    fun hasUifid(): Boolean {
        val cookie = try {
            CookieManager.getInstance().getCookie("https://www.douyin.com") ?: ""
        } catch (e: Exception) {
            ""
        }
        return cookie.contains("UIFID=") || cookie.contains("UIFID_TEMP=")
    }

    private fun serveAsset(url: String): WebResourceResponse {
        val path = url.removePrefix(SIGNER_PREFIX).substringBefore('?')
        return try {
            val stream = context.assets.open("signer/$path")
            WebResourceResponse(mimeOf(path), null, stream)
        } catch (e: Exception) {
            WebResourceResponse(
                "text/plain", "utf-8", 404, "Not Found", emptyMap(),
                ByteArrayInputStream(ByteArray(0))
            )
        }
    }

    private fun loadSignerPage() {
        webView.post { webView.loadUrl(SIGNER_PREFIX + "index.html") }
    }

    fun signAndFetch(path: String, callback: (JSONObject) -> Unit) {
        if (!ready) {
            val obj = JSONObject()
            obj.put("ok", false)
            obj.put("error", "signer not ready")
            callback(obj)
            return
        }
        val id = "r" + ids.incrementAndGet()
        pending[id] = callback
        val js = "window.__signer && window.__signer.signAndFetch(" +
            JSONObject.quote(path) + ", " + JSONObject.quote(id) + ")"
        webView.post { webView.evaluateJavascript(js, null) }
    }

    inner class SignerBridge {
        @JavascriptInterface
        fun onResult(json: String) {
            try {
                val obj = JSONObject(json)
                val id = obj.optString("id")
                val cb = pending.remove(id) ?: return
                cb(obj)
            } catch (e: Exception) {
            }
        }

        @JavascriptInterface
        fun onReady() {
            ready = true
        }
    }

    companion object {
        const val SIGNER_PREFIX = "https://www.douyin.com/__signer/"

        fun mimeOf(path: String): String = when {
            path.endsWith(".js") -> "application/javascript"
            path.endsWith(".html") -> "text/html"
            path.endsWith(".css") -> "text/css"
            path.endsWith(".json") -> "application/json"
            else -> "application/octet-stream"
        }
    }
}
