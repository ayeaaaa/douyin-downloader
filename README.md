# 视频下载站

粘贴抖音链接（或整段分享文案）即可下载视频。直链可用时浏览器直连 CDN 保存；
直链不可用时回退服务器中转下载。支持 yt-dlp 能解析的其他平台链接。

## 快速开始

```bash
docker compose up -d --build
```

浏览器打开 `http://<服务器IP>:8000`，粘贴链接，点「解析」，再点「下载」。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8000` | 宿主机端口 |
| `ACCESS_PASSWORD` | 空 | 非空时启用 Basic Auth（用户名任意，密码为该值）；`/healthz` 免认证 |
| `MAX_FILESIZE_MB` | `500` | 单个中转下载大小上限 |
| `COOKIES_PATH` | `/data/cookies.txt` | 容器内 cookie 文件路径 |

在项目目录建 `.env` 可覆盖，例如 `ACCESS_PASSWORD=yourpass`。

## Cookie（推荐导出浏览器 cookies）

抖音详情接口有风控校验（`a_bogus` / `uifid` / `x-secsdk-web-signature` 等签名）。
本项目内置 Node 签名服务（`signer/`），配合 Firefox TLS 指纹请求可纯请求通过风控，
但需要 cookies 里包含浏览器生成的 `UIFID_TEMP`（设备指纹）。用浏览器插件（如
Get cookies.txt LOCALLY）导出 douyin.com 的 Netscape 格式 cookie，保存为
`data/cookies.txt`，重启容器即可：

```bash
docker compose restart
```

抖音风控失败会提示「抖音风控临时拦截(非登录问题)…」；其他平台需要登录的视频会提示「需要登录,请配置 cookies.txt」。

抖音链接无需手动配置：容器会自动申请匿名 `ttwid` cookie（无需登录/浏览器），并自动附加 Referer。
如果你自行放入 `data/cookies.txt`（浏览器导出，可含登录态），则优先使用你的文件，可用于需要登录或更高清的视频。

也可以直接在网页底部的「Cookie 设置」面板粘贴或选择 cookies.txt 文件保存，无需登录服务器；
保存后即时生效并自动清空解析缓存，页面不会回显 cookie 内容。

## 图文/幻灯片

抖音图文（slides/note）链接会解析出图片、live 图视频片段与背景音乐：网页端可预览、
单项下载，或勾选后打包为 zip。图文提取依赖抖音接口，风控窗口内可能失败，稍后重试即可。

## 更新

站点结构变化导致解析失败时，重新构建以更新 yt-dlp：

```bash
docker compose build --pull
docker compose up -d
```

## 安全说明

- 默认无认证，适合本地/内网使用；公网部署务必设置 `ACCESS_PASSWORD`，
  并建议置于 HTTPS 反向代理之后。
- 服务器不保存视频：中转文件在响应结束后立即删除，启动时清理残留。
- 不记录 cookie 内容；`data/` 目录内容已被 git 忽略。

## 已知局限

- yt-dlp 内部对媒体地址的请求与重定向不做 SSRF 校验（仅校验初始页面 URL），DNS 解析存在重绑定窗口；
  服务器中转的直链下载路径虽逐跳校验 URL，但校验与实际连接之间同样存在解析重绑定窗口。
  本地/内网自用时风险有限，公网部署请设置访问密码并配合网络隔离。
- 部分视频的直链仅在带 Referer 时可用，浏览器直连可能失败，此时请改用「服务器中转下载」。
- 抖音接口偶发风控（403，要求浏览器指纹 uifid），表现为「解析失败/风控提示」，通常等待 1-2 分钟或
  导出浏览器 cookies 后重试即可；解析成功后 15 分钟内重复解析会走本地缓存，下载优先使用缓存直链。
- 极少数无法识别的图文/幻灯片链接会提示「这是图文/幻灯片帖子,暂不支持下载」；正常图文链接会在卡片中展示图片、live 片段与背景音乐。

## 常见问题

- 解析失败/需要登录：配置 `data/cookies.txt` 后重试。
- 直链点击无反应：改用「服务器中转下载」。
- 返回 429：已有中转任务进行中，稍后重试。
