import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { KilnShelf, useJobs } from '../components/KilnShelf'
import { AssetThumb } from '../components/ui'

export default function Jobs() {
  const { jobs } = useJobs()
  const [stats, setStats] = useState<any>(null)
  const [pick, setPick] = useState<string | null>(null)
  useEffect(() => { api.stats().then(setStats) }, [jobs.length])
  const job = jobs.find((j) => j.id === pick)
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-6xl mx-auto px-8 py-8 grid md:grid-cols-[1fr_360px] gap-6">
        <div>
          <h1 className="font-display text-3xl mb-1">窑炉记录</h1>
          {stats && (
            <p className="text-sm text-ink-soft mb-4">
              共 {Object.values(stats.jobs as Record<string, number>).reduce((a, b) => a + b, 0)} 次烧制 · 出窑 {stats.jobs.succeeded || 0} · 炸窑 {stats.jobs.failed || 0} · 今日云端估算 ${stats.spent_today_usd}
            </p>
          )}
          <KilnShelf jobs={jobs} limit={100} onPick={(j) => setPick(j.id)} />
        </div>
        <aside className="panel p-4 h-fit sticky top-4">
          {job ? (
            <div className="space-y-3">
              <div className="font-mono text-xs text-ink-soft">{job.id}</div>
              <Link to={`/studio/${job.project_id}`} className="btn btn-sm">打开所在项目</Link>
              <pre className="text-[11px] font-mono bg-white rounded p-2 overflow-auto max-h-60 border border-mat-line">{JSON.stringify(job.params, null, 2)}</pre>
              {job.error && <p className="text-xs text-danger break-words">{job.error}</p>}
              <div className="flex flex-wrap gap-2">{job.assets?.map((a) => <AssetThumb key={a.id} asset={a} size={72} />)}</div>
            </div>
          ) : <p className="text-sm text-ink-soft">点一条记录查看参数与产物。</p>}
        </aside>
      </div>
    </div>
  )
}
