package com.ayeaaaa.dydl

import android.content.Context
import android.webkit.CookieManager
import org.json.JSONObject

/**
 * Stores the user-supplied cookies.txt (Netscape format) and keeps the
 * WebView cookie jar in sync so both the signer page and the media proxy
 * see the same douyin.com cookies.
 */
class CookieStore(context: Context) {

    private val prefs = context.getSharedPreferences("dydl", Context.MODE_PRIVATE)

    fun raw(): String = prefs.getString(KEY, "") ?: ""

    fun status(): JSONObject {
        val entries = parseEntries(raw()).size
        val obj = JSONObject()
        obj.put("configured", entries > 0)
        obj.put("entries", entries)
        obj.put(
            "updated_at",
            if (entries > 0) prefs.getLong(KEY_TIME, 0L) / 1000 else JSONObject.NULL
        )
        return obj
    }

    fun save(content: String): JSONObject {
        prefs.edit()
            .putString(KEY, content)
            .putLong(KEY_TIME, System.currentTimeMillis())
            .apply()
        syncToWebView()
        return status()
    }

    fun clear() {
        prefs.edit().remove(KEY).remove(KEY_TIME).apply()
        try {
            val manager = CookieManager.getInstance()
            manager.removeAllCookies(null)
            manager.flush()
        } catch (e: Exception) {
        }
    }

    fun syncToWebView() {
        val entries = parseEntries(raw())
        if (entries.isEmpty()) return
        try {
            val manager = CookieManager.getInstance()
            for ((name, value) in entries) {
                manager.setCookie(DOMAIN, "$name=$value; path=/")
            }
            manager.flush()
        } catch (e: Exception) {
        }
    }

    private fun parseEntries(content: String): List<Pair<String, String>> {
        val out = ArrayList<Pair<String, String>>()
        for (rawLine in content.split("\n")) {
            var line = rawLine.trim()
            if (line.isEmpty()) continue
            if (line.startsWith("#HttpOnly_")) {
                line = line.removePrefix("#HttpOnly_")
            } else if (line.startsWith("#")) {
                continue
            }
            val parts = line.split("\t")
            if (parts.size < 7) continue
            val name = parts[5].trim()
            val value = parts[6].trim()
            if (name.isNotEmpty()) out.add(name to value)
        }
        return out
    }

    companion object {
        private const val KEY = "cookies"
        private const val KEY_TIME = "cookies_updated_at"
        private const val DOMAIN = "https://www.douyin.com"
    }
}
