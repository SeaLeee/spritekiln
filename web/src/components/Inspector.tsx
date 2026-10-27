import { Download, Heart, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, PROVIDER_LABEL, type Asset } from '../api'
import { CapIcon, isPixel } from './ui'

const ACTIONS: { cap: string; label: string; icon: string; key: string; kinds: Asset['kind'][] }[] = [
  { cap: 'animate', label: '做动画', icon: 'film', key: 'source', kinds: ['image'] },
  { cap: 'character_multi_view', label: '8 方向', icon: 'rotate', key: 'source', kinds: ['image'] },
  { cap: 'image_edit', label: '万能编辑', icon: 'pencil', key: 'source', kinds: ['image'] },
  { cap: 'asset_variants', label: '变体/升级', icon: 'layers', key: 'source', kinds: ['image'] },
  { cap: 'asset_clone', label: '同风格克隆', icon: 'copy', key: 'reference', kinds: ['image'] },
  { cap: 'remove_background', label: '去背景', icon: 'eraser', key: 'source', kinds: ['image', 'animation'] },
  { cap: 'pixelate', label: '像素化', icon: 'grid', key: 'source', kinds: ['image'] },
  { cap: 'split_components', label: '拆分组件', icon: 'scissors', key: 'source', kinds: ['image'] },
  { cap: 'image_to_3d', label: '转 3D', icon: 'cube', key: 'source', kinds: ['image'] },
  { cap: 'self_loop', label: '自循环', icon: 'repeat', key: 'source', kinds: ['image'] },
]

