import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import AccuracyPanel from './components/AccuracyPanel'
import ChatPanel from './components/ChatPanel'
import NumbersPanel from './components/NumbersPanel'
import PdfViewer from './components/PdfViewer'
import type { Answer, DocMeta, Focus, Health, Highlight, NumberItem, Passage } from './types'

type Tab = 'ask' | 'numbers' | 'accuracy'
const UPLOADS_KEY = 'cpc-uploads'

function loadUploads(): { id: string; name: string }[] {
  try {
    return JSON.parse(localStorage.getItem(UPLOADS_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveUploads(list: { id: string; name: string }[]) {
  try {
    localStorage.setItem(UPLOADS_KEY, JSON.stringify(list.slice(0, 20)))
  } catch {
    /* private mode */
  }
}

const params = new URLSearchParams(window.location.search)

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [samples, setSamples] = useState<DocMeta[]>([])
  const [uploads, setUploads] = useState(loadUploads)
  const [docId, setDocId] = useState<string | null>(params.get('doc'))
  const [doc, setDoc] = useState<DocMeta | null>(null)
  const [tab, setTab] = useState<Tab>((params.get('tab') as Tab) || 'ask')
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const [focus, setFocus] = useState<Focus | null>(null)
  const [activeCite, setActiveCite] = useState<{ msg: number; n: number } | null>(null)
  const [activeNumber, setActiveNumber] = useState<number | null>(null)
  const [mobileView, setMobileView] = useState<'panel' | 'doc'>('panel')
  const [split, setSplit] = useState(42)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const main = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    let tries = 0
    const loadSamples = () =>
      api.samples().then((s) => {
        setSamples(s)
        if (!s.length && tries++ < 20) setTimeout(loadSamples, 3000) // samples are still being prepared
      })
    void loadSamples()
  }, [])

  useEffect(() => {
    if (!docId && samples.length) setDocId(samples[0].id)
  }, [docId, samples])

  useEffect(() => {
    if (!docId) return
    setHighlights([])
    setFocus(null)
    setActiveCite(null)
    setActiveNumber(null)
    api
      .doc(docId)
      .then(setDoc)
      .catch(() => {
        setNotice('That document is no longer available.')
        setUploads((u) => {
          const next = u.filter((x) => x.id !== docId)
          saveUploads(next)
          return next
        })
        setDocId(samples[0]?.id ?? null)
      })
    const url = new URL(window.location.href)
    url.searchParams.set('doc', docId)
    url.searchParams.delete('q')
    window.history.replaceState(null, '', url)
  }, [docId])

  const showCitation = useCallback((msg: number, answer: Answer, n: number, fromClick = true) => {
    setActiveCite({ msg, n })
    setActiveNumber(null)
    setHighlights(
      answer.citations
        .filter((c) => c.status !== 'unverified' && c.rects.length)
        .map((c) => ({ key: `c${msg}-${c.n}`, page: c.page, rects: c.rects, tone: c.n === n ? 'active' : 'related', label: String(c.n) })),
    )
    const c = answer.citations.find((x) => x.n === n)
    if (c) setFocus({ page: c.page, rect: c.rects[0], nonce: Date.now() })
    if (fromClick) setMobileView('doc') // on phones, only a tap on a citation switches to the page
  }, [])

  const showPassage = useCallback((p: Passage) => {
    setActiveCite(null)
    setHighlights([{ key: `p${p.page}-${p.text.length}`, page: p.page, rects: p.rects, tone: 'passage' }])
    setFocus({ page: p.page, rect: p.rects[0], nonce: Date.now() })
  }, [])

  const showNumber = useCallback((n: NumberItem) => {
    setActiveNumber(n.id)
    setActiveCite(null)
    setHighlights([{ key: `n${n.id}`, page: n.page, rects: n.rects, tone: 'number' }])
    setFocus({ page: n.page, rect: n.rects[0], nonce: Date.now() })
    setMobileView('doc')
  }, [])

  const onUpload = async (file: File) => {
    const limit = (health?.max_upload_mb ?? 15) * 1024 * 1024
    if (file.size > limit) {
      setNotice(`PDFs up to ${health?.max_upload_mb ?? 15} MB, please.`)
      return
    }
    setUploading(true)
    setNotice(null)
    try {
      const meta = await api.upload(file)
      const next = [{ id: meta.id, name: meta.name }, ...uploads.filter((u) => u.id !== meta.id)]
      setUploads(next)
      saveUploads(next)
      setDocId(meta.id)
      setTab('ask')
    } catch (e) {
      setNotice((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  const startDrag = (e: React.PointerEvent) => {
    e.preventDefault()
    const box = main.current?.getBoundingClientRect()
    if (!box) return
    const move = (ev: PointerEvent) => setSplit(Math.min(65, Math.max(28, ((ev.clientX - box.left) / box.width) * 100)))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <Logo />
          <div className="leading-tight">
            <h1 className="text-[15px] font-semibold text-slate-900">Cited PDF Chat</h1>
            <p className="hidden text-xs text-slate-500 sm:block">Answers you can check, highlighted in the PDF</p>
          </div>
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <select
            value={docId ?? ''}
            onChange={(e) => setDocId(e.target.value)}
            className="min-w-0 max-w-xs flex-1 truncate rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-blue-500"
            aria-label="Document"
          >
            {!samples.length && !uploads.length && <option value="">Preparing sample documents…</option>}
            {!!samples.length && (
              <optgroup label="Samples">
                {samples.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.kind})
                  </option>
                ))}
              </optgroup>
            )}
            {!!uploads.length && (
              <optgroup label="Your uploads">
                {uploads.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) void onUpload(f)
            }}
          />
          <button
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
            className="shrink-0 rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-slate-700 disabled:bg-slate-400"
          >
            {uploading ? 'Reading PDF…' : 'Upload PDF'}
          </button>
        </div>
        <StatusPill health={health} />
      </header>

      {notice && (
        <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          <span>{notice}</span>
          <button onClick={() => setNotice(null)} className="text-amber-700 hover:text-amber-900" aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      {uploading && (
        <div className="border-b border-blue-100 bg-blue-50 px-4 py-2 text-sm text-blue-800">
          Reading your PDF: extracting text, running OCR on scanned pages and indexing it. Scanned pages take a few seconds each.
          {!!health?.upload_ttl_hours && ` Uploaded PDFs are deleted after ${health.upload_ttl_hours} hours.`}
        </div>
      )}

      <div className="flex border-b border-slate-200 bg-white md:hidden">
        {(['panel', 'doc'] as const).map((v) => (
          <button
            key={v}
            onClick={() => setMobileView(v)}
            className={`flex-1 py-2 text-sm font-medium ${mobileView === v ? 'border-b-2 border-blue-600 text-blue-700' : 'text-slate-500'}`}
          >
            {v === 'panel' ? 'Ask & explore' : 'Document'}
          </button>
        ))}
      </div>

      <div ref={main} className="flex min-h-0 flex-1">
        <section
          className={`min-h-0 flex-col bg-slate-50 md:flex md:w-auto md:shrink-0 md:[flex-basis:var(--split)] ${mobileView === 'panel' ? 'flex w-full' : 'hidden'}`}
          style={{ ['--split' as string]: `${split}%` }}
        >
          <nav className="flex items-center gap-1 border-b border-slate-200 bg-white px-3 pt-2">
            {(
              [
                ['ask', 'Ask'],
                ['numbers', `Numbers${doc ? ` (${doc.numbers})` : ''}`],
                ['accuracy', 'Accuracy'],
              ] as [Tab, string][]
            ).map(([t, label]) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`-mb-px rounded-t-lg border px-3 py-1.5 text-sm font-medium transition ${
                  tab === t ? 'border-slate-200 border-b-white bg-white text-slate-900' : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                {label}
              </button>
            ))}
            {doc && (
              <span className="ml-auto hidden truncate pb-1 text-[11px] text-slate-500 lg:block">
                {doc.pages} pages{doc.ocr_pages ? ` · ${doc.ocr_pages} read by OCR` : ''}
              </span>
            )}
          </nav>
          <div className="min-h-0 flex-1">
            {doc && tab === 'ask' && (
              <ChatPanel
                doc={doc}
                health={health}
                autoAsk={params.get('q')}
                active={activeCite}
                onCite={showCitation}
                onPassage={showPassage}
              />
            )}
            {doc && tab === 'numbers' && <NumbersPanel doc={doc} activeId={activeNumber} onSelect={showNumber} />}
            {tab === 'accuracy' && <AccuracyPanel />}
            {!doc && tab !== 'accuracy' && <p className="p-5 text-sm text-slate-500">Loading document…</p>}
          </div>
        </section>
        <div
          onPointerDown={startDrag}
          className="hidden w-1.5 shrink-0 cursor-col-resize bg-slate-200 transition hover:bg-blue-400 md:block"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize panels"
        />
        <section className={`min-h-0 min-w-0 flex-1 ${mobileView === 'doc' ? 'block' : 'hidden'} md:block`}>
          {docId ? (
            <PdfViewer url={api.fileUrl(docId)} highlights={highlights} focus={focus} />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">Preparing documents…</div>
          )}
        </section>
      </div>
    </div>
  )
}

function StatusPill({ health }: { health: Health | null }) {
  if (!health) return null
  const llm = health.mode === 'llm'
  return (
    <span
      className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium sm:inline-flex ${
        llm ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
      }`}
      title={health.embeddings ? 'Hybrid search: keywords + local embeddings' : 'Keyword search'}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${llm ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      {llm ? `${health.provider === 'gemini' ? 'Gemini' : health.provider === 'anthropic' ? 'Claude' : 'OpenAI'} · ${health.model}` : 'No-key mode'}
    </span>
  )
}

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#1d4ed8" />
      <path d="M9 7.5h10l4 4V24.5H9z" fill="#fff" />
      <path d="M19 7.5v4h4" fill="#bfdbfe" />
      <rect x="11.5" y="14.5" width="9" height="3" rx="1" fill="#facc15" />
      <rect x="11.5" y="19.5" width="6" height="1.6" rx=".8" fill="#cbd5e1" />
    </svg>
  )
}
