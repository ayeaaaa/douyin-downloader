package com.ayeaaaa.dydl

import org.json.JSONObject

/** Builds the same parse-result shape as the server version (app/douyin.py). */
object DouyinParser {

    private const val RISK_MESSAGE =
        "抖音风控拦截:请在下方「Cookie」里粘贴浏览器导出的 cookies.txt,或点「初始化」让 App 自动申请"

    fun riskError(url: String): JSONObject {
        val obj = base(url)
        obj.put("error", RISK_MESSAGE)
        return obj
    }

    fun unsupported(url: String): JSONObject {
        val obj = base(url)
        obj.put("error", "不支持的链接")
        return obj
    }

    private fun base(url: String): JSONObject {
        val obj = JSONObject()
        obj.put("url", url)
        obj.put("media_type", "video")
        obj.put("ok", false)
        obj.put("title", "")
        obj.put("author", "")
        obj.put("cover", "")
        obj.put("duration", 0)
        obj.put("direct_url", JSONObject.NULL)
        obj.put("direct_ok", false)
        obj.put("error", JSONObject.NULL)
        obj.put("items", org.json.JSONArray())
        return obj
    }

    fun build(url: String, kind: String, detail: JSONObject): JSONObject {
        return if (kind == "slides") buildSlides(url, detail) else buildVideo(url, detail)
    }

    private fun buildVideo(url: String, detail: JSONObject): JSONObject {
        val obj = base(url)
        obj.put("media_type", "video")
        val video = detail.optJSONObject("video") ?: JSONObject()
        val play = video.optJSONObject("play_addr") ?: JSONObject()
        val directUrl = firstUrl(play.optJSONArray("url_list"))
        val author = detail.optJSONObject("author") ?: JSONObject()
        val cover = video.optJSONObject("cover") ?: JSONObject()
        val duration = video.optLong("duration", 0L)
        obj.put("ok", true)
        obj.put("title", detail.optString("desc", ""))
        obj.put("author", author.optString("nickname", ""))
        obj.put("cover", firstUrl(cover.optJSONArray("url_list")) ?: "")
        obj.put("duration", if (duration > 0) duration / 1000 else 0)
        if (directUrl != null) {
            obj.put("direct_url", proxyDownload(directUrl))
            obj.put("direct_ok", true)
        }
        return obj
    }

    private fun buildSlides(url: String, detail: JSONObject): JSONObject {
        val obj = base(url)
        obj.put("media_type", "slides")
        val items = org.json.JSONArray()

        val images = detail.optJSONArray("images")
        if (images != null) {
            for (i in 0 until images.length()) {
                val image = images.optJSONObject(i) ?: continue
                val preview = firstUrl(image.optJSONArray("url_list"))
                val video = image.optJSONObject("video")
                val playAddr = video?.optJSONObject("play_addr")
                val clipUrls = playAddr?.optJSONArray("url_list")
                val clip = firstUrl(clipUrls)
                if (clip != null) {
                    val item = JSONObject()
                    item.put("kind", "clip")
                    item.put("index", i + 1)
                    item.put("preview_url", preview ?: clip)
                    item.put("download_url", clip)
                    items.put(item)
                    continue
                }
                val downloadList = image.optJSONArray("download_url_list")
                val downloadUrl = firstUrl(downloadList) ?: preview
                if (downloadUrl == null) continue
                val item = JSONObject()
                item.put("kind", "image")
                item.put("index", i + 1)
                item.put("preview_url", preview ?: downloadUrl)
                item.put("download_url", downloadUrl)
                items.put(item)
            }
        }

        val music = detail.optJSONObject("music")
        val musicUrl = music?.optJSONObject("play_url")?.optString("uri", "")
        if (!musicUrl.isNullOrEmpty()) {
            val item = JSONObject()
            item.put("kind", "music")
            item.put("index", 1)
            item.put("preview_url", musicUrl)
            item.put("download_url", musicUrl)
            items.put(item)
        }

        if (items.length() == 0) {
            val objErr = base(url)
            objErr.put("media_type", "slides")
            objErr.put("error", "未找到可下载的图片或视频")
            return objErr
        }

        obj.put("ok", true)
        obj.put("title", detail.optString("desc", ""))
        val author = detail.optJSONObject("author") ?: JSONObject()
        obj.put("author", author.optString("nickname", ""))
        obj.put("cover", items.optJSONObject(0)?.optString("preview_url", "") ?: "")
        obj.put("items", items)
        return obj
    }

    private fun proxyDownload(cdnUrl: String): String {
        return "/api/download?url=" + java.net.URLEncoder.encode(cdnUrl, "UTF-8")
    }

    private fun firstUrl(array: org.json.JSONArray?): String? {
        if (array == null) return null
        for (i in 0 until array.length()) {
            val value = array.optString(i, "")
            if (value.startsWith("http")) return value
        }
        return null
    }
}
