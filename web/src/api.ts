import { useEffect, useRef, useState } from 'react'

export type Param = {
  name: string
  type: 'text' | 'longtext' | 'int' | 'float' | 'bool' | 'select' | 'image' | 'images' | 'color' | 'lines'
  label: string
  default: unknown
  choices: (string | number | { value: string | number; label: string })[] | null
  min: number | null
  max: number | null
  help: string
  required: boolean
  advanced: boolean
}

export type Capability = {
  id: string
  name: string
  module: string
  description: string
  params: Param[]
  needs: string[]
  aliases: string[]
  outputs: string
  icon: string
  hint: string
}

export type Asset = {
  id: string
  project_id: string
  kind: 'image' | 'animation' | 'model3d' | 'doc' | 'video' | 'file'
  name: string
  path: string
  url: string
  width: number
  height: number
  meta: Record<string, any>
  parents: string[]
  job_id: string | null
  capability: string | null
  x: number
  y: number
  favorite: boolean
  role: 'output' | 'raw' | 'pack' | 'preview' | 'input'
  created_at: number
}

export type Job = {
  id: string
  project_id: string
  capability: string
  params: Record<string, unknown>
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
  progress: number
  message: string
  lane: string
  providers: Record<string, string>
  result: string[]
  error: string | null
  cost_usd: number
  created_at: number
  started_at: number | null
  finished_at: number | null
  assets?: Asset[]
}

export type Project = {
  id: string
  name: string
  kind: string
  description: string
  created_at: number
  updated_at: number
  asset_count?: number
  cover_url?: string | null
}

export type Health = {
  providers: Record<string, Record<string, { ok: boolean; detail: string; label: string; lane: string }>>
  routes: Record<string, string>
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const r = await fetch(url, init)
  if (!r.ok) {
    let msg = `${r.status}`
    try {
      const j = await r.json()
      msg = j.detail || JSON.stringify(j)
    } catch {
      msg = await r.text()
    }
    throw new Error(msg)
  }
  const ct = r.headers.get('content-type') || ''
  return (ct.includes('json') ? r.json() : (r.blob() as unknown)) as T
}

export type SystemInfo = {
  name: string
  version: string
  root: string
  data_dir: string
  skill_dir: string
  frontend_built: boolean
}

