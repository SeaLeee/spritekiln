import { Bot, Loader2, Paperclip, SendHorizontal, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, chatStream, useCapabilities, useEvents, type Asset } from '../api'
import { AssetThumb } from './ui'

type Msg = { id: string; role: string; content: string; data?: any }

export function AgentDock({ projectId, assets, attach, onClearAttach, onClose }: {
  projectId: string; assets: Asset[]; attach: string[]; onClearAttach: () => void; onClose?: () => void
}) {
  const caps = useCapabilities()
  const [thread, setThread] = useState<string | null>(() => localStorage.getItem(`sk-thread-${projectId}`))
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [thinking, setThinking] = useState('')
  const [notice, setNotice] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const t = localStorage.getItem(`sk-thread-${projectId}`)
    setThread(t)
    if (t) api.thread(t).then(setMsgs).catch(() => setMsgs([]))
    else setMsgs([])
  }, [projectId])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, thinking, busy])
  useEffect(() => {
    if (!busy) return
    setElapsed(0)
    const t = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(t)
  }, [busy])
  useEvents((ev) => {
    if (ev.type === 'job' && thread && ['succeeded', 'failed'].includes(ev.job.status)) {
      api.thread(thread).then(setMsgs).catch(() => {})
    }
  })

  const send = async () => {
    const message = text.trim()
    if (!message || busy) return
    setBusy(true)
    setText('')
    setThinking('')
    setNotice('')
    setStatus('正在连接模型…')
    setMsgs((m) => [...m, { id: 'tmp', role: 'user', content: message }])
    let threadId = thread
    try {
      await chatStream({ project_id: projectId, thread_id: thread, message, attachments: attach }, (ev) => {
        if (ev.type === 'start') threadId = ev.thread_id
        else if (ev.type === 'status') setStatus(ev.text)
        else if (ev.type === 'meta') setStatus(`正在思考 · ${ev.label}`)
        else if (ev.type === 'reasoning') setThinking((t) => t + ev.text)
        else if (ev.type === 'content') setStatus('正在生成执行计划…')
        else if (ev.type === 'notice') setNotice(ev.text)
        else if (ev.type === 'error') setNotice(ev.text)
        else if (ev.type === 'done') threadId = ev.thread_id
      })
      if (threadId) {
        setThread(threadId)
        localStorage.setItem(`sk-thread-${projectId}`, threadId)
        setMsgs(await api.thread(threadId))
      }
      onClearAttach()
    } catch (e: any) {
      setMsgs((m) => [...m, { id: 'err', role: 'assistant', content: `请求失败：${e.message}` }])
    } finally {
      setBusy(false)
      setThinking('')
      setNotice('')
      setStatus('')
    }
  }
  const capName = (id: string) => caps?.capabilities.find((c) => c.id === id)?.name || id

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-mat-line">
        <Bot size={16} className="text-glaze" />
        <span className="font-medium text-sm">Kiln Agent</span>
        <span className="text-[11px] text-ink-soft">说需求，自动选能力并串联执行</span>
        <button className="btn btn-ghost btn-sm ml-auto" onClick={() => { localStorage.removeItem(`sk-thread-${projectId}`); setThread(null); setMsgs([]) }}>新对话</button>
        {onClose && <button className="btn btn-ghost btn-sm !px-1" onClick={onClose} aria-label="收起"><X size={14} /></button>}
      </div>
      <div className="flex-1 overflow-y-auto scroll-thin px-3 py-2 space-y-2">
        {msgs.length === 0 && (
          <div className="text-xs text-ink-soft space-y-1 py-2">
            <p>试试：</p>
            {['做 4 个 64px 的森林小怪，再给第一个做跳跃动画', '把选中的角色做成 8 方向', '为一款像素宠物店经营游戏写素材清单'].map((s) => (
              <button key={s} className="block text-left hover:text-ink underline decoration-dotted" onClick={() => setText(s)}>“{s}”</button>
            ))}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id + m.content.slice(0, 8)} className={m.role === 'user' ? 'flex justify-end' : ''}>
            <div className={`rounded-lg px-3 py-2 text-[13px] max-w-[92%] whitespace-pre-wrap ${m.role === 'user' ? 'bg-ink text-white' : 'bg-white border border-mat-line'}`}>
              {m.content}
              {m.data?.reasoning && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-[11px] text-ink-soft select-none">思考过程</summary>
                  <div className="mt-1 max-h-40 overflow-y-auto scroll-thin text-[11px] leading-relaxed text-ink-soft whitespace-pre-wrap border-l-2 border-mat-line pl-2">
                    {m.data.reasoning}
                  </div>
                </details>
              )}
              {m.data?.plan?.length > 0 && (
                <ol className="mt-1.5 space-y-0.5 text-[11px] font-mono text-ink-soft list-decimal pl-4">
                  {m.data.plan.map((s: any, i: number) => <li key={i}>{capName(s.capability)} <span className="text-ash">{s.why}</span></li>)}
                </ol>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex justify-start">
            <div className="rounded-lg px-3 py-2 text-[13px] max-w-[92%] bg-white border border-mat-line w-full">
              <div className="flex items-center gap-1.5 text-[11px] text-ink-soft">
                <Loader2 size={12} className="animate-spin" />
                <span>{status || '思考中…'}</span>
                <span className="ml-auto font-mono tabular-nums">{elapsed}s</span>
              </div>
              {notice && <p className="mt-1 text-[11px] text-glaze">{notice}</p>}
              {thinking && (
                <details open className="mt-1.5">
                  <summary className="cursor-pointer text-[11px] text-ink-soft select-none">思考过程（实时）</summary>
                  <div className="mt-1 max-h-48 overflow-y-auto scroll-thin text-[11px] leading-relaxed text-ink-soft whitespace-pre-wrap border-l-2 border-mat-line pl-2">
                    {thinking}
                  </div>
                </details>
              )}
            </div>
          </div>
        )}
        <div ref={end} />
      </div>
      {attach.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 pt-2">
          <Paperclip size={13} className="text-ink-soft" />
          {attach.map((id) => {
            const a = assets.find((x) => x.id === id)
            return a ? <AssetThumb key={id} asset={a} size={34} /> : null
          })}
          <button className="btn btn-ghost btn-sm" onClick={onClearAttach}>清除</button>
        </div>
      )}
      <div className="p-2 flex gap-2">
        <textarea className="field !min-h-[40px] h-10 resize-none" placeholder={attach.length ? '对附带的素材说点什么…' : '描述你要的素材…（Enter 发送）'}
          value={text} onChange={(e) => setText(e.target.value)} aria-label="给 Agent 的消息"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <button className="btn btn-ink" onClick={send} disabled={busy} aria-label="发送"><SendHorizontal size={16} /></button>
      </div>
    </div>
  )
}
