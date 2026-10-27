import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, useCapabilities } from '../api'
import { CapIcon } from '../components/ui'

function CodeBlock({ code }: { code: string }) {
  const [ok, setOk] = useState(false)
  return (
    <div className="relative">
      <pre className="bg-ink text-[#e9eef3] rounded-lg p-3 text-[12px] font-mono overflow-x-auto scroll-thin whitespace-pre">{code}</pre>
      <button className="absolute top-2 right-2 btn btn-sm !bg-white/10 !border-white/20 !text-white"
        onClick={() => { navigator.clipboard.writeText(code); setOk(true); setTimeout(() => setOk(false), 1500) }}>
        {ok ? <Check size={13} /> : <Copy size={13} />}{ok ? '已复制' : '复制'}
      </button>
    </div>
  )
}

export default function Skills() {
  const caps = useCapabilities()
  const [open, setOpen] = useState<string | null>(null)
  const [ROOT, setRoot] = useState('')
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:7788'
  useEffect(() => { api.system().then((s) => setRoot(s.root)).catch(() => {}) }, [])
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-5xl mx-auto px-8 py-8 space-y-8">
        <header>
          <p className="eyebrow mb-2">Skill · CLI · MCP · REST</p>
          <h1 className="font-display text-3xl">让你的 Agent 来烧制素材</h1>
          <p className="text-ink-soft mt-2 max-w-2xl">Claude Code、Codex、Cursor 等 Agent 通过同一套能力目录工作：Skill 负责“何时用哪个能力”的判断规则，CLI/MCP 负责执行，产物落在同一个项目画布里，你随时可以在网页上手动接管。</p>
        </header>

        <section className="grid md:grid-cols-2 gap-4">
          <div className="panel p-4 space-y-2">
            <h2 className="font-semibold">1 · 安装 Skill（Claude Code）</h2>
            <p className="text-sm text-ink-soft">把 skill 目录链接到全局技能库（与 Skill本地中心 的 Junction 方式一致）：</p>
            <CodeBlock code={`New-Item -ItemType Junction -Path "$env:USERPROFILE\\.claude\\skills\\spritekiln-game-assets" -Target "${ROOT}\\skills\\spritekiln-game-assets"`} />
            <p className="text-sm text-ink-soft">Codex：复制到 <code className="font-mono text-xs">%USERPROFILE%\.codex\skills\</code>。</p>
          </div>
          <div className="panel p-4 space-y-2">
            <h2 className="font-semibold">2 · 接入 MCP</h2>
            <p className="text-sm text-ink-soft">stdio MCP 服务器，暴露能力目录、提交/轮询任务、导出到 Godot：</p>
            <CodeBlock code={`claude mcp add spritekiln -- python "${ROOT}\\mcp\\spritekiln_mcp.py"`} />
            <CodeBlock code={JSON.stringify({ mcpServers: { spritekiln: { command: 'python', args: [`${ROOT}\\mcp\\spritekiln_mcp.py`], env: { SPRITEKILN_URL: origin } } } }, null, 2)} />
          </div>
          <div className="panel p-4 space-y-2 md:col-span-2">
            <h2 className="font-semibold">3 · 命令行（Skill 内置运行器）</h2>
            <CodeBlock code={`python skills/spritekiln-game-assets/kiln_api.py capabilities
python skills/spritekiln-game-assets/kiln_api.py run pixel_gen --param template=px_char_64 --param "prompt=forest adventurers" --output-dir ./outputs/heroes
python skills/spritekiln-game-assets/kiln_api.py run animate --param source=<asset_id> --param "prompt=walk cycle" --output-dir ./outputs/walk
python skills/spritekiln-game-assets/kiln_api.py export-godot --project <project_id> --godot "D:\\Games\\MyGame"`} />
            <p className="text-sm text-ink-soft">配合 Godot MCP（godot-ai）：素材写入 <code className="font-mono text-xs">res://assets/spritekiln/</code> 后，Agent 用 <code className="font-mono text-xs">node_create</code> / <code className="font-mono text-xs">node_set_property</code> 创建 AnimatedSprite2D 并挂上生成的 SpriteFrames，即可自主拼出可玩原型。</p>
          </div>
        </section>

        <section>
          <h2 className="font-semibold mb-1">REST API</h2>
          <p className="text-sm text-ink-soft mb-3">异步任务模式：提交 → 轮询 → 读产物。也兼容 <code className="font-mono text-xs">POST /api/workflows/&lt;id&gt;/run</code> 形态。交互式文档：<a className="underline" href="/docs" target="_blank">/docs</a></p>
          <CodeBlock code={`curl -X POST ${origin}/api/capabilities/pixel_gen/run -H "Content-Type: application/json" \\
  -d '{"params": {"template": "px_icon_32", "prompt": "alchemy ingredients"}}'
curl ${origin}/api/jobs/<job_id>          # status / progress / assets[]
curl -N ${origin}/api/events              # SSE 实时进度`} />
        </section>

        <section>
          <h2 className="font-semibold mb-3">能力目录（{caps?.capabilities.length ?? '…'}）</h2>
          <div className="grid md:grid-cols-2 gap-2">
            {caps?.capabilities.map((c) => (
              <div key={c.id} className="panel">
                <button className="w-full text-left p-3 flex items-start gap-2" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                  <CapIcon name={c.icon} />
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{c.name} <span className="font-mono text-[11px] text-ink-soft">{c.id}</span></div>
                    <div className="text-[12px] text-ink-soft">{c.description}</div>
                  </div>
                </button>
                {open === c.id && (
                  <table className="w-full text-[11px] font-mono border-t border-mat-line">
                    <tbody>
                      {c.params.map((p) => (
                        <tr key={p.name} className="border-b border-mat-line/60">
                          <td className="px-3 py-1">{p.name}{p.required && <span className="text-ember">*</span>}</td>
                          <td className="px-2 py-1 text-ink-soft">{p.type}</td>
                          <td className="px-2 py-1 text-ink-soft truncate max-w-[180px]">{JSON.stringify(p.default)}</td>
                          <td className="px-2 py-1 font-sans">{p.label}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
