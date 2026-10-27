import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

export type ViewerHandle = { capture: (n: number, size: number) => Promise<Blob[]> }

type Props = { url: string | null; yaw: number; elevation: number; toon: boolean; onStatus?: (s: string) => void }

export const GlbViewer = forwardRef<ViewerHandle, Props>(function GlbViewer({ url, yaw, elevation, toon, onStatus }, ref) {
  const host = useRef<HTMLDivElement>(null)
  const state = useRef<{
    renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls
    pivot: THREE.Group; model: THREE.Object3D | null; originals: Map<THREE.Mesh, THREE.Material | THREE.Material[]>
  } | null>(null)

  useEffect(() => {
    const el = host.current!
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
    renderer.setSize(el.clientWidth, el.clientHeight)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    el.appendChild(renderer.domElement)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(30, el.clientWidth / el.clientHeight, 0.01, 100)
    camera.position.set(0, 0.6, 3)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a0, 2.2))
    const key = new THREE.DirectionalLight(0xffffff, 2.4)
    key.position.set(-2, 3, 2)
    scene.add(key)
    const pivot = new THREE.Group()
    scene.add(pivot)
    state.current = { renderer, scene, camera, controls, pivot, model: null, originals: new Map() }
    let raf = 0
    const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop) }
    loop()
    const ro = new ResizeObserver(() => {
      renderer.setSize(el.clientWidth, el.clientHeight)
      camera.aspect = el.clientWidth / el.clientHeight
      camera.updateProjectionMatrix()
    })
    ro.observe(el)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement) }
  }, [])

  useEffect(() => {
    const s = state.current
    if (!s || !url) return
    onStatus?.('加载模型…')
    new GLTFLoader().load(url, (gltf) => {
      if (s.model) s.pivot.remove(s.model)
      const model = gltf.scene
      const box = new THREE.Box3().setFromObject(model)
      const size = box.getSize(new THREE.Vector3())
      const center = box.getCenter(new THREE.Vector3())
      const k = 1.4 / Math.max(size.x, size.y, size.z)
      model.scale.setScalar(k)
      model.position.set(-center.x * k, -center.y * k, -center.z * k)
      s.originals.clear()
      model.traverse((o) => { if ((o as THREE.Mesh).isMesh) s.originals.set(o as THREE.Mesh, (o as THREE.Mesh).material) })
      s.pivot.add(model)
      s.model = model
      onStatus?.(`已加载 · ${s.originals.size} 个网格`)
    }, undefined, (e) => onStatus?.(`加载失败：${String(e)}`))
  }, [url]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const s = state.current
    if (!s) return
    s.pivot.rotation.y = (yaw * Math.PI) / 180
  }, [yaw])

  useEffect(() => {
    const s = state.current
    if (!s) return
    s.originals.forEach((orig, mesh) => {
      if (!toon) { mesh.material = orig; return }
      const m = (Array.isArray(orig) ? orig[0] : orig) as THREE.MeshStandardMaterial
      mesh.material = new THREE.MeshToonMaterial({ map: m.map ?? null, color: m.color ?? new THREE.Color(0xffffff), transparent: m.transparent, alphaTest: m.alphaTest })
    })
  }, [toon, url])

  useImperativeHandle(ref, () => ({
    async capture(n: number, size: number) {
      const s = state.current!
      const { renderer, camera, scene, controls } = s
      const prevSize = renderer.getSize(new THREE.Vector2())
      const prevPos = camera.position.clone()
      const prevAspect = camera.aspect
      renderer.setPixelRatio(1)
      renderer.setSize(size, size, false)
      camera.aspect = 1
      camera.updateProjectionMatrix()
      const dist = 3.2
      const el = (elevation * Math.PI) / 180
      const blobs: Blob[] = []
      for (let i = 0; i < n; i++) {
        // direction i: 0 = facing camera (S), then clockwise: SE, E, NE, N, NW, W, SW
        const a = (i * 2 * Math.PI) / n
        camera.position.set(Math.sin(a) * dist * Math.cos(el), Math.sin(el) * dist, Math.cos(a) * dist * Math.cos(el))
        camera.lookAt(0, 0, 0)
        renderer.render(scene, camera)
        blobs.push(await new Promise<Blob>((res) => renderer.domElement.toBlob((b) => res(b!), 'image/png')))
      }
      renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
      renderer.setSize(prevSize.x, prevSize.y)
      camera.aspect = prevAspect
      camera.position.copy(prevPos)
      camera.updateProjectionMatrix()
      controls.update()
      return blobs
    },
  }), [elevation])

  return <div ref={host} className="w-full h-full checker rounded-lg overflow-hidden" />
})
