import { Circle, RefreshCw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, PROVIDER_LABEL, type Health } from '../api'

const KIND_LABEL: Record<string, string> = { image: '生图', image_edit: '图像编辑', video: '动画/视频', llm: '大模型', threed: '3D', bg: '去背景' }

const PROVIDER_FIELDS: { key: string; title: string; note: string; fields: [string, string, boolean?][] }[] = [
  { key: 'ccswitch', title: 'cc-switch（Agent 首选）', note: '读取本机 cc-switch 当前 Codex provider 的模型与代理端口，Key 由 cc-switch 注入。地址/模型留空 = 自动跟随；代理没开时自动落到本地大模型。',
    fields: [['base_url', '代理地址（留空自动）'], ['model', '模型（留空自动）'], ['api_key', 'Key（通常不需要）', true]] },
  { key: 'comfyui', title: 'ComfyUI（本地）', note: 'Z-Image Turbo 生图/重绘 · MiniMax H3 首尾帧动画。模型文件留空 = 用工作流内置文件名；要换模型就填 ComfyUI models/ 下的相对路径。',
    fields: [['base_url', '地址'], ['image_workflow', '生图工作流'], ['img2img_workflow', '重绘工作流'], ['video_workflow', '视频工作流'], ['video_steps', '视频步数'],
      ['image_model', '生图主模型'], ['text_encoder', '文本编码器'], ['vae', 'VAE'],
      ['video_model', '视频主模型'], ['video_lora', '视频 LoRA'], ['video_text_encoder', '视频文本编码器'],
      ['video_vae', '视频 VAE'], ['video_audio_vae', '音频 VAE']] },
  { key: 'pixal3d', title: 'Pixal3D（本地 3D）', note: '单图 → PBR GLB。3090 建议开启低显存（1024 分辨率）。',
    fields: [['repo', '仓库目录'], ['python', 'venv Python'], ['resolution', '分辨率'], ['low_vram', '低显存模式']] },
  { key: 'llm_local', title: '本地大模型（Ollama / LM Studio）', note: 'OpenAI 兼容接口；用于 Agent 规划与策划文档。',
    fields: [['base_url', '地址'], ['model', '模型'], ['api_key', 'Key', true]] },
  { key: 'openai', title: 'OpenAI / 兼容中转（GPT Image）', note: '支持参考图、遮罩编辑、原生透明背景。',
    fields: [['base_url', '地址'], ['api_key', 'API Key', true], ['image_model', '图像模型'], ['llm_model', '对话模型']] },
  { key: 'ark', title: '火山方舟（Seedream / Seedance）', note: 'Seedream 多参考图一致性；Seedance 首尾帧视频。',
    fields: [['base_url', '地址'], ['api_key', 'API Key', true], ['image_model', '图像模型'], ['video_model', '视频模型'], ['llm_model', '对话模型']] },
  { key: 'minimax', title: 'MiniMax（image-01 / Hailuo）', note: '角色主体参考生图；Hailuo 首尾帧视频。',
    fields: [['base_url', '地址'], ['api_key', 'API Key', true], ['image_model', '图像模型'], ['video_model', '视频模型'], ['llm_model', '对话模型']] },
]

