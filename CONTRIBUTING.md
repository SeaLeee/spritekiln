# 参与贡献

感谢你愿意改进 SpriteKiln。这个项目优先保证「本地可跑、产物可验证、行为可解释」，提交前请先读下面几条。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
cd web; npm ci; npm run build; cd ..
python backend/run.py --reload         # API: http://127.0.0.1:7788/docs
cd web; npm run dev                    # 前端热更新（Vite 代理见 vite.config.ts）
```

可选依赖（本地 3D / 神经抠图）不写进 `requirements.txt`，按需安装：

- Pixal3D：见 [docs/03-3D管线.md](docs/03-3D管线.md)
- BiRefNet：`pip install torch torchvision transformers timm einops kornia`

## 提交前检查

```powershell
python -m pytest backend/tests -q
cd web; npm run build; cd ..
```

- 测试必须全绿。新增能力、导出格式或像素算法时，请同时补一个**确定性**测试（不依赖 GPU、网络或真实模型）。
- 前端改动后要确认 `npm run build` 通过（CI 会跑）。
- 不要把 `data/`、`.env`、API Key、个人绝对路径提交进仓库。本地路径请通过设置页、环境变量或 `/api/system` 读取。

## 新增一个能力

1. 在 `backend/app/capabilities/` 对应模块里 `register(Capability(...))`，参数用 `Param` 声明类型、默认值、可选值和 `advanced`。
2. 能力 ID 用小写下划线；给常见叫法加 `aliases`。
3. 只产出最终交付物时用 `role="output"`；中间结果用 `raw`，避免污染画布和导出。
4. 如果能力依赖某个 Provider，在 `needs` 里声明（`image` / `image_edit` / `video` / `llm` / `threed` / `bg`），路由会自动选健康引擎。
5. 补测试：离线环境用 `mock` / `procedural` 路由跑通一次。

## 新增一个模型 / 工作流

ComfyUI 走「一对文件」：

```text
backend/workflows/<name>.json       # ComfyUI API 格式工作流
backend/workflows/<name>.map.json   # 字段映射 + 需要的模型文件
```

`map.json` 里的 `fields` 把能力参数映射到节点输入，`models` 用来在文档和健康检查里提示缺失模型。改完在设置页把 `image_workflow` / `video_workflow` 指过去即可，不需要改 Python。

## 代码风格

- 后端：Python 3.10+，类型标注优先，异步函数里不要做长时间阻塞计算（用 `asyncio.to_thread`）。
- 前端：React + TypeScript，沿用现有组件与 Tailwind token，不引入第二套设计系统。
- 注释解释「为什么」，不要复述代码；中文注释和英文注释都可以，跟所在文件保持一致。

## 行为准则

- 不提交他人的私密素材、未授权模型权重或真实用户的 API Key。
- 讨论技术分歧时对事不对人；review 里说清楚可复现的步骤和预期。

## CLA（必须）

本项目同时以 AGPL-3.0 和商业许可分发，所以外部 Pull Request 需要先签署 [贡献者许可协议](CLA.md)：

> 在 PR 里回复：`I have read the CLA Document and I hereby sign the CLA.`

没有签署的 PR 会被标记为 `cla-required`，签署后再 review。

## 什么不在这个仓库

托管服务（账号、计费、多租户、GPU 调度、运营后台）是独立的私有项目，不要在这里提交相关代码。边界说明见 [docs/10-开源与商业边界.md](docs/10-开源与商业边界.md)。
