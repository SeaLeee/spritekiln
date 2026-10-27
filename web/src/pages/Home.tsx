import { ArrowRight, Circle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, timeAgo, useHealth, type Project } from '../api'

const LAUNCHERS = [
  { key: 'pixel-asset-pack', title: '像素美术', desc: '角色、道具、素材包 —— 精确尺寸、共享调色板', swatch: ['#1c2333', '#ff5a1f', '#f2b134', '#e4ebe5'] },
  { key: 'asset-pack', title: '高清美术', desc: '高清角色 2×2、素材包 4×4、通用生成', swatch: ['#157f7a', '#d6ebe8', '#f7f9f6', '#586273'] },
  { key: 'animation', title: '动画与关键帧', desc: '静帧 → 本地视频模型 → 锁色帧动画', swatch: ['#ff5a1f', '#d9430f', '#1c2333', '#f2b134'] },
  { key: 'map-editor', title: '游戏地图', desc: '无缝纹理、Dual-Grid 地块、等角、横版视差', swatch: ['#3f7d4a', '#8a5a3b', '#c4b48a', '#e4ebe5'] },
  { key: 'ui-agent', title: '游戏 UI', desc: 'HUD、菜单、按钮与图标，自动拆组件', swatch: ['#586273', '#f7f9f6', '#157f7a', '#f2b134'] },
  { key: 'threed', title: '3D 管线', desc: 'Pixal3D 生成 GLB → 渲染 8 方向精灵', swatch: ['#1c2333', '#9aa4af', '#cbd6cd', '#ff5a1f'] },
]

/** A tiny sprite drawn as data so the hero shows the product's actual output medium: pixels, fired. */
const SPRITE = [
  '....aaaa....', '...abbbba...', '..abccccba..', '..abcddcba..', '..abccccba..', '...abbbba...',
  '....aeea....', '...aeffea...', '..aeffffea..', '..ae.ff.ea..', '...a.ff.a...', '....aa.aa...',
]
const COLORS: Record<string, string> = { a: '#1c2333', b: '#d9430f', c: '#ff5a1f', d: '#ffe7a3', e: '#157f7a', f: '#f2b134' }

function HeroSprite() {
  return (
    <div className="grid gap-0" style={{ gridTemplateColumns: 'repeat(12, 14px)' }} aria-hidden>
      {SPRITE.flatMap((row, y) => row.split('').map((ch, x) => (
        <span key={`${x}-${y}`} style={{ width: 14, height: 14, background: COLORS[ch] || 'transparent',
          transition: 'background .4s', transitionDelay: `${(x + y) * 25}ms` }} />
      )))}
    </div>
  )
}

export default function Home() {
  const health = useHealth()
  const [projects, setProjects] = useState<Project[]>([])
  useEffect(() => { api.projects().then(setProjects).catch(() => {}) }, [])
  const engines = health ? [
    { label: 'ComfyUI 生图/视频', ok: health.providers.image?.comfyui?.ok, detail: health.providers.image?.comfyui?.detail },
    { label: 'Pixal3D 3D', ok: health.providers.threed?.pixal3d?.ok, detail: health.providers.threed?.pixal3d?.detail },
    { label: '本地大模型', ok: health.providers.llm?.llm_local?.ok, detail: health.providers.llm?.llm_local?.detail },
    { label: 'BiRefNet 抠图', ok: health.providers.bg?.birefnet?.ok, detail: health.providers.bg?.birefnet?.detail },
    { label: '云端 API', ok: ['openai', 'ark', 'minimax'].some((k) => health.providers.image?.[k]?.ok), detail: '在设置中配置 GPT Image / Seedream / MiniMax' },
  ] : []

  return (
    <div className="h-full overflow-y-auto scroll-thin mat">
      <div className="max-w-6xl mx-auto px-8 py-10">
        <section className="grid md:grid-cols-[1fr_auto] gap-10 items-center">
          <div>
            <p className="eyebrow mb-3">本地 AI 游戏素材工坊 · local-first</p>
            <h1 className="font-display text-[2.6rem] leading-[1.1] tracking-tight">
              一句话进窑，<br />出来的是能直接进游戏的素材。
            </h1>
            <p className="mt-4 text-ink-soft max-w-xl leading-relaxed">
              用本机的 Z-Image、MiniMax H3、Pixal3D 和你配置的云端模型，生成像素/高清角色、动画帧、地块、UI 和 3D 模型；
              Claude Code / Codex 通过 Skill 与 MCP 也能直接调用，产物一键写入 Godot。
            </p>
            <div className="mt-6 flex gap-2">
              <Link to="/studio?launch=pixel-asset-pack" className="btn btn-fire !px-4 !py-2.5">开始烧制 <ArrowRight size={16} /></Link>
              <Link to="/skills" className="btn !px-4 !py-2.5">接入我的 Agent</Link>
            </div>
          </div>
          <div className="panel p-6 hidden md:block">
            <HeroSprite />
            <p className="eyebrow mt-3 text-center">12 × 12 · 6 色 · 出窑</p>
          </div>
        </section>

        <section className="mt-10" aria-label="本地引擎状态">
          <div className="flex flex-wrap gap-2">
            {engines.map((e) => (
              <span key={e.label} className="chip !py-1 !px-2.5 !text-xs" title={e.detail}>
                <Circle size={8} fill={e.ok ? 'var(--color-glaze)' : 'var(--color-ash)'} stroke="none" />
                {e.label}
                <span className="text-ink-soft max-w-[220px] truncate">{e.detail}</span>
              </span>
            ))}
            {!health && <span className="chip">检测本地引擎…</span>}
          </div>
        </section>

        <section className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {LAUNCHERS.map((l) => (
            <Link key={l.key} to={`/studio?launch=${l.key}`} className="panel p-5 group hover:border-ink-soft transition-colors">
              <div className="flex gap-1 mb-4" aria-hidden>
                {l.swatch.map((c) => <span key={c} className="w-5 h-5 rounded-[3px] border border-black/10" style={{ background: c }} />)}
              </div>
              <h2 className="font-semibold text-lg flex items-center gap-2">{l.title}
                <ArrowRight size={16} className="opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition" />
              </h2>
              <p className="text-sm text-ink-soft mt-1">{l.desc}</p>
            </Link>
          ))}
          <Link to="/design" className="panel p-5 sm:col-span-2 lg:col-span-3 flex items-center gap-4 hover:border-ink-soft">
            <div>
              <h2 className="font-semibold text-lg">策划 Agent</h2>
              <p className="text-sm text-ink-soft mt-1">先想清楚玩法和素材清单，再让素材 Agent 按清单批量烧制。</p>
            </div>
            <ArrowRight size={18} className="ml-auto" />
          </Link>
        </section>

        {projects.length > 0 && (
          <section className="mt-10">
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="font-semibold">最近的项目</h2>
              <Link to="/projects" className="text-sm text-ink-soft hover:text-ink">全部项目</Link>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {projects.slice(0, 4).map((p) => (
                <Link key={p.id} to={`/studio/${p.id}`} className="panel overflow-hidden hover:border-ink-soft">
                  <div className="checker h-28 grid place-items-center">
                    {p.cover_url ? <img src={p.cover_url} alt="" className="pixelated max-h-24" /> : <span className="text-ink-soft text-xs">暂无素材</span>}
                  </div>
                  <div className="p-3">
                    <div className="font-medium text-sm truncate">{p.name}</div>
                    <div className="text-xs text-ink-soft">{p.asset_count} 个素材 · {timeAgo(p.updated_at)}</div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
