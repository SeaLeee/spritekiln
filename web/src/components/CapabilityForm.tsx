import { ChevronDown, Flame, ImagePlus, Upload, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Asset, type Capability, type Param } from '../api'
import { AssetThumb, Modal } from './ui'

type Values = Record<string, any>

function defaults(cap: Capability): Values {
  const v: Values = {}
  cap.params.forEach((p) => {
    v[p.name] = Array.isArray(p.default) ? [...(p.default as unknown[])] : p.default ?? (p.type === 'bool' ? false : '')
  })
  return v
}

function choiceList(p: Param) {
  return (p.choices || []).map((c) => (typeof c === 'object' ? c : { value: c, label: String(c) }))
}

export function AssetPicker({ open, onClose, assets, onPick, multi = false, projectId }: {
  open: boolean; onClose: () => void; assets: Asset[]; onPick: (ids: string[]) => void; multi?: boolean; projectId: string
}) {
  const [sel, setSel] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const pickable = assets.filter((a) => a.kind === 'image' || a.kind === 'animation')
  useEffect(() => { setSel([]) }, [open])
  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    const ids: string[] = []
    for (const f of Array.from(files)) ids.push((await api.upload(projectId, f, f.name)).id)
    onPick(ids)
    onClose()
  }
  return (
    <Modal open={open} onClose={onClose} title={multi ? '选择素材（可多选，按点击顺序）' : '选择素材'} wide>
      <div className="flex items-center gap-2 mb-3">
        <button className="btn" onClick={() => fileRef.current?.click()}><Upload size={14} />上传图片</button>
        <input ref={fileRef} type="file" accept="image/*" multiple={multi} hidden onChange={(e) => upload(e.target.files)} />
        {multi && <button className="btn btn-ink ml-auto" disabled={!sel.length} onClick={() => { onPick(sel); onClose() }}>使用 {sel.length} 张</button>}
      </div>
      {pickable.length === 0 && <p className="text-sm text-ink-soft py-8 text-center">项目里还没有图片，先上传或生成一张。</p>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-3">
        {pickable.slice().reverse().map((a) => {
          const idx = sel.indexOf(a.id)
          return (
            <button key={a.id} className={`relative rounded-lg border p-1.5 text-left bg-white ${idx >= 0 ? 'border-ember ring-2 ring-ember/30' : 'border-mat-line hover:border-ink-soft'}`}
              onClick={() => {
                if (!multi) { onPick([a.id]); onClose(); return }
                setSel((s) => (idx >= 0 ? s.filter((x) => x !== a.id) : [...s, a.id]))
              }}>
              <AssetThumb asset={a} size={100} />
              <div className="text-[11px] mt-1 truncate">{a.name}</div>
              {idx >= 0 && <span className="absolute top-1 right-1 bg-ember text-white text-[10px] rounded-full w-5 h-5 grid place-items-center">{idx + 1}</span>}
            </button>
          )
        })}
      </div>
    </Modal>
  )
}

function ImageField({ p, value, onChange, assets, projectId }: {
  p: Param; value: any; onChange: (v: any) => void; assets: Asset[]; projectId: string
}) {
  const [open, setOpen] = useState(false)
  const multi = p.type === 'images'
  const ids: string[] = multi ? (value || []) : value ? [value] : []
  const byId = (id: string) => assets.find((a) => a.id === id)
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {ids.map((id, i) => {
          const a = byId(id)
          return (
            <div key={id + i} className="relative">
              {a ? <AssetThumb asset={a} size={64} /> : <div className="w-16 h-16 checker rounded-md grid place-items-center text-[10px] font-mono">{id.slice(-6)}</div>}
              <button className="absolute -top-1.5 -right-1.5 bg-ink text-white rounded-full w-5 h-5 grid place-items-center"
                aria-label="移除" onClick={() => onChange(multi ? ids.filter((x) => x !== id) : null)}><X size={12} /></button>
            </div>
          )
        })}
        {(multi || ids.length === 0) && (
          <button className="w-16 h-16 rounded-md border border-dashed border-ash grid place-items-center text-ink-soft hover:border-ink hover:text-ink"
            onClick={() => setOpen(true)} aria-label={`选择${p.label}`}><ImagePlus size={18} /></button>
        )}
      </div>
      <AssetPicker open={open} onClose={() => setOpen(false)} assets={assets} multi={multi} projectId={projectId}
        onPick={(picked) => onChange(multi ? [...ids, ...picked] : picked[0])} />
    </div>
  )
}

