import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, timeAgo, type Project } from '../api'

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [name, setName] = useState('')
  const nav = useNavigate()
  const load = () => api.projects().then(setProjects)
  useEffect(() => { load() }, [])
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-5xl mx-auto px-8 py-8">
        <h1 className="font-display text-3xl mb-1">项目</h1>
        <p className="text-sm text-ink-soft mb-6">每个项目是一张独立的工作台画布，素材、动画、设计文档和导出都按项目隔离。</p>
        <form className="flex gap-2 mb-6" onSubmit={async (e) => {
          e.preventDefault()
          const p = await api.createProject(name.trim() || '未命名项目')
          nav(`/studio/${p.id}`)
        }}>
          <input className="field max-w-sm" placeholder="新项目名称，如：异世界魔宠店" value={name} onChange={(e) => setName(e.target.value)} aria-label="新项目名称" />
          <button className="btn btn-ink"><Plus size={15} />新建项目</button>
        </form>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <div key={p.id} className="panel overflow-hidden group">
              <Link to={`/studio/${p.id}`} className="block">
                <div className="checker h-36 grid place-items-center">
                  {p.cover_url ? <img src={p.cover_url} alt="" className="pixelated max-h-32" /> : <span className="text-xs text-ink-soft">暂无素材</span>}
                </div>
              </Link>
              <div className="p-3 flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <Link to={`/studio/${p.id}`} className="font-medium truncate block hover:underline">{p.name}</Link>
                  <div className="text-xs text-ink-soft">{p.kind === 'inbox' ? 'Agent/API 收件箱 · ' : ''}{p.asset_count} 个素材 · {timeAgo(p.updated_at)}</div>
                </div>
                <Link to={`/design/${p.id}`} className="btn btn-sm">策划</Link>
                <button className="btn btn-ghost btn-sm text-danger" aria-label={`删除 ${p.name}`}
                  onClick={async () => { if (confirm(`删除项目「${p.name}」及其全部素材？`)) { await api.deleteProject(p.id); load() } }}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
