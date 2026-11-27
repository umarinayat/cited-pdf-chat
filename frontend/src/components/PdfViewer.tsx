import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Focus, Highlight, Tone } from '../types'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const ZOOMS = [0.6, 0.8, 1, 1.25, 1.5, 2]

const TONE: Record<Tone, string> = {
  active: 'bg-yellow-300/55 ring-2 ring-yellow-500 hl-active',
  related: 'bg-yellow-200/45',
  number: 'bg-sky-300/45 ring-2 ring-sky-500 hl-active',
  passage: 'bg-violet-200/50 ring-1 ring-violet-400',
}

interface Props {
  url: string
  highlights: Highlight[]
  focus: Focus | null
}

export default function PdfViewer({ url, highlights, focus }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const pageEls = useRef<(HTMLDivElement | null)[]>([])
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [sizes, setSizes] = useState<{ w: number; h: number }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [width, setWidth] = useState(0)
  const [zoomIdx, setZoomIdx] = useState(2)
  const [current, setCurrent] = useState(1)

  useEffect(() => {
    let cancelled = false
    setPdf(null)
    setSizes([])
    setError(null)
    // Uploaded PDFs are untrusted. pdfjs-dist 6.2.108+ fixes the font-code bug (GHSA-hq66-cqwq-w95j) and this viewer
    // never runs a PDF's own scripts (no scripting manager is set up).
    const task = pdfjs.getDocument({ url })
    task.promise
      .then(async (doc) => {
        const s = []
        for (let i = 1; i <= doc.numPages; i++) {
          const v = (await doc.getPage(i)).getViewport({ scale: 1 })
          s.push({ w: v.width, h: v.height })
        }
        if (!cancelled) {
          setPdf(doc)
          setSizes(s)
        }
      })
      .catch((e) => !cancelled && setError(String(e?.message ?? e)))
    return () => {
      cancelled = true
      void task.destroy()
    }
  }, [url])

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const fit = (i: number) => (sizes[i] ? Math.max(0.3, (width - 40) / sizes[i].w) : 1)
  const scale = (i: number) => fit(i) * ZOOMS[zoomIdx]

  // Jump to the focused highlight.
  useEffect(() => {
    if (!focus || !sizes.length) return
    const el = pageEls.current[focus.page]
    const box = scroller.current
    if (!el || !box) return
    const y = el.offsetTop + (focus.rect ? focus.rect[1] * scale(focus.page) : 0)
    const top = Math.max(0, y - box.clientHeight * 0.3)
    const from = box.scrollTop
    box.scrollTo({ top, behavior: 'smooth' })
    // Background or throttled tabs don't animate smooth scrolling: jump if it hasn't moved.
    const t = window.setTimeout(() => {
      if (Math.abs(box.scrollTop - from) < 2 && Math.abs(top - from) > 2) box.scrollTop = top
    }, 400)
    return () => window.clearTimeout(t)
  }, [focus?.nonce, sizes.length, width > 0]) // also when the viewer is shown again (mobile tabs)

  const onScroll = () => {
    const box = scroller.current
    if (!box) return
    const mid = box.scrollTop + box.clientHeight / 3
    let page = 1
    pageEls.current.forEach((el, i) => {
      if (el && el.offsetTop <= mid) page = i + 1
    })
    setCurrent(page)
  }

  const byPage = useMemo(() => {
    const m = new Map<number, Highlight[]>()
    for (const h of highlights) m.set(h.page, [...(m.get(h.page) ?? []), h])
    return m
  }, [highlights])

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-200/70">
      <div className="flex items-center justify-between gap-2 border-b border-slate-300/70 bg-white/80 px-3 py-1.5 text-xs text-slate-600 backdrop-blur">
        <span className="tabular-nums">
          {sizes.length ? `Page ${current} of ${sizes.length}` : 'Loading PDF…'}
        </span>
        <div className="flex items-center gap-1">
          <ToolButton label="Zoom out" onClick={() => setZoomIdx((z) => Math.max(0, z - 1))} disabled={zoomIdx === 0}>
            −
          </ToolButton>
          <button
            className="rounded px-2 py-1 tabular-nums hover:bg-slate-100"
            onClick={() => setZoomIdx(2)}
            title="Fit to width"
          >
            {Math.round(ZOOMS[zoomIdx] * 100)}%
          </button>
          <ToolButton
            label="Zoom in"
            onClick={() => setZoomIdx((z) => Math.min(ZOOMS.length - 1, z + 1))}
            disabled={zoomIdx === ZOOMS.length - 1}
          >
            +
          </ToolButton>
        </div>
      </div>
      <div ref={scroller} onScroll={onScroll} className="thin-scroll relative min-h-0 flex-1 overflow-auto px-5 py-5">
        {error && <p className="mx-auto max-w-sm rounded-lg bg-red-50 p-4 text-sm text-red-700">Couldn't open this PDF: {error}</p>}
        {pdf &&
          sizes.map((s, i) => (
            <div
              key={`${url}-${i}`}
              ref={(el) => {
                pageEls.current[i] = el
              }}
              className="mx-auto mb-5"
              style={{ width: s.w * scale(i) }}
            >
              <PageCanvas pdf={pdf} index={i} scale={scale(i)} size={s} highlights={byPage.get(i) ?? []} />
            </div>
          ))}
      </div>
    </div>
  )
}

