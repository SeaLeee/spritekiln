import {
  Book, Box, Boxes, Copy, Eraser, Film, Grid3x3, Image, KeyRound, Layers, LayoutPanelTop, Mountain, Palette, Pencil,
  Repeat, RotateCw, Ruler, Scissors, Sparkles, Square, Video, Wand2, Cuboid, FileText, Shapes,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Asset } from '../api'

const ICONS: Record<string, any> = {
  grid: Grid3x3, image: Image, ruler: Ruler, sparkles: Sparkles, wand: Wand2, rotate: RotateCw, layout: LayoutPanelTop,
  copy: Copy, eraser: Eraser, pencil: Pencil, layers: Layers, scissors: Scissors, palette: Palette, square: Square,
  box: Box, mountain: Mountain, repeat: Repeat, film: Film, keyframes: KeyRound, video: Video, cube: Cuboid,
  cubes: Boxes, book: Book,
}

export function CapIcon({ name, size = 16 }: { name: string; size?: number }) {
  const I = ICONS[name] || Shapes
  return <I size={size} strokeWidth={1.8} aria-hidden />
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 select-none">
      <img src="/favicon.svg" alt="" width={compact ? 28 : 30} height={compact ? 28 : 30} className="pixelated rounded-[6px]" />
      {!compact && (
        <span className="font-display text-[1.15rem] leading-none tracking-wide">
          SpriteKiln <span className="text-ink-soft text-[.8rem] font-sans">像素窑</span>
        </span>
      )}
    </span>
  )
}

export function isPixel(a: Asset) {
  return !!a.meta?.pixel || (a.width > 0 && a.width <= 256 && a.height <= 256)
}

export function AssetThumb({ asset, size = 140, className = '' }: { asset: Asset; size?: number; className?: string }) {
  if (asset.kind === 'model3d') {
    const input = asset.meta?.file_urls?.input
    return (
      <div className={`checker grid place-items-center rounded-md ${className}`} style={{ width: size, height: size }}>
        {input ? <img src={input} alt="" className="max-w-full max-h-full object-contain opacity-90" /> : <Cuboid size={size / 3} />}
        <span className="absolute bottom-1 right-1 chip !text-[10px] !py-0">GLB</span>
      </div>
    )
  }
  if (asset.kind === 'doc') {
    return (
      <div className={`grid place-items-center rounded-md bg-white ${className}`} style={{ width: size, height: size * 0.7 }}>
        <FileText size={size / 4} className="text-ink-soft" />
      </div>
    )
  }
  if (asset.kind === 'video') {
    return <video src={asset.url} muted loop autoPlay playsInline className={`rounded-md bg-black ${className}`} style={{ width: size }} />
  }
  const px = isPixel(asset)
  const w = asset.width || 64
  const h = asset.height || 64
  const scale = px ? Math.max(1, Math.floor(Math.min(size / w, size / h))) : Math.min(size / w, size / h)
  return (
    <div className={`checker grid place-items-center rounded-md overflow-hidden ${className}`} style={{ width: size, height: size }}>
      <img
        src={asset.url}
        alt={asset.name}
        draggable={false}
        className={px ? 'pixelated' : ''}
        style={{ width: Math.min(w * scale, size), height: 'auto', maxHeight: size, objectFit: 'contain' }}
      />
    </div>
  )
}

export function Modal({ open, onClose, title, children, wide = false }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4" onClick={onClose} role="dialog" aria-modal>
      <div className={`panel shadow-xl w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} max-h-[88vh] overflow-auto scroll-thin`}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h2 className="font-semibold">{title}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <div className="px-5 pb-5">{children}</div>
      </div>
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="text-center py-10 px-6 text-ink-soft">
      <div className="font-display text-ink text-lg mb-1">{title}</div>
      <div className="text-sm">{children}</div>
    </div>
  )
}
