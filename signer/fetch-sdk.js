#!/usr/bin/env node
/**
 * Downloads the ByteDance web SDK files required by the signer into ./sdk
 * and applies the two small patches the signer needs.
 *
 * The SDK files are NOT distributed with this repository; run this script
 * before first use (the Docker image runs it automatically at build time).
 *
 *   node fetch-sdk.js
 */
const fs = require("fs");
const path = require("path");

const SDK_DIR = path.join(__dirname, "sdk");
const UA =
  "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0";

// The bdms signer exposes the final re-open URL (with a_bogus) to `window.__capUrl`.
const BDMS_FROM = "else{var m=n.apply(d,e);v[++p]=m}";
const BDMS_TO =
  'else{var m=n.apply(d,e);try{if(window.__capUrl&&n&&"apply"===n.name&&e&&e[1]&&Array.isArray(e[1])){var _u=String(e[1][1]||"");if(_u.indexOf("a_bogus=")>=0&&_u.indexOf("aweme")>=0)window.__capUrl(_u)}}catch(e){}v[++p]=m}';

// The captcha SDK exposes its XHR interceptor as `window.__ku`.
const CAPTCHA_FROM = "ku=function(e,t){";
const CAPTCHA_TO = "ku=window.__ku=function(e,t){";

const FILES = [
  {
    out: "webmssdk.js",
    url: "https://lf-c-flwb.bytetos.com/obj/rc-client-security/c-webmssdk/1.0.0.20/webmssdk.es5.js",
  },
  {
    out: "secsdk-runtime.js",
    url: "https://lf-security.bytegoofy.com/obj/security-secsdk/runtime_bundler_34_v2.js",
  },
  {
    out: "sdk-glue.js",
    url: "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/glue/1.0.0.64-fix.01/sdk-glue.js",
  },
  {
    out: "slardar.js",
    url: "https://lf3-short.ibytedapm.com/slardar/fe/sdk-web/browser.cn.js?bid=douyin_web&globalName=bdSlardar",
  },
  {
    out: "bdms-signer.js",
    url: "https://p-pc-weboff.byteimg.com/tos-cn-i-9r5gewecjs/bdms_1.0.1.19_fix.js",
    patch: { from: BDMS_FROM, to: BDMS_TO },
  },
  {
    out: "captcha-sdk.js",
    url: "https://lf-rc1.yhgfb-cn-static.com/obj/rc-verifycenter/sec_sdk_build/4.0.28/captcha/index.js",
    patch: { from: CAPTCHA_FROM, to: CAPTCHA_TO },
  },
  {
    out: "verifycenter.js",
    url: "https://lf-rc1.yhgfb-cn-static.com/obj/rc-verifycenter/verifycenter/1.0.0.427/index.js",
  },
];

async function download(url) {
  const response = await fetch(url, { headers: { "User-Agent": UA } });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  return await response.text();
}

(async () => {
  fs.mkdirSync(SDK_DIR, { recursive: true });
  for (const file of FILES) {
    const target = path.join(SDK_DIR, file.out);
    process.stdout.write(`[fetch-sdk] ${file.out} ... `);
    try {
      let source = await download(file.url);
      if (file.patch) {
        if (!source.includes(file.patch.from)) {
          throw new Error("patch anchor not found (SDK changed?)");
        }
        source = source.replace(file.patch.from, file.patch.to);
      }
      fs.writeFileSync(target, source);
      process.stdout.write(`ok (${source.length} bytes)\n`);
    } catch (error) {
      process.stdout.write(`FAILED: ${error.message}\n`);
      process.exitCode = 1;
    }
  }
  process.stdout.write("[fetch-sdk] done\n");
})();
