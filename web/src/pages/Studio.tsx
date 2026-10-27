import {
  applyNodeChanges, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeChange, type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Bot, Download, Eye, EyeOff, Gamepad2, PanelRight, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, downloadZip, useCapabilities, useEvents, type Asset, type Project } from '../api'
import { AgentDock } from '../components/AgentDock'
import { CapabilityForm } from '../components/CapabilityForm'
import { Inspector } from '../components/Inspector'
import { KilnShelf, useJobs } from '../components/KilnShelf'
import { AssetThumb, CapIcon, Modal } from '../components/ui'

const MODULE_ORDER = ['pixel', 'hd', 'character', 'animation', 'map', 'ui', 'edit', 'threed', 'design']
const LAUNCH: Record<string, [string, string]> = {
  'pixel-asset-pack': ['pixel', 'pixel_gen'], 'asset-pack': ['hd', 'hd_gen'], 'ui-agent': ['ui', 'ui_gen'],
  'map-editor': ['map', 'tileset_gen'], animation: ['animation', 'animate'], threed: ['threed', 'image_to_3d'],
  character: ['character', 'character_multi_view'], edit: ['edit', 'image_edit'], design: ['design', 'game_design'],
}

type AssetNodeData = { asset: Asset }

function AssetNode({ data }: NodeProps<Node<AssetNodeData>>) {
  const a = data.asset
  const size = a.kind === 'image' && a.role === 'raw' ? 150 : a.width > 300 ? 180 : 132
  return (
    <div className={`asset-node rounded-xl bg-white border shadow-sm p-1.5 ${a.role === 'raw' ? 'border-dashed border-ash opacity-80' : 'border-mat-line'}`}>
      <Handle type="target" position={Position.Left} className="!bg-ash !w-1.5 !h-1.5 !border-0" />
      <div className="relative"><AssetThumb asset={a} size={size} /></div>
      <div className="flex items-center gap-1 mt-1 px-0.5" style={{ maxWidth: size }}>
        <span className="text-[11px] font-medium truncate flex-1">{a.name}</span>
        {a.kind === 'animation' && <span className="chip !text-[9px] !py-0 !border-ember text-ember">{a.meta?.count}f</span>}
        {a.width > 0 && a.kind === 'image' && <span className="font-mono text-[9px] text-ash">{a.width}×{a.height}</span>}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-ash !w-1.5 !h-1.5 !border-0" />
    </div>
  )
}
const nodeTypes = { asset: AssetNode }