export default function Settings() {
  const [s, setS] = useState<any>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [cc, setCc] = useState<{ ok: boolean; provider: string; model: string; base_url: string; proxy: boolean; detail: string } | null>(null)
  const [saved, setSaved] = useState('')
  const load = () => {
    api.settings().then(setS)
    api.health(true).then(setHealth)
    api.ccswitch().then(setCc).catch(() => setCc(null))
  }
  useEffect(() => { load() }, [])
  if (!s) return <div className="p-8 text-ink-soft">加载设置…</div>
  const setProv = (k: string, f: string, v: any) => setS((x: any) => ({ ...x, providers: { ...x.providers, [k]: { ...x.providers[k], [f]: v } } }))
  const save = async () => {
    const out = await api.saveSettings(s)
    setS(out)
    setSaved('已保存')
    api.health(true).then(setHealth)
    setTimeout(() => setSaved(''), 2000)
  }

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-5xl mx-auto px-8 py-8 space-y-8">
        <div className="flex items-center gap-3">
          <h1 className="font-display text-3xl">设置</h1>
          <button className="btn ml-auto" onClick={load}><RefreshCw size={14} />重新检测</button>
          <button className="btn btn-ink" onClick={save}><Save size={14} />保存</button>
          {saved && <span className="text-sm text-glaze">{saved}</span>}
        </div>

        <section>
          <h2 className="font-semibold mb-1">路由</h2>
          <p className="text-sm text-ink-soft mb-3">“自动”= 按偏好顺序使用第一个可用引擎。大模型顺序是 cc-switch → 本地模型 → 云端 → 规则；图像/视频是本地优先、云端兜底、最后离线程序化。每次任务也可在表单里单独指定。</p>
          <div className="text-[12px] mb-3 text-ink-soft">
            cc-switch：{cc ? (cc.ok ? `${cc.provider} · ${cc.model} · ${cc.base_url}` : cc.detail) : '读取中…'}
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            {Object.keys(KIND_LABEL).map((k) => (
              <div key={k} className="panel p-3">
                <label className="label" htmlFor={`route-${k}`}>{KIND_LABEL[k]}</label>
                <select id={`route-${k}`} className="field" value={s.routing[k]} onChange={(e) => setS({ ...s, routing: { ...s.routing, [k]: e.target.value } })}>
                  <option value="auto">自动 → {PROVIDER_LABEL[health?.routes?.[k] || ''] || health?.routes?.[k] || '…'}</option>
                  {Object.keys(health?.providers?.[k === 'image_edit' ? 'image' : k] || {}).map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p] || p}</option>)}
                </select>
                <div className="mt-2 space-y-0.5">
                  {Object.entries(health?.providers?.[k === 'image_edit' ? 'image' : k] || {}).map(([p, h]) => (
                    <div key={p} className="flex items-center gap-1.5 text-[11px]" title={h.detail}>
                      <Circle size={7} fill={h.ok ? 'var(--color-glaze)' : 'var(--color-ash)'} stroke="none" />
                      <span className="w-16 shrink-0">{PROVIDER_LABEL[p] || p}</span>
                      <span className="text-ink-soft truncate">{h.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="font-semibold mb-3">模型服务</h2>
          <div className="grid md:grid-cols-2 gap-3">
            {PROVIDER_FIELDS.map((pf) => {
              const cfg = s.providers[pf.key] || {}
              return (
                <div key={pf.key} className="panel p-4">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium">{pf.title}</h3>
                    <label className="ml-auto text-xs flex items-center gap-1">
                      <input type="checkbox" checked={!!cfg.enabled} onChange={(e) => setProv(pf.key, 'enabled', e.target.checked)} />启用
                    </label>
                  </div>
                  <p className="text-[12px] text-ink-soft mb-2">{pf.note}</p>
                  <div className="space-y-2">
                    {pf.fields.map(([f, label, secret]) => typeof cfg[f] === 'boolean' ? (
                      <label key={f} className="text-sm flex items-center gap-2"><input type="checkbox" checked={cfg[f]} onChange={(e) => setProv(pf.key, f, e.target.checked)} />{label}</label>
                    ) : (
                      <div key={f}>
                        <label className="label" htmlFor={`${pf.key}-${f}`}>{label}</label>
                        <input id={`${pf.key}-${f}`} className="field font-mono !text-xs" type={secret ? 'password' : 'text'} value={cfg[f] ?? ''}
                          onChange={(e) => setProv(pf.key, f, typeof cfg[f] === 'number' ? Number(e.target.value) : e.target.value)} />
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="grid md:grid-cols-3 gap-3">
          <div className="panel p-4">
            <h3 className="font-medium mb-1">云端预算</h3>
            <p className="text-[12px] text-ink-soft mb-2">每日云端费用上限（美元，估算）。超出后云端任务会被拒绝，本地引擎不受影响。0 = 不限。</p>
            <input className="field font-mono" type="number" step={0.5} value={s.budget.daily_cloud_usd}
              onChange={(e) => setS({ ...s, budget: { daily_cloud_usd: Number(e.target.value) } })} aria-label="每日预算" />
          </div>
          <div className="panel p-4">
            <h3 className="font-medium mb-1">并发</h3>
            <p className="text-[12px] text-ink-soft mb-2">GPU 通道建议 1（单张 3090 串行，避免显存争抢）；云端可并发。重启后生效。</p>
            {(['gpu', 'cloud', 'cpu'] as const).map((k) => (
              <label key={k} className="flex items-center gap-2 text-sm mb-1"><span className="w-12 font-mono">{k}</span>
                <input className="field !py-1 font-mono" type="number" min={1} max={16} value={s.queue[k]} onChange={(e) => setS({ ...s, queue: { ...s.queue, [k]: Number(e.target.value) } })} />
              </label>
            ))}
          </div>
          <div className="panel p-4">
            <h3 className="font-medium mb-1">Godot</h3>
            <p className="text-[12px] text-ink-soft mb-2">“写入 Godot”的默认项目目录与素材子目录。</p>
            <label className="label" htmlFor="gp">项目目录</label>
            <input id="gp" className="field font-mono !text-xs mb-2" value={s.godot.project_path} onChange={(e) => setS({ ...s, godot: { ...s.godot, project_path: e.target.value } })} />
            <label className="label" htmlFor="gd">素材子目录</label>
            <input id="gd" className="field font-mono !text-xs" value={s.godot.asset_dir} onChange={(e) => setS({ ...s, godot: { ...s.godot, asset_dir: e.target.value } })} />
          </div>
        </section>
      </div>
    </div>
  )
}
