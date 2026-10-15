# Douyin 纯请求签名服务

Node + jsdom 实现的抖音 Web 接口签名（`a_bogus` + `uifid` + `x-secsdk-web-signature`），
配合 Firefox TLS 指纹请求（curl_cffi `impersonate="firefox"`）纯请求通过抖音风控。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `signer.js` | 入口（加载编译后的字节码） |
| `dist/signer.jsc` | **加密产物**（V8 字节码，随仓库发布） |
| `build.js` | 编译脚本：`src/` → `dist/`（维护者用） |
| `fetch-sdk.js` | 下载字节跳动 SDK 文件到 `sdk/`（不随仓库分发） |
| `src/` | 可维护源码（**不随仓库发布**） |
| `sdk/` | 运行时依赖的 SDK 文件（构建时自动下载） |

## 首次使用 / 构建

```bash
node fetch-sdk.js   # 下载 SDK 文件到 ./sdk
npm install         # jsdom + bytenode
```

## 重新编译（维护者）

源码在 `src/signer.src.js`，编译必须与部署镜像的 Node 版本一致（Node 20.19.x）：

```bash
docker run --rm -v "$PWD":/signer -w /signer python:3.12-slim \
  sh -c "apt-get update -qq && apt-get install -y -qq nodejs npm >/dev/null && npm install --no-audit --no-fund && node build.js"
```

## 协议

stdin/stdout 逐行 JSON（NDJSON）：

```json
{"id":1,"url":"/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&aweme_id=...","cookies":{"ttwid":"...","UIFID_TEMP":"..."}}
→ {"id":1,"ok":true,"signedUrl":"https://www.douyin.com/aweme/...&a_bogus=...&uifid=...&timestamp=...&x-secsdk-web-signature=...","cookies":{...}}
```

注意：cookies 中必须包含 `UIFID_TEMP`（或 `UIFID`），否则 secsdk 签名不会生效。
