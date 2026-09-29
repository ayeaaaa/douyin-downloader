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

## Cookie（可选）

部分视频需要登录才能解析或获取高清。用浏览器插件（如 Get cookies.txt LOCALLY）
导出 douyin.com 的 Netscape 格式 cookie，保存为 `data/cookies.txt`，重启容器即可：

```bash
docker compose restart
```

未配置 cookie 时，需要登录的视频会提示「需要登录,请配置 cookies.txt」。

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
  本地/内网自用时风险有限，公网部署请设置访问密码并配合网络隔离。
- 部分视频的直链仅在带 Referer 时可用，浏览器直连可能失败，此时请改用「服务器中转下载」。

## 常见问题

- 解析失败/需要登录：配置 `data/cookies.txt` 后重试。
- 直链点击无反应：改用「服务器中转下载」。
- 返回 429：已有中转任务进行中，稍后重试。