export function Field({ p, value, onChange, assets, projectId }: {
  p: Param; value: any; onChange: (v: any) => void; assets: Asset[]; projectId: string
}) {
  const id = `f-${p.name}`
  const label = (
    <label htmlFor={id} className="label">
      {p.label}{p.required && <span className="text-ember"> *</span>}
    </label>
  )
  let input
  switch (p.type) {
    case 'longtext':
      input = <textarea id={id} className="field min-h-[84px] resize-y" value={value ?? ''} placeholder={p.help} onChange={(e) => onChange(e.target.value)} />
      break
    case 'lines':
      input = <textarea id={id} className="field min-h-[72px] font-mono text-xs" value={(value || []).join('\n')}
        onChange={(e) => onChange(e.target.value.split('\n'))} placeholder="每行一项" />
      break
    case 'int':
    case 'float':
      input = <input id={id} className="field font-mono" type="number" step={p.type === 'float' ? 0.05 : 1} value={value ?? ''}
        min={p.min ?? undefined} max={p.max ?? undefined} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
      break
    case 'bool':
      return (
        <label className="flex items-center gap-2 text-sm cursor-pointer py-1">
          <input type="checkbox" className="accent-[var(--color-glaze)] w-4 h-4" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
          {p.label}
        </label>
      )
    case 'select': {
      const list = choiceList(p)
      if (list.length <= 4 && list.every((c) => String(c.label).length <= 8)) {
        input = (
          <div className="flex rounded-lg border border-mat-line bg-white p-0.5" role="radiogroup" aria-label={p.label}>
            {list.map((c) => (
              <button key={String(c.value)} role="radio" aria-checked={value === c.value}
                className={`flex-1 rounded-md px-2 py-1 text-xs ${String(value) === String(c.value) ? 'bg-ink text-white' : 'text-ink-soft hover:text-ink'}`}
                onClick={() => onChange(c.value)}>{c.label}</button>
            ))}
          </div>
        )
      } else {
        input = (
          <select id={id} className="field" value={String(value)} onChange={(e) => {
            const c = list.find((x) => String(x.value) === e.target.value)
            onChange(c ? c.value : e.target.value)
          }}>
            {list.map((c) => <option key={String(c.value)} value={String(c.value)}>{c.label}</option>)}
          </select>
        )
      }
      break
    }
    case 'image':
    case 'images':
      input = <ImageField p={p} value={value} onChange={onChange} assets={assets} projectId={projectId} />
      break
    case 'color':
      input = (
        <div className="flex gap-2">
          <input id={id} className="field font-mono" value={value ?? ''} placeholder="#ffffff / 留空自动" onChange={(e) => onChange(e.target.value)} />
          <input type="color" aria-label="取色" className="w-10 h-9 rounded border border-mat-line" value={/^#[0-9a-f]{6}$/i.test(value || '') ? value : '#ffffff'} onChange={(e) => onChange(e.target.value)} />
        </div>
      )
      break
    default:
      input = <input id={id} className="field" value={value ?? ''} placeholder={p.help} onChange={(e) => onChange(e.target.value)} />
  }
  return (
    <div>
      {label}
      {input}
      {p.help && p.type !== 'longtext' && p.type !== 'text' && <p className="text-[11px] text-ink-soft mt-1">{p.help}</p>}
    </div>
  )
}

export function CapabilityForm({ cap, projectId, assets, preset, onSubmitted }: {
  cap: Capability; projectId: string; assets: Asset[]; preset?: Values | null; onSubmitted?: (jobId: string) => void
}) {
  const [values, setValues] = useState<Values>(() => ({ ...defaults(cap), ...(preset || {}) }))
  const [showAdv, setShowAdv] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setValues({ ...defaults(cap), ...(preset || {}) }) }, [cap, preset])
  const basic = useMemo(() => cap.params.filter((p) => !p.advanced), [cap])
  const adv = useMemo(() => cap.params.filter((p) => p.advanced), [cap])
  const set = (k: string) => (v: any) => setValues((s) => ({ ...s, [k]: v }))

  const submit = async () => {
    setErr(null)
    const missing = cap.params.find((p) => p.required && (values[p.name] === '' || values[p.name] == null || (Array.isArray(values[p.name]) && !values[p.name].length)))
    if (missing) { setErr(`请填写「${missing.label}」`); return }
    setBusy(true)
    try {
      const params = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Array.isArray(v) ? v.filter((x) => x !== '') : v]))
      const job = await api.run(cap.id, projectId, params)
      onSubmitted?.(job.id)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-[13px] leading-relaxed text-ink-soft">{cap.description}</p>
        {cap.hint && <p className="text-[12px] mt-1 text-glaze">提示：{cap.hint}</p>}
      </div>
      {basic.map((p) => <Field key={p.name} p={p} value={values[p.name]} onChange={set(p.name)} assets={assets} projectId={projectId} />)}
      {adv.length > 0 && (
        <div>
          <button className="text-xs text-ink-soft inline-flex items-center gap-1 hover:text-ink" onClick={() => setShowAdv((s) => !s)} aria-expanded={showAdv}>
            <ChevronDown size={14} className={showAdv ? 'rotate-180' : ''} />高级参数
          </button>
          {showAdv && <div className="space-y-3 mt-2">{adv.map((p) => <Field key={p.name} p={p} value={values[p.name]} onChange={set(p.name)} assets={assets} projectId={projectId} />)}</div>}
        </div>
      )}
      {err && <p className="text-xs text-danger" role="alert">{err}</p>}
      <button className="btn btn-fire w-full !py-2.5" onClick={submit} disabled={busy}>
        <Flame size={16} />{busy ? '送入窑中…' : '烧制'}
      </button>
    </div>
  )
}
