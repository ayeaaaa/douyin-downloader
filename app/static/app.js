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

function renderCard(item) {
  const card = el("article", "card");
  if (!item.ok) {
    card.classList.add("failed");
    card.append(el("div", "card-title", item.url));
    card.append(el("div", "error", item.error || "解析失败"));
    return card;
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
loadCookieStatus();