function Canvas({ assets, showRaw, onSelect, onSelection, projectId, onUploaded }: {
  assets: Asset[]; showRaw: boolean; onSelect: (a: Asset | null) => void; onSelection: (ids: string[]) => void
  projectId: string; onUploaded: () => void
}) {
  const visible = useMemo(() => assets.filter((a) => showRaw || (a.role !== 'raw' && a.role !== 'preview')), [assets, showRaw])
  const [nodes, setNodes] = useState<Node<AssetNodeData>[]>([])
  const rf = useReactFlow()
  const first = useRef(true)
  useEffect(() => {
    setNodes((prev) => visible.map((a) => {
      const old = prev.find((n) => n.id === a.id)
      return { id: a.id, type: 'asset', position: old?.position ?? { x: a.x, y: a.y }, data: { asset: a }, selected: old?.selected }
    }))
    if (first.current && visible.length) {
      first.current = false
      setTimeout(() => rf.fitView({ padding: 0.2, maxZoom: 1.2 }), 50)
    }
  }, [visible, rf])
  const edges: Edge[] = useMemo(() => {
    const ids = new Set(visible.map((a) => a.id))
    return visible.flatMap((a) => (a.parents || []).filter((p) => ids.has(p)).map((p) => ({ id: `${p}-${a.id}`, source: p, target: a.id })))
  }, [visible])
  const onNodesChange = useCallback((changes: NodeChange<Node<AssetNodeData>>[]) => setNodes((ns) => applyNodeChanges(changes, ns)), [])
  const onSelectionChange = useCallback(({ nodes: ns }: { nodes: Node[] }) => onSelection(ns.map((n) => n.id)), [onSelection])

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/') || f.name.endsWith('.glb'))
    if (!files.length) return
    const pos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    for (const [i, f] of files.entries()) {
      await api.upload(projectId, f, f.name, { x: String(pos.x + i * 30), y: String(pos.y + i * 30) })
    }
    onUploaded()
  }

  return (
    <div className="absolute inset-0 mat" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} minZoom={0.1} maxZoom={4}
        onNodeClick={(_, n) => onSelect(n.data.asset)} onPaneClick={() => onSelect(null)}
        onSelectionChange={onSelectionChange}
        onNodeDragStop={(_, n) => api.patchAsset(n.id, { x: n.position.x, y: n.position.y })}
        proOptions={{ hideAttribution: true }} selectionOnDrag={false} panOnScroll={false}
      >
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap pannable zoomable className="!bg-paper !border !border-mat-line" nodeColor="#cbd6cd" />
      </ReactFlow>
      {visible.length === 0 && (
        <div className="absolute inset-0 grid place-items-center pointer-events-none">
          <div className="text-center text-ink-soft">
            <div className="font-display text-2xl text-ink mb-1">工作台是空的</div>
            <p className="text-sm">在左侧选一个能力点“烧制”，或把图片拖进来作为参考 / 源素材。</p>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Studio() {
  const { pid } = useParams()
  const [search] = useSearchParams()
  const nav = useNavigate()
  const caps = useCapabilities()
  const [project, setProject] = useState<Project | null>(null)
  const [assets, setAssets] = useState<Asset[]>([])
  const [module, setModule] = useState('pixel')
  const [capId, setCapId] = useState('pixel_gen')
  const [preset, setPreset] = useState<Record<string, unknown> | null>(null)
  const [selected, setSelected] = useState<Asset | null>(null)
  const [selection, setSelection] = useState<string[]>([])
  const [rightTab, setRightTab] = useState<'inspect' | 'kiln'>('kiln')
  const [showRaw, setShowRaw] = useState(false)
  const [agentOpen, setAgentOpen] = useState(true)
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth >= 1280)
  const [godotOpen, setGodotOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const { jobs } = useJobs(pid)
  const onSelection = useCallback((ids: string[]) => {
    setSelection((prev) => (prev.length === ids.length && prev.every((x, i) => x === ids[i]) ? prev : ids))
  }, [])
  const onSelect = useCallback((a: Asset | null) => { setSelected(a); if (a) { setRightTab('inspect'); setPanelOpen(true) } }, [])

  // resolve project
  useEffect(() => {
    if (pid) return
    api.projects().then(async (ps) => {
      const p = ps.find((x) => x.kind !== 'inbox') || (await api.createProject('我的第一个游戏'))
      nav(`/studio/${p.id}${window.location.search}`, { replace: true })
    })
  }, [pid, nav])
  const loadAssets = useCallback(() => { if (pid) api.assets(pid).then(setAssets) }, [pid])
  useEffect(() => {
    if (!pid) return
    api.project(pid).then(setProject).catch(() => nav('/projects'))
    loadAssets()
  }, [pid, loadAssets, nav])
  useEffect(() => {
    const l = search.get('launch')
    if (l && LAUNCH[l]) { setModule(LAUNCH[l][0]); setCapId(LAUNCH[l][1]) }
  }, [search])
  useEvents((ev) => {
    if (ev.type === 'assets' && ev.project_id === pid) {
      setAssets((prev) => {
        const ids = new Set(prev.map((a) => a.id))
        return [...prev, ...ev.assets.filter((a: Asset) => !ids.has(a.id))]
      })
    }
  })

  const moduleCaps = useMemo(() => caps?.capabilities.filter((c) => c.module === module) || [], [caps, module])
  const cap = caps?.capabilities.find((c) => c.id === capId) || moduleCaps[0]
  const pickModule = (m: string) => {
    setModule(m)
    const first = caps?.capabilities.find((c) => c.module === m)
    if (first) setCapId(first.id)
    setPreset(null)
  }
  const doAction = (c: string, p: Record<string, unknown>) => {
    const target = caps?.capabilities.find((x) => x.id === c)
    if (!target) return
    setModule(target.module)
    setCapId(c)
    setPreset({ ...p })
  }

  if (!pid || !caps) return <div className="p-10 text-ink-soft">加载工作台…</div>

  return (
    <div className="h-full flex flex-col min-w-0 relative">
      {/* top bar */}
      <header className="flex items-center gap-3 px-4 h-12 border-b border-mat-line bg-paper shrink-0 min-w-0">
        <input className="font-display text-lg bg-transparent outline-none focus:bg-white rounded px-1 w-40 shrink-0" aria-label="项目名称"
          value={project?.name || ''} onChange={(e) => setProject((p) => p && { ...p, name: e.target.value })}
          onBlur={() => project && api.patchProject(project.id, { name: project.name })} />
        <nav className="flex gap-0.5 overflow-x-auto scroll-thin min-w-0" aria-label="能力模块">
          {MODULE_ORDER.filter((m) => caps.modules[m]).map((m) => (
            <button key={m} onClick={() => pickModule(m)}
              className={`px-2.5 py-1 rounded-md text-[13px] whitespace-nowrap ${module === m ? 'bg-ink text-white' : 'text-ink-soft hover:text-ink hover:bg-white'}`}>
              {caps.modules[m].name}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1.5 shrink-0">
          <button className="btn btn-ghost btn-sm" onClick={() => setShowRaw((s) => !s)} title="显示原始生成图与预览">
            {showRaw ? <Eye size={14} /> : <EyeOff size={14} />}原图
          </button>
          <button className="btn btn-sm" onClick={() => fileRef.current?.click()}><Upload size={14} />上传</button>
          <input ref={fileRef} type="file" accept="image/*,.glb" multiple hidden
            onChange={async (e) => { for (const f of Array.from(e.target.files || [])) await api.upload(pid, f, f.name); loadAssets() }} />
          <button className="btn btn-sm" onClick={() => downloadZip(pid, selection.length ? selection : null)}>
            <Download size={14} />{selection.length ? `导出 ${selection.length} 项` : '导出 ZIP'}
          </button>
          <button className="btn btn-sm" onClick={() => setGodotOpen(true)}><Gamepad2 size={14} />写入 Godot</button>
          <button className={`btn btn-sm ${agentOpen ? 'btn-ink' : ''}`} onClick={() => setAgentOpen((s) => !s)}><Bot size={14} />Agent</button>
          <button className={`btn btn-sm ${panelOpen ? 'btn-ink' : ''}`} onClick={() => setPanelOpen((s) => !s)} aria-label="切换检查器与窑炉面板"><PanelRight size={14} /></button>
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* tool panel */}
        <aside className="w-[300px] xl:w-[340px] shrink-0 border-r border-mat-line bg-paper flex flex-col min-h-0" aria-label="工具面板">
          <div className="p-3 border-b border-mat-line">
            <div className="eyebrow mb-1.5">{caps.modules[module]?.desc}</div>
            <div className="flex flex-wrap gap-1">
              {moduleCaps.map((c) => (
                <button key={c.id} onClick={() => { setCapId(c.id); setPreset(null) }}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] border ${cap?.id === c.id ? 'border-ink bg-ink text-white' : 'border-mat-line bg-white hover:border-ink-soft'}`}>
                  <CapIcon name={c.icon} size={13} />{c.name}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto scroll-thin p-3">
            {cap && <CapabilityForm cap={cap} projectId={pid} assets={assets} preset={preset}
              onSubmitted={() => { setRightTab('kiln'); setPanelOpen(true) }} />}
          </div>
        </aside>

        {/* canvas + agent */}
        <main className="flex-1 relative min-w-0">
          <ReactFlowProvider>
            <Canvas assets={assets} showRaw={showRaw} projectId={pid} onUploaded={loadAssets}
              onSelect={onSelect} onSelection={onSelection} />
          </ReactFlowProvider>
          {agentOpen && (
            <div className="absolute right-3 bottom-3 w-[min(420px,calc(100%-24px))] h-[min(340px,calc(100%-24px))] panel shadow-lg overflow-hidden z-10">
              <AgentDock projectId={pid} assets={assets} attach={selection} onClearAttach={() => {}} onClose={() => setAgentOpen(false)} />
            </div>
          )}
        </main>

        {/* right: inspector / kiln */}
        {panelOpen && <aside className="w-[300px] shrink-0 border-l border-mat-line bg-paper flex flex-col min-h-0 max-xl:absolute max-xl:right-0 max-xl:top-12 max-xl:bottom-0 max-xl:z-20 max-xl:shadow-xl">
          <div className="flex border-b border-mat-line" role="tablist">
            {(['inspect', 'kiln'] as const).map((t) => (
              <button key={t} role="tab" aria-selected={rightTab === t} onClick={() => setRightTab(t)}
                className={`flex-1 py-2.5 text-sm ${rightTab === t ? 'border-b-2 border-ember font-medium' : 'text-ink-soft'}`}>
                {t === 'inspect' ? '检查器' : `窑炉 ${jobs.filter((j) => j.status === 'running' || j.status === 'queued').length || ''}`}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto scroll-thin p-3">
            {rightTab === 'kiln' ? (
              <KilnShelf jobs={jobs} />
            ) : selected ? (
              <Inspector asset={selected} onAction={doAction}
                onDeleted={() => { setSelected(null); loadAssets() }}
                onChanged={(a) => { setSelected(a); setAssets((xs) => xs.map((x) => (x.id === a.id ? a : x))) }} />
            ) : (
              <p className="text-sm text-ink-soft text-center py-10">在画布上点一个素材查看详情。<br />Shift + 拖拽可多选，用于导出或交给 Agent。</p>
            )}
          </div>
        </aside>}
      </div>
      <GodotModal open={godotOpen} onClose={() => setGodotOpen(false)} pid={pid} selection={selection} />
    </div>
  )
}

function GodotModal({ open, onClose, pid, selection }: { open: boolean; onClose: () => void; pid: string; selection: string[] }) {
  const [path, setPath] = useState('')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { if (open) api.settings().then((s) => setPath(s.godot?.project_path || '')) }, [open])
  return (
    <Modal open={open} onClose={onClose} title="写入 Godot 项目">
      <p className="text-sm text-ink-soft mb-3">把{selection.length ? `选中的 ${selection.length} 个` : '全部产出'}素材写入 Godot 4 项目的 <code className="font-mono">res://assets/spritekiln/</code>，动画会生成 SpriteFrames(.tres) 与 AnimatedSprite2D 场景，并把画布纹理过滤设为“最近邻”。之后可由 Godot MCP 直接摆放到场景中。</p>
      <label className="label" htmlFor="godot-path">Godot 项目目录（含 project.godot）</label>
      <input id="godot-path" className="field font-mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\\Games\\MyGame" />
      {err && <p className="text-xs text-danger mt-2">{err}</p>}
      {res && (
        <div className="mt-3 text-xs bg-glaze-soft rounded-md p-2 max-h-48 overflow-auto font-mono">
          已写入 {res.assets.length} 项到 {res.res_dir}
          {res.assets.slice(0, 12).map((a: any) => <div key={a.id}>· {a.scene || a.files[0]}</div>)}
        </div>
      )}
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn" onClick={onClose}>关闭</button>
        <button className="btn btn-fire" onClick={async () => {
          setErr(null); setRes(null)
          try {
            await api.saveSettings({ godot: { project_path: path } })
            setRes(await api.exportGodot(pid, selection.length ? selection : null, path))
          } catch (e: any) { setErr(e.message) }
        }}>写入</button>
      </div>
    </Modal>
  )
}
