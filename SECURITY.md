# 安全说明

SpriteKiln 默认是**单用户、本机运行**的工具，不是多租户 SaaS。请先按这个前提部署。

## 默认安全边界

- 服务默认只监听 `127.0.0.1:7788`。
- 没有登录、权限、租户隔离，也没有请求限流。
- `GET/PUT /api/settings` 可以读写模型配置；返回给浏览器的 Key 会被掩码，但**本机任何进程都能调用 API**。
- 云端 Key 以明文保存在 `data/settings.json`（gitignored）。不要把这个文件放进镜像、备份仓库或共享目录。
- 生成的文件通过 `/files` 静态目录直接暴露；路径由服务端生成，但仍不建议把整个 `data/` 挂到公网 Web 根目录。
- 内置 Agent 会把你的提示词发送给所配置的 LLM（cc-switch 代理、本地 Ollama 或云端）。接云端模型前请确认数据合规要求。
- cc-switch 集成只**只读** `~/.cc-switch/cc-switch.db` 中的 provider 名称、模型 ID 与代理端口，不读取或复制 API Key；Key 由 cc-switch 本地代理注入。`/api/ccswitch` 也不返回密钥。但该代理本身是可信边界：不要把它监听到公网，也不要让不可信的本机进程改写 cc-switch 配置。

## 部署到公网前必须做的

1. **加认证**：在反向代理层加 Basic Auth / OAuth / SSO，或自己在 FastAPI 前面加中间件；同时限制 `/docs`、`/api/settings`、`/files`。
2. **收紧 CORS**：`backend/app/main.py` 目前是 `allow_origins=["*"]`，公网部署应改成你的域名。
3. **TLS**：只通过 HTTPS 暴露；WebSocket/SSE（`/api/events`）要允许长连接、关闭代理缓冲。
4. **隔离执行面**：ComfyUI、Pixal3D 默认信任本机调用，不要把它们的管理端口暴露到公网。
5. **限制上传**：当前上传没有大小/类型白名单之外的配额，公网部署需在代理层加 `client_max_body_size` 与速率限制。
6. **单实例**：SQLite + 进程内任务队列只适合单实例。要多副本请先换成 Postgres + 外部队列（Redis/Celery 等）。
7. **备份**：定期备份 `data/`（SQLite 用 `.backup` 或停机复制，避免直接拷贝 WAL 中的库）。

## 密钥处理

- 优先用环境变量注入（见 `.env.example`），不要把 Key 写进代码、Dockerfile 或 compose 文件。
- 如果 Key 曾经提交到 git，立刻在服务商后台轮换；从历史里删除并不能让它失效。
- 前端只应接触掩码值；不要把 `data/settings.json` 返回给未认证的客户端。

## 报告漏洞

请不要公开提交可利用细节。通过仓库的 Security Advisory（GitHub → Security → Report a vulnerability）私下联系维护者，并附上：

- 受影响版本 / commit
- 复现步骤与预期影响
- 是否需要特定配置（例如已暴露到公网）

我们会在确认后尽快回复并协调修复与披露时间。
