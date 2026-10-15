const $ = (id) => document.getElementById(id);

function setStatus(text) {
  $("status").textContent = text;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function platformOf(url) {
  try {
    const host = new URL(url).hostname;
    if (host.includes("douyin")) return "抖音";
    return host;
  } catch (err) {
    return "";
  }
}

function serverDownload(url) {
  setStatus("服务器开始下载，完成后浏览器会自动保存…");
  window.location.href = "/api/download?url=" + encodeURIComponent(url);
}

function mediaUrl(url) {
  return "/api/media?url=" + encodeURIComponent(url);
}

function mediaDownloadUrl(url, name) {
  return (
    "/api/media?download=1&name=" +
    encodeURIComponent(name) +
    "&url=" +
    encodeURIComponent(url)
  );
}

function itemName(media) {
  const prefix =
    { image: "image", clip: "clip", music: "music" }[media.kind] || "file";
  const ext =
    media.kind === "clip" ? "mp4" : media.kind === "music" ? "mp3" : "webp";
  return `${prefix}-${String(media.index).padStart(2, "0")}.${ext}`;
}

function openPreview(media) {
  const overlay = $("preview-overlay");
  const content = $("preview-content");
  content.replaceChildren();
  if (media.kind === "music") {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = mediaUrl(media.preview_url);
    content.append(audio);
  } else if (media.kind === "clip") {
    const video = document.createElement("video");
    video.controls = true;
    video.poster = mediaUrl(media.preview_url);
    video.src = mediaUrl(media.download_url);
    content.append(video);
  } else {
    const img = el("img", "preview-img");
    img.src = mediaUrl(media.preview_url);
    img.alt = "图片预览";
    content.append(img);
  }
  const link = $("preview-download");
  link.href = mediaDownloadUrl(media.download_url, itemName(media));
  link.setAttribute("download", itemName(media));
  overlay.classList.remove("hidden");
}

function renderSlidesCard(item) {
  const card = el("article", "card slides-card");
  const body = el("div", "card-body");
  body.append(el("div", "card-title", item.title || "图文帖子"));
  const meta = [item.author, platformOf(item.url)].filter(Boolean).join(" · ");
  body.append(el("div", "meta", meta));

  const toolbar = el("div", "card-actions");
  const selectAllLabel = el("label", "check");
  const selectAll = document.createElement("input");
  selectAll.type = "checkbox";
  selectAllLabel.append(selectAll, document.createTextNode("全选"));
  const zipButton = el("button", "primary", "打包下载选中");
  const status = el("span", "status", "");
  toolbar.append(selectAllLabel, zipButton, status);

  const grid = el("div", "media-grid");
  const boxes = [];
  item.items.forEach((media) => {
    const cell = el("div", "media-cell");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.url = media.download_url;
    checkbox.dataset.kind = media.kind;
    checkbox.dataset.index = String(media.index);
    boxes.push(checkbox);

    const thumb = el("button", "thumb");
    thumb.type = "button";
    if (media.kind === "music") {
      thumb.classList.add("music-thumb");
      thumb.textContent = "🎵";
    } else {
      const img = el("img", "thumb-img");
      img.loading = "lazy";
      img.src = mediaUrl(media.preview_url);
      img.alt = media.kind === "clip" ? "视频片段" : "图片";
      thumb.append(img);
      if (media.kind === "clip") {
        thumb.append(el("span", "play-badge", "▶"));
      }
    }
    thumb.onclick = () => openPreview(media);

    const download = document.createElement("a");
    download.className = "button-like";
    download.href = mediaDownloadUrl(media.download_url, itemName(media));
    download.setAttribute("download", itemName(media));
    download.textContent = "下载";

    cell.append(checkbox, thumb, download);
    grid.append(cell);
  });

  selectAll.onchange = () => {
    boxes.forEach((box) => {
      box.checked = selectAll.checked;
    });
  };

  zipButton.onclick = async () => {
    const selected = boxes.filter((box) => box.checked);
    if (!selected.length) {
      status.textContent = "请先勾选要下载的内容";
      return;
    }
    status.textContent = "打包中…";
    try {
      const resp = await fetch("/api/slides/zip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: item.title || "图文",
          items: selected.map((box) => ({
            url: box.dataset.url,
            kind: box.dataset.kind,
            index: Number(box.dataset.index),
          })),
        }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        status.textContent = data.error || "打包失败";
        return;
      }
      const blob = await resp.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = (item.title || "图文") + "_图文.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      status.textContent = "打包完成";
    } catch (err) {
      status.textContent = "网络错误，请重试";
    }
  };

  body.append(toolbar, grid);
  card.append(body);
  return card;
}

