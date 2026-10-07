import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Answer, Citation, DocMeta, Health, Passage } from '../types'

const SAMPLE_QUESTIONS = [
  'How many visits did the library have in 2025?',
  'How much did the Eastside Branch cost, and who helped pay for it?',
  'How long can I keep a DVD?',
  'Which service measure went down last year?',
  'What is the director’s salary?',
  '图书馆提供哪些中文服务？',
]

interface Msg {
  id: number
  q: string
  answer?: Answer
  error?: string
}

interface Props {
  doc: DocMeta
  health: Health | null
  autoAsk?: string | null
  active: { msg: number; n: number } | null
  onCite: (msg: number, answer: Answer, n: number, fromClick?: boolean) => void
  onPassage: (p: Passage) => void
}

export default function ChatPanel({ doc, health, autoAsk, active, onCite, onPassage }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)
  const asked = useRef<string | null>(null)

  useEffect(() => {
    setMsgs([])
  }, [doc.id])
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [msgs])

  const ask = async (q: string) => {
    const question = q.trim()
    if (!question || busy) return
    const id = Date.now()
    setMsgs((m) => [...m, { id, q: question }])
    setInput('')
    setBusy(true)
    try {
      const answer = await api.ask(doc.id, question)
      setMsgs((m) => m.map((x) => (x.id === id ? { ...x, answer } : x)))
      const first = answer.citations.find((c) => c.status !== 'unverified')
      if (first) onCite(id, answer, first.n, false)
      else if (answer.closest?.length) onPassage(answer.closest[0])
    } catch (e) {
      setMsgs((m) => m.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (autoAsk && asked.current !== `${doc.id}:${autoAsk}`) {
      asked.current = `${doc.id}:${autoAsk}`
      void ask(autoAsk)
    }
  }, [autoAsk, doc.id])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="thin-scroll min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4 sm:px-5">
        {msgs.length === 0 && (
          <div className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-sm font-medium text-slate-900">Ask anything about this PDF.</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">
                Every sentence of the answer is linked to the exact text it came from, and that text is highlighted in
                the document. Quotes are checked against the PDF itself, so a made-up citation can't slip through.
              </p>
              {health?.mode === 'extractive' && (
                <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
                  No AI model is connected right now, so you'll get the passages that best match your question
                  instead of a written answer.
                </p>
              )}
            </div>
            {doc.sample && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Try one</p>
                <div className="flex flex-wrap gap-2">
                  {SAMPLE_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => void ask(q)}
                      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-left text-sm text-slate-700 shadow-sm transition hover:border-blue-300 hover:text-blue-700"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className="space-y-3">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-blue-600 px-4 py-2 text-sm text-white shadow-sm">
              {m.q}
            </div>
            {m.error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{m.error}</p>}
            {!m.answer && !m.error && <Thinking />}
            {m.answer && (
              <AnswerCard
                answer={m.answer}
                activeN={active?.msg === m.id ? active.n : null}
                onCite={(n) => onCite(m.id, m.answer!, n)}
                onPassage={onPassage}
              />
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void ask(input)
        }}
        className="border-t border-slate-200 bg-white p-3"
      >
        <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 shadow-sm focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void ask(input)
              }
            }}
            rows={1}
            maxLength={500}
            placeholder="Ask a question about the document…"
            className="max-h-32 min-h-[24px] flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:bg-slate-300"
          >
            Ask
          </button>
        </div>
      </form>
    </div>
  )
}

function Thinking() {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="inline-flex gap-1">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" style={{ animationDelay: `${i * 120}ms` }} />
        ))}
      </span>
      Searching the document and checking quotes…
    </div>
  )
}

const CHIP: Record<Citation['label'], string> = {
  high: 'bg-emerald-50 text-emerald-700 ring-emerald-300 hover:bg-emerald-100',
  medium: 'bg-amber-50 text-amber-800 ring-amber-300 hover:bg-amber-100',
  low: 'bg-rose-50 text-rose-700 ring-rose-300 hover:bg-rose-100',
}

