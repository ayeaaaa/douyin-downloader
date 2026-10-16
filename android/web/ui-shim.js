/*
 * Runtime-injected shim for the frozen web UI (loaded into the visible
 * WebView on every page load; app/static/* stays untouched).
 *
 * WebView's DownloadManager cannot fetch blob: URLs, which the slides-zip
 * flow produces via URL.createObjectURL. Intercept the click, stream the
 * blob back to the local server, and let the server save it to Downloads.
 */
(function () {
  "use strict";
  if (window.__blobShimInstalled) {
    return;
  }
  window.__blobShimInstalled = true;

  function setStatus(text) {
    var node = document.getElementById("status");
    if (node) {
      node.textContent = text;
    }
  }

  document.addEventListener(
    "click",
    function (event) {
      var node = event.target;
      while (node && node.tagName !== "A") {
        node = node.parentElement;
      }
      if (!node || !node.href || String(node.href).indexOf("blob:") !== 0) {
        return;
      }
      event.preventDefault();
      var name = node.getAttribute("download") || "download.bin";
      fetch(node.href)
        .then(function (resp) {
          return resp.blob();
        })
        .then(function (blob) {
          return fetch("/api/save-blob?name=" + encodeURIComponent(name), {
            method: "POST",
            body: blob,
          });
        })
        .then(function (resp) {
          return resp.json().catch(function () {
            return {};
          });
        })
        .then(function (data) {
          setStatus(data && data.ok ? "已保存到系统下载目录: " + name : "保存失败");
        })
        .catch(function () {
          setStatus("保存失败");
        });
    },
    true
  );
})();
