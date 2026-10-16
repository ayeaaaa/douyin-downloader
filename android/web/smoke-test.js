#!/usr/bin/env node
/**
 * Behavioral smoke test for the standalone signer page.
 *
 * Loads signer.html + the SDK assets in jsdom (mimicking the Android
 * WebView environment) and asserts the signing stack actually initializes
 * and produces a signed URL.
 *
 * Catches the class of bug that compile + asset-presence checks cannot:
 * SDK load-time failures (script-tag lookups, missing globals, wrong asset
 * paths after CI assembly, ...).
 *
 * Modes:
 *   node smoke-test.js
 *       Source mode: android/web/signer.html + signer/sdk/*.
 *   node smoke-test.js android/app/src/main/assets
 *       Assembled mode: loads the CI-assembled assets exactly as the APK
 *       ships them (verifies the copy paths).
 *
 * Requires jsdom:  NODE_PATH=signer/node_modules node android/web/smoke-test.js
 */
const fs = require("fs");
const path = require("path");
const { JSDOM, ResourceLoader, VirtualConsole } = require("jsdom");

const WEB_DIR = __dirname;
const SDK_DIR = path.join(WEB_DIR, "..", "..", "signer", "sdk");
const ASSEMBLED_DIR = process.argv[2] ? path.resolve(process.argv[2]) : null;

// Source-mode basename mapping.
const ASSET_MAP = {
  "webmssdk.js": "webmssdk.js",
  "secsdk-runtime.js": "secsdk-runtime.js",
  "runtime_bundler_34_v2.js": "secsdk-runtime.js",
  "sdk-glue.js": "sdk-glue.js",
  "bdms-signer.js": "bdms-signer.js",
  "slardar.js": "slardar.js",
  "verifycenter.js": "verifycenter.js",
  "captcha-sdk.js": "captcha-sdk.js",
};

class AssetLoader extends ResourceLoader {
  fetch(url) {
    const noQuery = url.split("?")[0];
    if (ASSEMBLED_DIR) {
      // Assembled mode: serve the real asset path under signer/.
      const marker = "/__signer/";
      const idx = noQuery.indexOf(marker);
      if (idx >= 0) {
        const rel = noQuery.slice(idx + marker.length);
        const file = path.join(ASSEMBLED_DIR, "signer", rel);
        if (fs.existsSync(file)) {
          return Promise.resolve(fs.readFileSync(file));
        }
      }
      return null;
    }
    const base = noQuery.split("/").pop();
    if (base === "signer-glue.js") {
      return Promise.resolve(fs.readFileSync(path.join(WEB_DIR, "signer-glue.js")));
    }
    const mapped = ASSET_MAP[base];
    if (mapped) {
      const file = path.join(SDK_DIR, mapped);
      if (fs.existsSync(file)) {
        return Promise.resolve(fs.readFileSync(file));
      }
    }
    return null;
  }
}

async function main() {
  const htmlPath = ASSEMBLED_DIR
    ? path.join(ASSEMBLED_DIR, "signer", "index.html")
    : path.join(WEB_DIR, "signer.html");
  if (!fs.existsSync(htmlPath)) {
    console.log(`FAIL signer html not found: ${htmlPath}`);
    console.log("SMOKE TEST: FAIL");
    process.exit(1);
  }
  const html = fs.readFileSync(htmlPath, "utf8");

  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    const message = String((err && err.message) || err);
    // "Not implemented" notices are jsdom limitations (canvas etc.); the real
    // WebView has those APIs, so they are not script errors.
    if (message.includes("Not implemented")) return;
    errors.push(message);
  });

  const dom = new JSDOM(html, {
    url: "https://www.douyin.com/__signer/index.html",
    runScripts: "dangerously",
    resources: new AssetLoader(),
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      // The real WebView has these; mirror them so the test cannot fail
      // for reasons that only exist in jsdom.
      for (const name of ["Request", "Headers", "Response", "fetch", "TextEncoder", "TextDecoder", "AbortController", "Blob", "FormData"]) {
        if (typeof window[name] === "undefined" && typeof globalThis[name] !== "undefined") {
          window[name] = globalThis[name];
        }
      }
      window.atob = globalThis.atob;
      window.btoa = globalThis.btoa;
    },
  });

  // Mimic the Android bridge.
  const results = [];
  dom.window.AndroidSigner = {
    onReady: () => {},
    onResult: (json) => results.push(json),
  };
  // A UIFID cookie makes webSignUrl actually sign (mirrors the real device state).
  dom.window.document.cookie = "UIFID_TEMP=smoke-test-uifid; path=/";
  dom.window.document.cookie = "ttwid=smoke-test-ttwid; path=/";

  // Give the SDK scripts time to execute.
  await new Promise((r) => setTimeout(r, 1500));

  const checks = [];
  const fail = (msg) => {
    checks.push(`FAIL ${msg}`);
  };
  const pass = (msg) => {
    checks.push(`ok   ${msg}`);
  };

  if (errors.length) {
    fail(`page scripts threw: ${errors.join(" | ").slice(0, 300)}`);
  } else {
    pass("no script errors");
  }

  const useFn = dom.window.use;
  if (typeof useFn === "function") {
    pass("window.use is a function");
  } else {
    fail("window.use is not a function (runtime did not initialize)");
  }

  let webSignUrlOk = false;
  if (typeof useFn === "function") {
    try {
      webSignUrlOk = typeof useFn("webSignUrl") === "function";
    } catch (e) {
      webSignUrlOk = false;
    }
  }
  if (webSignUrlOk) {
    pass("webSignUrl is registered");
  } else {
    fail("webSignUrl is not registered");
  }

  if (dom.window.__signer && typeof dom.window.__signer.sign === "function") {
    pass("window.__signer.sign exists");
    const signed = await dom.window.__signer.sign(
      "/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&aweme_id=7690569417713790890&pc_client_type=1&version_code=170400&version_name=17.4.0"
    );
    if (signed && signed.ok) {
      pass("sign() returned ok");
      if (String(signed.url).includes("a_bogus=")) {
        pass("signed url contains a_bogus");
      } else {
        fail("signed url missing a_bogus");
      }
      if (String(signed.url).includes("uifid=")) {
        pass("signed url contains uifid");
      } else {
        fail("signed url missing uifid");
      }
    } else {
      fail(`sign() failed: ${JSON.stringify(signed).slice(0, 200)}`);
    }
  } else {
    fail("window.__signer.sign missing (glue did not run)");
  }

  dom.window.close();
  console.log(checks.join("\n"));
  const failed = checks.some((c) => c.startsWith("FAIL"));
  console.log(`SMOKE TEST${ASSEMBLED_DIR ? " (assembled)" : ""}: ${failed ? "FAIL" : "PASS"}`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error("smoke test crashed:", e);
  process.exit(1);
});