function renderCard(item) {
  const card = el("article", "card");
  if (!item.ok) {
    card.classList.add("failed");
    card.append(el("div", "card-title", item.url));
    card.append(el("div", "error", item.error || "解析失败"));
    return card;
  }

  if (item.media_type === "slides") {
    return renderSlidesCard(item);
  }

  const cover = el("img", "cover");
  cover.alt = "封面";
  cover.loading = "lazy";
  if (item.cover) cover.src = "/api/cover?url=" + encodeURIComponent(item.cover);

  const body = el("div", "card-body");
  body.append(el("div", "card-title", item.title || "未命名视频"));
  const meta = [item.author, platformOf(item.url), formatDuration(item.duration)]
    .filter(Boolean)
    .join(" · ");
  body.append(el("div", "meta", meta));

  const actions = el("div", "card-actions");
  const main = el("button", "primary", "下载");
  main.onclick = () => {
    if (item.direct_ok && item.direct_url) {
      const a = document.createElement("a");
      a.href = item.direct_url;
      a.download = "";
      a.referrerPolicy = "no-referrer";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setStatus("已开始直链下载；若浏览器没有反应，请点『服务器中转下载』");
    } else {
      serverDownload(item.url);
    }
  };
  const proxy = el("button", "", "服务器中转下载");
  proxy.onclick = () => serverDownload(item.url);
  actions.append(main, proxy);

  if (item.direct_url) {
    const copy = el("button", "", "复制直链");
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(item.direct_url);
        setStatus("直链已复制");
      } catch (err) {
        setStatus("复制失败，请手动复制");
      }
    };
    actions.append(copy);
  }

  body.append(actions);
  card.append(cover, body);
  return card;
}

async function parse() {
  const text = $("input").value.trim();
  if (!text) {
    setStatus("请先粘贴链接");
    return;
  }
  $("parse-btn").disabled = true;
  setStatus("解析中…");
  $("results").replaceChildren();
  try {
    const resp = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || "解析失败");
      return;
    }
    data.results.forEach((item) => $("results").append(renderCard(item)));
    setStatus(`共解析 ${data.results.length} 条`);
  } catch (err) {
    setStatus("网络错误，请重试");
  } finally {
    $("parse-btn").disabled = false;
  }
}

$("parse-btn").addEventListener("click", parse);
$("input").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") parse();
});

async function loadCookieStatus() {
  try {
    const resp = await fetch("/api/cookies/status");
    if (!resp.ok) return;
    renderCookieStatus(await resp.json());
  } catch (err) {
    // ignore
  }
}

function renderCookieStatus(data) {
  const node = $("cookie-status");
  if (!data.configured) {
    node.textContent = "当前未配置 cookie（抖音自动申请匿名 ttwid）";
    return;
  }
  const when = data.updated_at
    ? new Date(data.updated_at * 1000).toLocaleString()
    : "未知";
  node.textContent = `已配置：${data.entries} 条，更新时间 ${when}`;
}

async function saveCookies() {
  const content = $("cookie-input").value;
  if (!content.trim()) {
    $("cookie-msg").textContent = "请先粘贴 cookie 内容";
    return;
  }
  try {
    const resp = await fetch("/api/cookies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      $("cookie-msg").textContent = data.error || "保存失败";
      return;
    }
    $("cookie-msg").textContent = "已保存";
    $("cookie-input").value = "";
    renderCookieStatus(data);
  } catch (err) {
    $("cookie-msg").textContent = "网络错误，请重试";
  }
}

async function clearCookies() {
  try {
    const resp = await fetch("/api/cookies", { method: "DELETE" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      $("cookie-msg").textContent = data.error || "清除失败";
      return;
    }
    $("cookie-msg").textContent = "已清除，将自动申请匿名 ttwid";
    renderCookieStatus(data);
  } catch (err) {
    $("cookie-msg").textContent = "网络错误，请重试";
  }
}

$("cookie-pick").addEventListener("click", () => $("cookie-file").click());
$("cookie-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  $("cookie-input").value = await file.text();
  $("cookie-msg").textContent = "已读入文件，点击保存生效";
  event.target.value = "";
});
$("cookie-save").addEventListener("click", saveCookies);
$("cookie-clear").addEventListener("click", clearCookies);

function closePreview() {
  $("preview-overlay").classList.add("hidden");
  $("preview-content").replaceChildren();
}

$("preview-close").addEventListener("click", closePreview);
$("preview-overlay").addEventListener("click", (event) => {
  if (event.target === $("preview-overlay")) {
    closePreview();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closePreview();
  }
});
loadCookieStatus();

// 支持 ?text= / ?url= 预填并自动解析（移动端分享入口 / APK 分享直达）
(() => {
  const params = new URLSearchParams(window.location.search);
  const shared = (params.get("text") || params.get("url") || "").trim();
  if (!shared) {
    return;
  }
  const input = $("input");
  if (!input) {
    return;
  }
  input.value = shared;
  history.replaceState(null, "", window.location.pathname);
  parse();
})();