export const api = {
  system: () => req<SystemInfo>('GET', '/api/system'),
  health: (force = false) => req<Health>('GET', `/api/health${force ? '?force=true' : ''}`),
  settings: () => req<any>('GET', '/api/settings'),
  saveSettings: (patch: any) => req<any>('PUT', '/api/settings', patch),
  ccswitch: () => req<{ ok: boolean; base_url: string; model: string; provider: string; proxy: boolean; db: string; detail: string }>('GET', '/api/ccswitch'),
  capabilities: () => req<{ modules: Record<string, { name: string; desc: string }>; capabilities: Capability[] }>('GET', '/api/capabilities'),
  templates: () => req<any>('GET', '/api/templates'),
  projects: () => req<Project[]>('GET', '/api/projects'),
  project: (id: string) => req<Project>('GET', `/api/projects/${id}`),
  createProject: (name: string, description = '') => req<Project>('POST', '/api/projects', { name, description }),
  patchProject: (id: string, patch: Partial<Project>) => req<Project>('PATCH', `/api/projects/${id}`, patch),
  deleteProject: (id: string) => req('DELETE', `/api/projects/${id}`),
  assets: (pid: string) => req<Asset[]>('GET', `/api/projects/${pid}/assets`),
  upload: (pid: string, file: File | Blob, name = '', extra: Record<string, string> = {}) => {
    const fd = new FormData()
    fd.append('file', file, (file as File).name || `${name || 'upload'}.png`)
    fd.append('name', name)
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v))
    return req<Asset>('POST', `/api/projects/${pid}/assets`, fd)
  },
  patchAsset: (id: string, patch: Partial<Asset>) => req<Asset>('PATCH', `/api/assets/${id}`, patch),
  deleteAsset: (id: string) => req('DELETE', `/api/assets/${id}`),
  run: (cap: string, project_id: string | null, params: Record<string, unknown>) =>
    req<Job>('POST', `/api/capabilities/${cap}/run`, { project_id, params }),
  jobs: (project_id?: string, status?: string) => {
    const q = new URLSearchParams()
    if (project_id) q.set('project_id', project_id)
    if (status) q.set('status', status)
    return req<Job[]>('GET', `/api/jobs?${q}`)
  },
  cancel: (id: string) => req<Job>('POST', `/api/jobs/${id}/cancel`),
  retry: (id: string) => req<Job>('POST', `/api/jobs/${id}/retry`),
  chat: (body: { project_id: string | null; thread_id: string | null; message: string; attachments: string[] }) =>
    req<any>('POST', '/api/agent/chat', body),
  thread: (id: string) => req<any[]>('GET', `/api/agent/threads/${id}`),
  threads: (pid: string) => req<any[]>('GET', `/api/agent/threads?project_id=${pid}`),
  docs: (pid: string) => req<{ name: string; size: number; modified: number }[]>('GET', `/api/projects/${pid}/docs`),
  doc: (pid: string, name: string) => req<{ name: string; content: string }>('GET', `/api/projects/${pid}/docs/${encodeURIComponent(name)}`),
  saveDoc: (pid: string, name: string, content: string) => req('PUT', `/api/projects/${pid}/docs/${encodeURIComponent(name)}`, { content }),
  exportGodot: (pid: string, asset_ids: string[] | null, godot_project?: string) =>
    req<any>('POST', `/api/projects/${pid}/export`, { target: 'godot', asset_ids, godot_project }),
  stats: () => req<any>('GET', '/api/stats'),
}

export async function downloadZip(pid: string, asset_ids: string[] | null) {
  const r = await fetch(`/api/projects/${pid}/export`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: 'zip', asset_ids }),
  })
  if (!r.ok) throw new Error(await r.text())
  const blob = await r.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `spritekiln_${pid.slice(-6)}.zip`
  a.click()
  URL.revokeObjectURL(a.href)
}

type Listener = (ev: any) => void
const listeners = new Set<Listener>()
let source: EventSource | null = null

function ensureSource() {
  if (source) return
  source = new EventSource('/api/events')
  source.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data)
      listeners.forEach((l) => l(ev))
    } catch {
      /* ignore keep-alives */
    }
  }
}

export function useEvents(fn: Listener) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    ensureSource()
    const l: Listener = (ev) => ref.current(ev)
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  }, [])
}

let capCache: Promise<Awaited<ReturnType<typeof api.capabilities>>> | null = null
export function useCapabilities() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.capabilities>> | null>(null)
  useEffect(() => {
    capCache ??= api.capabilities()
    capCache.then(setData)
  }, [])
  return data
}

export function useHealth(intervalMs = 20000) {
  const [h, setH] = useState<Health | null>(null)
  useEffect(() => {
    let alive = true
    const tick = () => api.health().then((x) => alive && setH(x)).catch(() => {})
    tick()
    const t = setInterval(tick, intervalMs)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [intervalMs])
  return h
}

export const CAP_NAMES: Record<string, string> = {}

export function timeAgo(ts: number) {
  const s = Date.now() / 1000 - ts
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`
  return `${Math.floor(s / 86400)} 天前`
}

export const PROVIDER_LABEL: Record<string, string> = {
  comfyui: 'ComfyUI', openai: 'GPT Image', ark: '火山方舟', minimax: 'MiniMax', mock: '离线', procedural: '程序化',
  ccswitch: 'cc-switch', llm_local: '本地 LLM', rules: '规则', pixal3d: 'Pixal3D', birefnet: 'BiRefNet', chroma: '键控',
}
