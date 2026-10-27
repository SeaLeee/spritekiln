import { Camera, Cuboid } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, useCapabilities, useEvents, type Asset, type Project } from '../api'
import { CapabilityForm } from '../components/CapabilityForm'
import { GlbViewer, type ViewerHandle } from '../components/GlbViewer'
import { KilnShelf, useJobs } from '../components/KilnShelf'
import { AssetThumb } from '../components/ui'

const DIR8 = ['S', 'SE', 'E', 'NE', 'N', 'NW', 'W', 'SW']

export default function ThreeD() {
  const [search, setSearch] = useSearchParams()
  const caps = useCapabilities()
  const [projects, setProjects] = useState<Project[]>([])
  const [pid, setPid] = useState<string>('')
  const [assets, setAssets] = useState<Asset[]>([])
  const [capId, setCapId] = useState('image_to_3d')
  const [modelId, setModelId] = useState<string | null>(search.get('asset'))
  const [yaw, setYaw] = useState(0)
  const [elev, setElev] = useState(30)
  const [toon, setToon] = useState(true)
  const [dirs, setDirs] = useState(8)
  const [size, setSize] = useState(64)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const viewer = useRef<ViewerHandle>(null)
  const { jobs } = useJobs(pid || undefined)

  useEffect(() => {
    api.projects().then(async (ps) => {
      setProjects(ps)
      if (modelId) {
        const a = await fetch(`/api/assets/${modelId}`).then((r) => r.json())
        setPid(a.project_id)
      } else if (ps.length) setPid((ps.find((p) => p.kind !== 'inbox') || ps[0]).id)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (pid) api.assets(pid).then(setAssets) }, [pid])
  useEvents((ev) => {
    if (ev.type === 'assets' && ev.project_id === pid) {
      setAssets((xs) => [...xs, ...ev.assets])
      const m = ev.assets.find((a: Asset) => a.kind === 'model3d')
      if (m) setModelId(m.id)
    }
  })
  const models = useMemo(() => assets.filter((a) => a.kind === 'model3d'), [assets])
  const model = models.find((m) => m.id === modelId) || null
  const cap = caps?.capabilities.find((c) => c.id === capId)

  const renderSprites = async () => {
    if (!viewer.current || !model) return
    setBusy(true)
    setStatus('渲染方向视图…')
    try {
      const blobs = await viewer.current.capture(dirs, 512)
      const labels = dirs === 8 ? DIR8 : dirs === 4 ? ['S', 'E', 'N', 'W'] : Array.from({ length: dirs }, (_, i) => `D${i}`)
      const ids: string[] = []
      for (const [i, b] of blobs.entries()) ids.push((await api.upload(pid, b, `render_${labels[i]}`, { role: 'input', pixel: 'false' })).id)
      await api.run('render_sprites', pid, { renders: ids, model: model.id, directions: labels, size, mode: 'pixel', outline: true })
      setStatus(`已提交 ${dirs} 个方向的像素化任务`)
    } catch (e: any) {
      setStatus(`失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full flex min-h-0">
      <aside className="w-[340px] shrink-0 border-r border-mat-line bg-paper flex flex-col min-h-0">
        <div className="p-3 border-b border-mat-line space-y-2">
          <h1 className="font-display text-xl flex items-center gap-2"><Cuboid size={18} />3D 管线</h1>
          <select className="field" value={pid} onChange={(e) => { setPid(e.target.value); setModelId(null) }} aria-label="项目">
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <div className="flex gap-1">
            {['image_to_3d', 'multiview_3d'].map((c) => (
              <button key={c} onClick={() => setCapId(c)}
                className={`flex-1 rounded-md px-2 py-1 text-xs border ${capId === c ? 'bg-ink text-white border-ink' : 'bg-white border-mat-line'}`}>
                {caps?.capabilities.find((x) => x.id === c)?.name}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto scroll-thin p-3 space-y-4">
          {cap && pid && <CapabilityForm cap={cap} projectId={pid} assets={assets} />}
          <div>
            <div className="eyebrow mb-1.5">窑炉</div>
            <KilnShelf jobs={jobs.filter((j) => ['image_to_3d', 'multiview_3d', 'render_sprites'].includes(j.capability))} limit={6} />
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 p-4 gap-3 mat">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="eyebrow">模型</span>
          {models.length === 0 && <span className="text-sm text-ink-soft">项目里还没有 3D 模型，先在左侧生成一个。</span>}
          {models.map((m) => (
            <button key={m.id} onClick={() => { setModelId(m.id); setSearch({ asset: m.id }) }}
              className={`chip !py-1 ${m.id === modelId ? '!border-ember text-ember' : ''}`}>{m.name}</button>
          ))}
          {model && <a className="btn btn-sm ml-auto" href={`/api/assets/${model.id}/download`}>下载 GLB（{model.meta?.size_mb} MB）</a>}
        </div>
        <div className="flex-1 min-h-0 panel p-2">
          {model ? <GlbViewer ref={viewer} url={model.url} yaw={yaw} elevation={elev} toon={toon} onStatus={setStatus} />
            : <div className="h-full grid place-items-center text-ink-soft text-sm">选择或生成一个模型</div>}
        </div>
        <div className="panel p-3 flex flex-wrap items-end gap-4">
          <label className="text-xs">朝向偏移 {yaw}°
            <input type="range" min={-180} max={180} value={yaw} onChange={(e) => setYaw(Number(e.target.value))} className="block w-40 accent-[var(--color-glaze)]" />
          </label>
          <label className="text-xs">俯角 {elev}°
            <input type="range" min={0} max={60} value={elev} onChange={(e) => setElev(Number(e.target.value))} className="block w-32 accent-[var(--color-glaze)]" />
          </label>
          <label className="text-xs flex items-center gap-1.5"><input type="checkbox" checked={toon} onChange={(e) => setToon(e.target.checked)} />卡通着色</label>
          <label className="text-xs">方向数
            <select className="field !py-1 mt-0.5" value={dirs} onChange={(e) => setDirs(Number(e.target.value))}>{[4, 8, 16].map((n) => <option key={n}>{n}</option>)}</select>
          </label>
          <label className="text-xs">精灵尺寸
            <select className="field !py-1 mt-0.5" value={size} onChange={(e) => setSize(Number(e.target.value))}>{[32, 48, 64, 96, 128].map((n) => <option key={n}>{n}</option>)}</select>
          </label>
          <button className="btn btn-fire" disabled={!model || busy} onClick={renderSprites}><Camera size={15} />渲染为方向精灵</button>
          <span className="text-xs text-ink-soft">{status}</span>
        </div>
        <div className="flex gap-2 overflow-x-auto scroll-thin">
          {assets.filter((a) => a.meta?.from_3d && a.role === 'output').slice(-16).map((a) => (
            <div key={a.id} className="text-center shrink-0"><AssetThumb asset={a} size={72} /><span className="text-[10px] font-mono">{a.meta?.direction}</span></div>
          ))}
        </div>
        <p className="text-[11px] text-ink-soft">3D → 2D：同一模型渲染出的方向视图天然一致，统一尺度 + 共享调色板后即是严格一致的 8 方向像素精灵。完整产物见 <Link className="underline" to={`/studio/${pid}`}>工作台</Link>。</p>
      </main>
    </div>
  )
}