function AnswerCard(props: { answer: Answer; activeN: number | null; onCite: (n: number) => void; onPassage: (p: Passage) => void }) {
  const { answer, activeN, onCite, onPassage } = props
  const cites = new Map(answer.citations.map((c) => [c.n, c]))
  const verified = answer.citations.filter((c) => c.status === 'verified').length

  return (
    <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 shadow-sm">
      {answer.note && <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{answer.note}</p>}
      {!answer.found ? (
        <div>
          <p className="text-sm font-medium text-slate-900">This isn't in the document.</p>
          <p className="mt-1 text-sm text-slate-600">I couldn't find text in the PDF that answers this, so I won't guess.</p>
          {!!answer.closest?.length && (
            <div className="mt-3 space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Closest passages</p>
              {answer.closest.map((p, i) => (
                <button
                  key={i}
                  onClick={() => onPassage(p)}
                  className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-xs leading-relaxed text-slate-600 hover:border-violet-300 hover:bg-violet-50"
                >
                  <span className="mr-1 font-semibold text-violet-700">p.{p.page + 1}</span>
                  {p.text}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className={answer.mode === 'extractive' ? 'space-y-2' : ''}>
          {answer.mode === 'extractive' && (
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Best-matching passages</p>
          )}
          <p className={`text-[15px] leading-7 text-slate-800 ${answer.mode === 'extractive' ? 'space-y-2' : ''}`}>
            {answer.sentences.map((s, i) => (
              <span key={i} className={answer.mode === 'extractive' ? 'block' : ''}>
                <span
                  className={
                    s.status === 'unsupported'
                      ? 'underline decoration-rose-400 decoration-dotted decoration-2 underline-offset-4'
                      : s.status === 'weak'
                        ? 'underline decoration-amber-400 decoration-dotted decoration-2 underline-offset-4'
                        : ''
                  }
                  title={
                    s.status === 'unsupported'
                      ? 'No quote for this sentence could be found in the PDF'
                      : s.status === 'weak'
                        ? 'The quoted text only partly supports this sentence'
                        : undefined
                  }
                >
                  {s.text}
                </span>
                {s.cites.map((n) => {
                  const c = cites.get(n)
                  return c ? <Chip key={n} c={c} active={activeN === n} onClick={() => onCite(n)} /> : null
                })}{' '}
              </span>
            ))}
          </p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
        <span>
          {answer.mode === 'llm' ? `${prettyProvider(answer.provider)} · ${answer.model}` : 'No-key mode (search only)'}
        </span>
        <span>{(answer.ms / 1000).toFixed(1)} s</span>
        {answer.found && answer.mode === 'llm' && (
          <span>
            {verified}/{answer.citations.length} quotes found word-for-word in the PDF
          </span>
        )}
      </div>
    </div>
  )
}

function Chip({ c, active, onClick }: { c: Citation; active: boolean; onClick: () => void }) {
  const unverified = c.status === 'unverified'
  return (
    <span className="group relative inline-block align-baseline">
      <button
        onClick={onClick}
        disabled={unverified}
        className={`ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1 text-[11px] font-semibold ring-1 transition ${
          unverified ? 'cursor-not-allowed bg-slate-100 text-slate-400 ring-slate-300' : CHIP[c.label]
        } ${active ? 'ring-2 ring-offset-1 ring-offset-white' : ''}`}
        aria-label={`Source ${c.n}, page ${c.page + 1}, ${c.score}% match`}
      >
        {unverified ? '?' : c.n}
      </button>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-72 -translate-x-1/2 rounded-lg bg-slate-900 p-3 text-left text-xs leading-relaxed text-slate-100 shadow-xl group-hover:block">
        <span className="mb-1 flex items-center justify-between font-semibold text-white">
          <span>Page {c.page + 1}</span>
          <span>
            {c.score}% match · {c.label}
          </span>
        </span>
        {unverified ? (
          <span className="block text-rose-300">The model's quote could not be found in the PDF.</span>
        ) : (
          <span className="block italic text-slate-300">“{c.text}”</span>
        )}
        {c.warnings?.map((w) => (
          <span key={w} className="mt-1 block text-amber-300">
            {w}
          </span>
        ))}
      </span>
    </span>
  )
}

function prettyProvider(p: string | null) {
  return p === 'gemini' ? 'Gemini' : p === 'anthropic' ? 'Claude' : p === 'openai' ? 'OpenAI' : 'Model'
}
