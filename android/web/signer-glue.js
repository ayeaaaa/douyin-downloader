/*
 * Douyin signer glue — runs inside the hidden WebView.
 *
 * The page is served (via WebViewClient.shouldInterceptRequest) under
 * https://www.douyin.com/__signer/ so it shares the douyin.com origin:
 *  - document.cookie sees the real douyin cookies (ttwid / UIFID_TEMP / ...)
 *  - fetch() below is same-origin and uses the WebView's Chrome network stack
 *
 * Kotlin calls:  window.__signer.signAndFetch(path, requestId)
 * The result is delivered via the AndroidSigner.onResult(requestId, json) bridge.
 */
(function () {
  "use strict";

  try {
    window.bdSlardar.init({ bid: "douyin_web" });
  } catch (e) {}

  try {
    window.bdms.init({
      aid: 6383,
      pageId: 1,
      paths: {
        include: [
          new RegExp("^/webcast/"),
          new RegExp("^/aweme/v1/"),
          new RegExp("^/aweme/v2/"),
          new RegExp("/douplus/"),
        ],
        exclude: [new RegExp("/aweme/v1/play/"), new RegExp("douyinvod\\.com")],
      },
    });
  } catch (e) {}

  function bridge(payload) {
    try {
      if (window.AndroidSigner && window.AndroidSigner.onResult) {
        window.AndroidSigner.onResult(JSON.stringify(payload));
      }
    } catch (e) {}
  }

  function sign(path) {
    return new Promise(function (resolve) {
      var webId;
      Promise.resolve()
        .then(function () {
          return window.verifySDK.getCaptchaWebId();
        })
        .then(function (id) {
          webId = String(id || "");
          var sep = path.indexOf("?") >= 0 ? "&" : "?";
          var url = path + sep + "verifyFp=" + encodeURIComponent(webId) + "&fp=" + encodeURIComponent(webId);
          window.__lastSignedUrl = null;
          var xhr = new XMLHttpRequest();
          xhr.open("GET", url, true);
          xhr.send();
          var deadline = Date.now() + 8000;
          (function poll() {
            if (window.__lastSignedUrl) {
              var signed = String(window.__lastSignedUrl);
              var rel = signed.indexOf("://") >= 0 ? "/" + signed.split("/").slice(3).join("/") : signed;
              var ws = window.use("webSignUrl")(rel);
              var origin = (signed.match(/^(https?:\/\/[^/]+)/) || [])[1] || "https://www.douyin.com";
              resolve({ ok: true, url: origin + (ws && ws.url ? ws.url : rel) });
              return;
            }
            if (Date.now() > deadline) {
              resolve({ ok: false, error: "sign timeout" });
              return;
            }
            setTimeout(poll, 50);
          })();
        })
        .catch(function (err) {
          resolve({ ok: false, error: String(err && err.message ? err.message : err) });
        });
    });
  }

  function signAndFetch(path, requestId) {
    sign(path).then(function (signed) {
      if (!signed.ok) {
        bridge({ id: requestId, ok: false, error: signed.error });
        return;
      }
      var doFetch = window.__origFetch || window.fetch;
      doFetch(signed.url, { credentials: "same-origin" })
        .then(function (resp) {
          return resp.text().then(function (text) {
            bridge({ id: requestId, ok: true, status: resp.status, body: text });
          });
        })
        .catch(function (err) {
          bridge({ id: requestId, ok: false, error: String(err && err.message ? err.message : err) });
        });
    });
  }

  window.__signer = {
    sign: sign,
    signAndFetch: signAndFetch,
    hasUifid: function () {
      return /(^|;\s*)UIFID(_TEMP)?=/.test(document.cookie);
    },
  };

  try {
    if (window.AndroidSigner && window.AndroidSigner.onReady) {
      window.AndroidSigner.onReady();
    }
  } catch (e) {}
})();
