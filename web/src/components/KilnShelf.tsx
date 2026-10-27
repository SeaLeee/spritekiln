import { Ban, RotateCcw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, PROVIDER_LABEL, useCapabilities, useEvents, type Job } from '../api'

const STATUS: Record<Job['status'], string> = {
  queued: '待烧制', running: '烧制中', succeeded: '出窑', failed: '炸窑', canceled: '已取消',
}

export function useJobs(projectId?: string) {
  const [jobs, setJobs] = useState<Job[]>([])
  const load = useCallback(() => {
    api.jobs(projectId).then(setJobs).catch(() => {})
  }, [projectId])
  useEffect(() => { load() }, [load])
  useEvents((ev) => {
    if (ev.type !== 'job') return
    const j: Job = ev.job
    if (projectId && j.project_id !== projectId) return
    setJobs((prev) => {
      const i = prev.findIndex((x) => x.id === j.id)
      if (i === -1) return [j, ...prev]
      const next = prev.slice()
      next[i] = { ...prev[i], ...j }
      return next
    })
  })
  return { jobs, reload: load }
}

/** The kiln shelf: each job is a tile whose heat bar warms from glaze to ember while it fires. */
export function KilnShelf({ jobs, onPick, limit = 30 }: { jobs: Job[]; onPick?: (j: Job) => void; limit?: number }) {
  const caps = useCapabilities()
  const name = (id: string) => caps?.capabilities.find((c) => c.id === id)?.name || id
  const shown = jobs.slice(0, limit)
  if (!shown.length) return <p className="text-sm text-ink-soft px-1 py-6 text-center">窑里还空着。选个能力，点“烧制”。</p>
  return (
    <ul className="space-y-2">
      {shown.map((j) => {
        const live = j.status === 'running' || j.status === 'queued'
        const pct = j.status === 'succeeded' ? 100 : Math.round((j.progress || 0) * 100)
        const engines = Object.entries(j.providers || {}).filter(([k]) => k !== 'bg').map(([, v]) => PROVIDER_LABEL[v] || v)
        return (
          <li key={j.id} className="rounded-lg border border-mat-line bg-white px-3 py-2">
            <div className="flex items-center gap-2">
              <button className="text-left flex-1 min-w-0" onClick={() => onPick?.(j)}>
                <div className="text-sm font-medium truncate">{name(j.capability)}</div>
                <div className="text-[11px] text-ink-soft truncate">
                  {j.status === 'failed' ? j.error : j.message || STATUS[j.status]}
                </div>
              </button>
              <span className={`chip !text-[10px] ${j.status === 'failed' ? '!border-danger text-danger' : j.status === 'succeeded' ? '!border-glaze text-glaze' : ''}`}>
                {STATUS[j.status]}
              </span>
              {live ? (
                <button className="btn btn-ghost btn-sm !px-1" title="取消" aria-label="取消任务" onClick={() => api.cancel(j.id)}><Ban size={14} /></button>
              ) : (
                <button className="btn btn-ghost btn-sm !px-1" title="重新烧制" aria-label="重试任务" onClick={() => api.retry(j.id)}><RotateCcw size={14} /></button>
              )}
            </div>
            <div className="mt-1.5 h-1.5 rounded-full heat-track overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div
                className={`h-full heat-bar ${j.status === 'running' ? 'heat-running' : ''}`}
                style={{
                  width: `${Math.max(live ? 4 : 0, pct)}%`,
                  backgroundPosition: `${100 - pct}% 0`,
                  ...(j.status === 'succeeded' ? { background: 'var(--color-glaze)' } : {}),
                  ...(j.status === 'failed' ? { background: 'var(--color-danger)' } : {}),
                }}
              />
            </div>
            <div className="mt-1 flex gap-2 text-[10px] font-mono text-ash">
              <span>{j.lane}</span>
              {engines.length > 0 && <span>{engines.join(' · ')}</span>}
              {j.cost_usd > 0 && <span>${j.cost_usd.toFixed(3)}</span>}
              {j.finished_at && j.started_at && <span>{Math.round(j.finished_at - j.started_at)}s</span>}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