export function Inspector({ asset, onAction, onDeleted, onChanged }: {
  asset: Asset; onAction: (cap: string, preset: Record<string, unknown>) => void; onDeleted: () => void; onChanged: (a: Asset) => void
}) {
  const px = isPixel(asset)
  const [zoom, setZoom] = useState(px ? Math.max(1, Math.floor(240 / Math.max(asset.width || 1, asset.height || 1))) : 1)
  const [name, setName] = useState(asset.name)
  useEffect(() => {
    setName(asset.name)
    setZoom(px ? Math.max(1, Math.floor(240 / Math.max(asset.width || 1, asset.height || 1))) : 1)
  }, [asset.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const m = asset.meta || {}
  const files: Record<string, string> = m.file_urls || {}
  const palette: number[][] = m.palette || []

  return (
    <div className="space-y-4">
      <div className="checker rounded-lg grid place-items-center overflow-auto scroll-thin" style={{ height: 260 }}>
        {asset.kind === 'video' ? (
          <video src={asset.url} controls loop autoPlay muted className="max-h-full max-w-full" />
        ) : asset.kind === 'model3d' ? (
          <Link to={`/three?asset=${asset.id}`} className="btn btn-ink">在 3D 工作台打开</Link>
        ) : asset.kind === 'doc' ? (
          <Link to={`/design/${asset.project_id}`} className="btn btn-ink">在策划 Agent 中查看</Link>
        ) : (
          <img src={asset.url} alt={asset.name} className={px ? 'pixelated' : 'max-h-full max-w-full object-contain'}
            style={px ? { width: (asset.width || 64) * zoom } : undefined} />
        )}
      </div>
      {px && (asset.kind === 'image' || asset.kind === 'animation') && (
        <div className="flex items-center gap-2">
          <span className="eyebrow">缩放</span>
          <input type="range" min={1} max={12} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="flex-1 accent-[var(--color-glaze)]" aria-label="像素缩放" />
          <span className="font-mono text-xs w-8 text-right">{zoom}×</span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <input className="field !py-1 font-medium" value={name} onChange={(e) => setName(e.target.value)} aria-label="素材名称"
          onBlur={() => name !== asset.name && api.patchAsset(asset.id, { name }).then(onChanged)} />
        <button className={`btn btn-ghost btn-sm ${asset.favorite ? 'text-ember' : ''}`} aria-label="收藏"
          onClick={() => api.patchAsset(asset.id, { favorite: !asset.favorite }).then(onChanged)}>
          <Heart size={15} fill={asset.favorite ? 'currentColor' : 'none'} />
        </button>
        <button className="btn btn-ghost btn-sm text-danger" aria-label="删除素材"
          onClick={() => confirm('删除这个素材？') && api.deleteAsset(asset.id).then(onDeleted)}><Trash2 size={15} /></button>
      </div>

      <dl className="grid grid-cols-[72px_1fr] gap-y-1 text-xs">
        <dt className="text-ink-soft">类型</dt><dd>{asset.kind}{px ? ' · 像素' : ''}{asset.role !== 'output' ? ` · ${asset.role}` : ''}</dd>
        {asset.width > 0 && <><dt className="text-ink-soft">尺寸</dt><dd className="font-mono">{asset.width}×{asset.height}</dd></>}
        {m.count && <><dt className="text-ink-soft">帧</dt><dd className="font-mono">{m.count} 帧 · {m.fps} fps · {m.cols}×{m.rows}</dd></>}
        {m.direction && <><dt className="text-ink-soft">方向</dt><dd>{m.direction}{m.mirrored ? '（镜像）' : ''}</dd></>}
        {m.prompt && <><dt className="text-ink-soft">描述</dt><dd className="break-words">{m.prompt}</dd></>}
        {m.providers && <><dt className="text-ink-soft">引擎</dt><dd>{Object.entries(m.providers).map(([k, v]) => `${k}:${PROVIDER_LABEL[v as string] || v}`).join(' · ')}</dd></>}
        {m.seed != null && <><dt className="text-ink-soft">种子</dt><dd className="font-mono">{m.seed}</dd></>}
        <dt className="text-ink-soft">ID</dt><dd className="font-mono text-ink-soft select-all">{asset.id}</dd>
      </dl>

      {palette.length > 0 && (
        <div>
          <div className="eyebrow mb-1">调色板 · {palette.length}</div>
          <div className="flex flex-wrap gap-0.5">
            {palette.slice(0, 48).map((c, i) => (
              <span key={i} title={`rgb(${c.join(',')})`} className="w-4 h-4 rounded-[2px] border border-black/10" style={{ background: `rgb(${c.join(',')})` }} />
            ))}
          </div>
        </div>
      )}

      {asset.kind === 'animation' && m.frame_urls && (
        <div>
          <div className="eyebrow mb-1">逐帧</div>
          <div className="flex gap-1 overflow-x-auto scroll-thin pb-1">
            {m.frame_urls.map((u: string, i: number) => (
              <img key={u} src={u} alt={`第 ${i + 1} 帧`} className="checker pixelated rounded border border-mat-line h-12" />
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="eyebrow mb-1.5">下载</div>
        <div className="flex flex-wrap gap-1.5">
          <a className="btn btn-sm" href={`/api/assets/${asset.id}/download`}><Download size={13} />原文件</a>
          {px && asset.kind === 'image' && <a className="btn btn-sm" href={`/api/assets/${asset.id}/download?fmt=png&scale=4`}>PNG ×4</a>}
          {files.sheet && <a className="btn btn-sm" href={`/api/assets/${asset.id}/download?fmt=sheet`}>Sprite Sheet</a>}
          {files.webp && <a className="btn btn-sm" href={`/api/assets/${asset.id}/download?fmt=webp`}>WebP</a>}
          {files.tres && <a className="btn btn-sm" href={`/api/assets/${asset.id}/download?fmt=tres`}>Godot .tres</a>}
          <a className="btn btn-sm" href={`/api/assets/${asset.id}/download?fmt=zip`}>ZIP</a>
        </div>
      </div>

      {ACTIONS.some((a) => a.kinds.includes(asset.kind)) && (
        <div>
          <div className="eyebrow mb-1.5">继续加工</div>
          <div className="grid grid-cols-2 gap-1.5">
            {ACTIONS.filter((a) => a.kinds.includes(asset.kind)).map((a) => (
              <button key={a.cap} className="btn btn-sm !justify-start" onClick={() => onAction(a.cap, { [a.key]: asset.id })}>
                <CapIcon name={a.icon} size={14} />{a.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
