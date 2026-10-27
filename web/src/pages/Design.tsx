import { marked } from 'marked'
import { FileText, Save } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, useCapabilities, useEvents, type Project } from '../api'
import { CapabilityForm } from '../components/CapabilityForm'
import { KilnShelf, useJobs } from '../components/KilnShelf'

export default function Design() {
  const { pid } = useParams()
  const nav = useNavigate()
  const caps = useCapabilities()
  const [projects, setProjects] = useState<Project[]>([])
  const [docs, setDocs] = useState<{ name: string; modified: number }[]>([])
  const [current, setCurrent] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [editing, setEditing] = useState(false)
  const { jobs } = useJobs(pid)

  useEffect(() => {
    api.projects().then((ps) => {
      setProjects(ps)
      if (!pid && ps.length) nav(`/design/${(ps.find((p) => p.kind !== 'inbox') || ps[0]).id}`, { replace: true })
    })
  }, [pid, nav])
  const loadDocs = () => pid && api.docs(pid).then((d) => {
    setDocs(d)
    if (d.length && !current) setCurrent(d[d.length - 1].name)
  })
  useEffect(() => { setCurrent(null); setContent(''); loadDocs() }, [pid]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (pid && current) api.doc(pid, current).then((d) => setContent(d.content)) }, [pid, current])
  useEvents((ev) => {
    if (ev.type === 'assets' && ev.project_id === pid && ev.assets.some((a: any) => a.kind === 'doc')) {
      api.docs(pid!).then((d) => { setDocs(d); if (d.length) setCurrent(d[d.length - 1].name) })
    }
  })
  const html = useMemo(() => marked.parse(content || '') as string, [content])
  const cap = caps?.capabilities.find((c) => c.id === 'game_design')

  return (
    <div className="h-full flex min-h-0">
      <aside className="w-[340px] shrink-0 border-r border-mat-line bg-paper flex flex-col min-h-0">
        <div className="p-3 border-b border-mat-line space-y-2">
          <h1 className="font-display text-xl">策划 Agent</h1>
          <select className="field" value={pid || ''} onChange={(e) => nav(`/design/${e.target.value}`)} aria-label="项目">
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="flex-1 overflow-y-auto scroll-thin p-3 space-y-4">
          {cap && pid && <CapabilityForm cap={cap} projectId={pid} assets={[]} />}
          <div>
            <div className="eyebrow mb-1.5">设计文档</div>
            {docs.length === 0 && <p className="text-xs text-ink-soft">还没有文档。写下游戏想法，让 Agent 起草第一版 GDD。</p>}
            <ul className="space-y-1">
              {docs.slice().reverse().map((d) => (
                <li key={d.name}>
                  <button onClick={() => { setCurrent(d.name); setEditing(false) }}
                    className={`w-full text-left text-xs px-2 py-1.5 rounded-md flex items-center gap-1.5 ${d.name === current ? 'bg-ink text-white' : 'hover:bg-white'}`}>
                    <FileText size={13} /><span className="truncate">{d.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <KilnShelf jobs={jobs.filter((j) => j.capability === 'game_design')} limit={4} />
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto scroll-thin">
        {current ? (
          <div className="max-w-3xl mx-auto px-8 py-6">
            <div className="flex items-center gap-2 mb-3">
              <span className="font-mono text-xs text-ink-soft truncate">{current}</span>
              <div className="ml-auto flex gap-1.5">
                <button className="btn btn-sm" onClick={() => setEditing((e) => !e)}>{editing ? '预览' : '编辑'}</button>
                {editing && <button className="btn btn-sm btn-ink" onClick={() => api.saveDoc(pid!, current, content).then(() => setEditing(false))}><Save size={13} />保存</button>}
              </div>
            </div>
            {editing
              ? <textarea className="field font-mono text-xs min-h-[70vh]" value={content} onChange={(e) => setContent(e.target.value)} aria-label="文档内容" />
              : <article className="md panel px-8 py-6" dangerouslySetInnerHTML={{ __html: html }} />}
          </div>
        ) : (
          <div className="h-full grid place-items-center text-ink-soft text-sm mat">左侧输入游戏想法，生成第一份设计文档。</div>
        )}
      </main>
    </div>
  )
}