function ToolButton(props: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      aria-label={props.label}
      title={props.label}
      onClick={props.onClick}
      disabled={props.disabled}
      className="h-7 w-7 rounded text-base leading-none hover:bg-slate-100 disabled:opacity-30"
    >
      {props.children}
    </button>
  )
}

interface PageProps {
  pdf: PDFDocumentProxy
  index: number
  scale: number
  size: { w: number; h: number }
  highlights: Highlight[]
}

function PageCanvas({ pdf, index, scale, size, highlights }: PageProps) {
  const wrap = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setVisible(true), { rootMargin: '600px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    if (!visible || !canvas.current) return
    let task: RenderTask | null = null
    let cancelled = false
    pdf.getPage(index + 1).then((page) => {
      if (cancelled || !canvas.current) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const viewport = page.getViewport({ scale: scale * dpr })
      const c = canvas.current
      c.width = Math.floor(viewport.width)
      c.height = Math.floor(viewport.height)
      task = page.render({ canvas: c, viewport })
      task.promise.catch(() => {})
    })
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [visible, pdf, index, scale])

  return (
    <div
      ref={wrap}
      className="relative overflow-hidden rounded-[3px] bg-white shadow-[0_1px_3px_rgba(15,23,42,0.12),0_8px_24px_-12px_rgba(15,23,42,0.25)]"
      style={{ width: size.w * scale, height: size.h * scale }}
    >
      <canvas ref={canvas} className="absolute inset-0 h-full w-full" />
      {highlights.map((h) =>
        h.rects.map((r, j) => (
          <div
            key={`${h.key}-${j}`}
            className={`pointer-events-none absolute rounded-[2px] mix-blend-multiply ${TONE[h.tone]}`}
            style={{
              left: r[0] * scale - 2,
              top: r[1] * scale - 1,
              width: (r[2] - r[0]) * scale + 4,
              height: (r[3] - r[1]) * scale + 2,
            }}
          />
        )),
      )}
      {highlights
        .filter((h) => h.label && h.rects.length)
        .map((h) => (
          <span
            key={`${h.key}-label`}
            className={`pointer-events-none absolute -translate-x-full rounded px-1 text-[10px] font-semibold text-white shadow ${
              h.tone === 'number' ? 'bg-sky-600' : 'bg-amber-600'
            }`}
            style={{ left: h.rects[0][0] * scale - 4, top: h.rects[0][1] * scale - 1 }}
          >
            {h.label}
          </span>
        ))}
    </div>
  )
}
