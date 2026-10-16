package com.ayeaaaa.dydl

import android.content.Context
import android.webkit.CookieManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.net.URL
import java.net.URLDecoder
import java.net.URLEncoder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Minimal local HTTP server powering the web UI inside the app:
 *  - serves the static UI (assets/www)
 *  - implements the same /api contract as the server version (app/main.py)
 *  - proxies media/CDN requests with the required Referer header
 */
class LocalServer(
    private val context: Context,
    private val signer: SignerController,
    private val cookieStore: CookieStore,
) {

    private var serverSocket: ServerSocket? = null
    private var acceptThread: Thread? = null

    @Volatile
    private var running = false

    var port: Int = 0
        private set

    fun start(): Int {
        val socket = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        serverSocket = socket
        port = socket.localPort
        running = true
        acceptThread = Thread {
            while (running) {
                try {
                    val client = socket.accept()
                    Thread { handleClient(client) }.apply { isDaemon = true }.start()
                } catch (e: Exception) {
                    if (!running) break
                }
            }
        }.apply { isDaemon = true; start() }
        return port
    }

    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (e: Exception) {
        }
    }

    // ---------------------------------------------------------------- HTTP --

    private fun handleClient(client: Socket) {
        try {
            client.use { sock ->
                val input = BufferedInputStream(sock.getInputStream())
                val output = BufferedOutputStream(sock.getOutputStream())
                val requestLine = readLine(input) ?: return
                val parts = requestLine.split(" ")
                if (parts.size < 2) return
                val method = parts[0].uppercase()
                val target = parts[1]
                val headers = HashMap<String, String>()
                while (true) {
                    val line = readLine(input) ?: break
                    if (line.isEmpty()) break
                    val idx = line.indexOf(':')
                    if (idx > 0) {
                        headers[line.substring(0, idx).trim().lowercase()] =
                            line.substring(idx + 1).trim()
                    }
                }
                val contentLength = headers["content-length"]?.toIntOrNull() ?: 0

                val uri = URI("http://127.0.0.1" + target)
                val path = uri.path ?: "/"
                val query = parseQuery(uri.rawQuery)

                try {
                    if (method == "POST" && path == "/api/save-blob") {
                        handleSaveBlob(output, query, contentLength, input)
                    } else {
                        val body = readBody(input, contentLength)
                        route(method, path, query, headers, body, output)
                    }
                } catch (e: Exception) {
                    try {
                        sendJson(output, 500, JSONObject().put("error", "服务器内部错误"))
                    } catch (ignored: Exception) {
                    }
                }
                output.flush()
            }
        } catch (e: Exception) {
        }
    }

    private fun readLine(input: InputStream): String? {
        val sb = StringBuilder()
        while (true) {
            val c = input.read()
            if (c < 0) return if (sb.isEmpty()) null else sb.toString()
            if (c == '\n'.code) return sb.toString().trimEnd('\r')
            sb.append(c.toChar())
        }
    }

    private fun readBody(input: InputStream, length: Int): ByteArray {
        if (length <= 0) return ByteArray(0)
        val buf = ByteArray(length)
        var off = 0
        while (off < length) {
            val n = input.read(buf, off, length - off)
            if (n < 0) break
            off += n
        }
        return buf
    }

    /** Streams the request body to a file (used by /api/save-blob). */
    private fun readBodyToFile(input: InputStream, length: Int, target: File): Boolean {
        return try {
            FileOutputStream(target).use { out ->
                var remaining = length.toLong()
                val buf = ByteArray(65536)
                while (remaining > 0) {
                    val n = input.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                    if (n < 0) return false
                    out.write(buf, 0, n)
                    remaining -= n
                }
            }
            true
        } catch (e: Exception) {
            false
        }
    }

    /** Saves the uploaded blob (slides zip from the UI shim) to Downloads. */
    private fun handleSaveBlob(
        output: OutputStream,
        query: Map<String, String>,
        contentLength: Int,
        input: InputStream,
    ) {
        if (contentLength <= 0 || contentLength > 512 * 1024 * 1024) {
            sendJson(output, 400, JSONObject().put("error", "无效的内容长度"))
            return
        }
        val name = (query["name"] ?: "download.zip")
            .replace("/", "_")
            .replace("\\", "_")
            .ifBlank { "download.zip" }
        val temp = File.createTempFile("blob", ".bin", context.cacheDir)
        if (!readBodyToFile(input, contentLength, temp)) {
            temp.delete()
            sendJson(output, 400, JSONObject().put("error", "读取失败"))
            return
        }
        val saved = try {
            saveToDownloads(name, temp)
        } catch (e: Exception) {
            false
        }
        temp.delete()
        if (saved) {
            sendJson(output, 200, JSONObject().put("ok", true).put("name", name))
        } else {
            sendJson(output, 502, JSONObject().put("error", "保存失败"))
        }
    }

    private fun saveToDownloads(name: String, file: File): Boolean {
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.Downloads.DISPLAY_NAME, name)
                put(android.provider.MediaStore.Downloads.MIME_TYPE, "application/octet-stream")
            }
            val uri = context.contentResolver.insert(
                android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, values
            ) ?: return false
            context.contentResolver.openOutputStream(uri)?.use { out ->
                file.inputStream().use { it.copyTo(out, 65536) }
            } ?: return false
            return true
        }
        val dir = context.getExternalFilesDir(android.os.Environment.DIRECTORY_DOWNLOADS)
            ?: return false
        dir.mkdirs()
        file.copyTo(File(dir, name), overwrite = true)
        return true
    }

    private fun parseQuery(raw: String?): Map<String, String> {
        if (raw.isNullOrEmpty()) return emptyMap()
        val map = HashMap<String, String>()
        for (pair in raw.split("&")) {
            if (pair.isEmpty()) continue
            val idx = pair.indexOf('=')
            if (idx < 0) {
                map[URLDecoder.decode(pair, "UTF-8")] = ""
            } else {
                map[URLDecoder.decode(pair.substring(0, idx), "UTF-8")] =
                    URLDecoder.decode(pair.substring(idx + 1), "UTF-8")
            }
        }
        return map
    }

    private fun writeHead(
        output: OutputStream,
        status: Int,
        headers: Map<String, String>,
    ) {
        val sb = StringBuilder()
        sb.append("HTTP/1.1 ").append(status).append(' ').append(statusText(status)).append("\r\n")
        sb.append("Connection: close\r\n")
        for ((k, v) in headers) {
            sb.append(k).append(": ").append(v).append("\r\n")
        }
        sb.append("\r\n")
        output.write(sb.toString().toByteArray(Charsets.UTF_8))
    }

    private fun statusText(status: Int): String = when (status) {
        200 -> "OK"
        206 -> "Partial Content"
        400 -> "Bad Request"
        404 -> "Not Found"
        500 -> "Internal Server Error"
        502 -> "Bad Gateway"
        else -> "OK"
    }

    private fun sendJson(output: OutputStream, status: Int, obj: JSONObject) {
        val bytes = obj.toString().toByteArray(Charsets.UTF_8)
        writeHead(
            output, status,
            mapOf(
                "Content-Type" to "application/json; charset=utf-8",
                "Content-Length" to bytes.size.toString(),
                "Cache-Control" to "no-store",
            )
        )
        output.write(bytes)
    }

    // --------------------------------------------------------------- routes --

    private fun route(
        method: String,
        path: String,
        query: Map<String, String>,
        headers: Map<String, String>,
        body: ByteArray,
        output: OutputStream,
    ) {
        when {
            path == "/healthz" -> sendJson(output, 200, JSONObject().put("status", "ok"))

            path == "/" || path == "/index.html" ->
                sendAsset(output, "www/index.html", "text/html; charset=utf-8")

            path.startsWith("/static/") ->
                sendAsset(output, "www/" + path.removePrefix("/static/"), mimeOf(path))

            path == "/api/parse" && method == "POST" -> handleParse(output, body)

            path == "/api/media" -> handleProxy(
                output, query, headers,
                forceDownload = query["download"] == "1",
                name = query["name"],
            )

            path == "/api/cover" -> handleProxy(output, query, headers, forceDownload = false, name = null)

            path == "/api/download" -> handleDownload(output, query)

            path == "/api/slides/zip" && method == "POST" -> handleZip(output, body)

            path == "/api/cookies/status" -> sendJson(output, 200, cookieStore.status())

            path == "/api/cookies" && method == "POST" -> {
                val content = try {
                    JSONObject(String(body, Charsets.UTF_8)).optString("content", "")
                } catch (e: Exception) {
                    ""
                }
                if (content.isBlank()) {
                    sendJson(output, 400, JSONObject().put("error", "内容格式不正确"))
                } else {
                    sendJson(output, 200, cookieStore.save(content))
                }
            }

            path == "/api/cookies" && method == "DELETE" -> {
                cookieStore.clear()
                val obj = JSONObject()
                obj.put("configured", false)
                obj.put("entries", 0)
                obj.put("updated_at", JSONObject.NULL)
                sendJson(output, 200, obj)
            }

            else -> sendJson(output, 404, JSONObject().put("error", "not found"))
        }
    }

    private fun sendAsset(output: OutputStream, assetPath: String, mime: String) {
        try {
            val stream = context.assets.open(assetPath)
            val bytes = stream.use { it.readBytes() }
            writeHead(
                output, 200,
                mapOf(
                    "Content-Type" to mime,
                    "Content-Length" to bytes.size.toString(),
                    "Cache-Control" to "no-cache",
                )
            )
            output.write(bytes)
        } catch (e: Exception) {
            sendJson(output, 404, JSONObject().put("error", "not found"))
        }
    }

    private fun mimeOf(path: String): String = when {
        path.endsWith(".html") -> "text/html; charset=utf-8"
        path.endsWith(".js") -> "application/javascript; charset=utf-8"
        path.endsWith(".css") -> "text/css; charset=utf-8"
        path.endsWith(".svg") -> "image/svg+xml"
        path.endsWith(".png") -> "image/png"
        path.endsWith(".ico") -> "image/x-icon"
        else -> "application/octet-stream"
    }

    // ---------------------------------------------------------------- parse --

    private val videoRe = Regex("/(?:video|share/video)/(\\d+)")
    private val noteRe = Regex("/(?:share/slides|note)/(\\d+)")
    private val urlRe = Regex("https?://[^\\s\"'<>，。！？、；：）】]+")

    private fun extractUrls(text: String): List<String> {
        val seen = LinkedHashSet<String>()
        for (match in urlRe.findAll(text)) {
            val url = match.value.trimEnd('.', ',', ')', '，', '。', '!', '！', '?', '？')
            if (url.contains("douyin.com")) seen.add(url)
        }
        return seen.toList()
    }

    private fun handleParse(output: OutputStream, body: ByteArray) {
        val text = try {
            JSONObject(String(body, Charsets.UTF_8)).optString("text", "")
        } catch (e: Exception) {
            ""
        }
        if (text.isBlank()) {
            sendJson(output, 400, JSONObject().put("error", "未找到链接,请粘贴视频链接或分享文案"))
            return
        }
        val urls = extractUrls(text)
        if (urls.isEmpty()) {
            sendJson(output, 400, JSONObject().put("error", "未找到链接,请粘贴视频链接或分享文案"))
            return
        }
        if (urls.size > 20) {
            sendJson(output, 400, JSONObject().put("error", "一次最多解析 20 条链接"))
            return
        }
        val results = JSONArray()
        for (url in urls) {
            results.put(parseOne(url))
        }
        sendJson(output, 200, JSONObject().put("results", results))
    }

    private fun parseOne(url: String): JSONObject {
        var kind = "video"
        var match = videoRe.find(url)
        if (match == null) {
            match = noteRe.find(url)
            kind = "slides"
        }
        if (match == null) {
            val finalUrl = resolveRedirect(url)
            if (finalUrl != null) {
                match = videoRe.find(finalUrl)
                kind = "video"
                if (match == null) {
                    match = noteRe.find(finalUrl)
                    kind = "slides"
                }
            }
        }
        if (match == null) {
            return DouyinParser.unsupported(url)
        }
        val id = match.groupValues[1]
        val detailPath = "/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383" +
            "&channel=channel_pc_web&aweme_id=$id&pc_client_type=1" +
            "&version_code=170400&version_name=17.4.0"
        val payload = fetchDetailBlocking(detailPath) ?: return DouyinParser.riskError(url)
        val detail = payload.optJSONObject("aweme_detail") ?: return DouyinParser.riskError(url)
        return DouyinParser.build(url, kind, detail)
    }

    private fun fetchDetailBlocking(path: String): JSONObject? {
        val latch = CountDownLatch(1)
        var result: JSONObject? = null
        signer.signAndFetch(path) { obj ->
            if (obj.optBoolean("ok", false) && obj.optInt("status", 0) == 200) {
                try {
                    result = JSONObject(obj.optString("body", ""))
                } catch (e: Exception) {
                }
            }
            latch.countDown()
        }
        latch.await(40, TimeUnit.SECONDS)
        return result
    }

    private fun resolveRedirect(url: String): String? {
        var current = url
        repeat(5) {
            try {
                val conn = URL(current).openConnection() as HttpURLConnection
                conn.instanceFollowRedirects = false
                conn.connectTimeout = 8000
                conn.readTimeout = 8000
                conn.setRequestProperty("User-Agent", BROWSER_UA)
                conn.requestMethod = "GET"
                val code = conn.responseCode
                val location = if (code in 300..399) conn.getHeaderField("Location") else null
                conn.disconnect()
                if (!location.isNullOrEmpty()) {
                    current = if (location.startsWith("http")) {
                        location
                    } else {
                        URL(URL(current), location).toString()
                    }
                    return@repeat
                }
                return current
            } catch (e: Exception) {
                return null
            }
        }
        return current
    }

    // ---------------------------------------------------------------- media --

    private fun isAllowedCdn(raw: String): Boolean {
        return try {
            val host = URL(raw).host.lowercase()
            ALLOWED_MEDIA_SUFFIXES.any { host == it || host.endsWith(".$it") }
        } catch (e: Exception) {
            false
        }
    }

    private fun handleProxy(
        output: OutputStream,
        query: Map<String, String>,
        headers: Map<String, String>,
        forceDownload: Boolean,
        name: String?,
    ) {
        val url = query["url"]
        if (url.isNullOrBlank() || !isAllowedCdn(url)) {
            sendJson(output, 400, JSONObject().put("error", "不允许的媒体地址"))
            return
        }
        val conn = try {
            URL(url).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            sendJson(output, 502, JSONObject().put("error", "媒体获取失败"))
            return
        }
        try {
            conn.instanceFollowRedirects = true
            conn.connectTimeout = 15000
            conn.readTimeout = 30000
            conn.setRequestProperty("User-Agent", BROWSER_UA)
            conn.setRequestProperty("Referer", "https://www.douyin.com/")
            headers["range"]?.let { conn.setRequestProperty("Range", it) }
            val code = conn.responseCode
            if (code !in 200..299) {
                sendJson(output, 502, JSONObject().put("error", "媒体获取失败"))
                return
            }
            val responseHeaders = HashMap<String, String>()
            responseHeaders["Content-Type"] = conn.contentType ?: "application/octet-stream"
            conn.getHeaderField("Content-Length")?.let { responseHeaders["Content-Length"] = it }
            conn.getHeaderField("Content-Range")?.let {
                responseHeaders["Content-Range"] = it
                responseHeaders["Accept-Ranges"] = "bytes"
            }
            if (forceDownload) {
                val fileName = (name ?: "video.mp4").ifBlank { "video.mp4" }
                responseHeaders["Content-Disposition"] =
                    "attachment; filename*=UTF-8''" + URLEncoder.encode(fileName, "UTF-8")
            }
            writeHead(output, code, responseHeaders)
            conn.inputStream.use { it.copyTo(output, 65536) }
        } catch (e: Exception) {
            try {
                sendJson(output, 502, JSONObject().put("error", "媒体获取失败"))
            } catch (ignored: Exception) {
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun handleDownload(output: OutputStream, query: Map<String, String>) {
        val url = query["url"] ?: ""
        if (url.isBlank()) {
            sendJson(output, 400, JSONObject().put("error", "缺少地址"))
            return
        }
        if (isAllowedCdn(url)) {
            handleProxy(output, query, emptyMap(), forceDownload = true, name = guessName(url))
            return
        }
        // douyin page URL: parse -> pick direct CDN url -> proxy
        if (url.contains("douyin.com")) {
            val result = parseOne(url)
            val direct = result.optString("direct_url", "")
            if (result.optBoolean("ok", false) && direct.startsWith("/api/download?url=")) {
                val cdn = URLDecoder.decode(direct.removePrefix("/api/download?url="), "UTF-8")
                handleProxy(output, mapOf("url" to cdn), emptyMap(), forceDownload = true, name = guessName(cdn))
                return
            }
            sendJson(output, 502, JSONObject().put("error", result.optString("error", "解析失败")))
            return
        }
        sendJson(output, 400, JSONObject().put("error", "不允许的媒体地址"))
    }

    private fun guessName(url: String): String {
        val base = url.substringBefore('?').substringAfterLast('/')
        return if (base.isEmpty() || !base.contains('.')) "douyin-media.mp4" else base
    }

    private fun handleZip(output: OutputStream, body: ByteArray) {
        val payload = try {
            JSONObject(String(body, Charsets.UTF_8))
        } catch (e: Exception) {
            sendJson(output, 400, JSONObject().put("error", "内容格式不正确"))
            return
        }
        val title = payload.optString("title", "图文")
        val items = payload.optJSONArray("items") ?: JSONArray()
        if (items.length() > 50) {
            sendJson(output, 400, JSONObject().put("error", "一次最多打包 50 项"))
            return
        }
        val temp = File.createTempFile("slides", ".zip", context.cacheDir)
        var added = 0
        try {
            ZipOutputStream(BufferedOutputStream(FileOutputStream(temp))).use { zip ->
                for (i in 0 until items.length()) {
                    val item = items.optJSONObject(i) ?: continue
                    val url = item.optString("url", "")
                    if (url.isBlank() || !isAllowedCdn(url)) continue
                    val rawKind = item.optString("kind", "image")
                    val kind = if (rawKind in setOf("image", "clip", "music")) rawKind else "image"
                    val index = item.optInt("index", i + 1).coerceIn(1, 999)
                    val ext = extensionOf(url, kind)
                    try {
                        val conn = URL(url).openConnection() as HttpURLConnection
                        conn.connectTimeout = 15000
                        conn.readTimeout = 60000
                        conn.setRequestProperty("User-Agent", BROWSER_UA)
                        conn.setRequestProperty("Referer", "https://www.douyin.com/")
                        conn.inputStream.use { stream ->
                            zip.putNextEntry(
                                ZipEntry(String.format("%03d_%s.%s", index, kind, ext))
                            )
                            stream.copyTo(zip, 65536)
                            zip.closeEntry()
                            added++
                        }
                        conn.disconnect()
                    } catch (e: Exception) {
                    }
                }
            }
        } catch (e: Exception) {
            temp.delete()
            sendJson(output, 502, JSONObject().put("error", "打包失败"))
            return
        }
        if (added == 0) {
            temp.delete()
            sendJson(output, 502, JSONObject().put("error", "打包失败:没有可下载的内容"))
            return
        }
        val fileName = (title.ifBlank { "图文" } + "_图文.zip")
        writeHead(
            output, 200,
            mapOf(
                "Content-Type" to "application/zip",
                "Content-Length" to temp.length().toString(),
                "Content-Disposition" to
                    "attachment; filename*=UTF-8''" + URLEncoder.encode(fileName, "UTF-8"),
            )
        )
        temp.inputStream().use { it.copyTo(output, 65536) }
        temp.delete()
    }

    private fun extensionOf(url: String, kind: String): String {
        val path = url.substringBefore('?')
        val ext = path.substringAfterLast('.', "")
        if (ext.length in 2..5 && ext.all { it.isLetterOrDigit() }) return ext.lowercase()
        return when (kind) {
            "clip" -> "mp4"
            "music" -> "mp3"
            else -> "jpg"
        }
    }

    companion object {
        const val BROWSER_UA =
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"

        /** Mirrors app/security.py ALLOWED_MEDIA_SUFFIXES (the server contract). */
        private val ALLOWED_MEDIA_SUFFIXES = listOf(
            "douyin.com",
            "iesdouyin.com",
            "douyinpic.com",
            "douyinvod.com",
            "douyinstatic.com",
            "byteimg.com",
            "ibytedtos.com",
            "bytecdntp.com",
            "zjcdn.com",
            "snssdk.com",
            "amemv.com",
            "365yg.com",
        )
    }
}
