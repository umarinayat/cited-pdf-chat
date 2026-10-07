import { useEffect, useState } from 'react'
import { api } from '../api'
import type { EvalReport, EvalRun } from '../types'

export default function AccuracyPanel() {
  const [report, setReport] = useState<EvalReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.evalReport().then(setReport).catch((e) => setError((e as Error).message))
  }, [])

  return (
    <div className="thin-scroll h-full overflow-y-auto px-4 py-4 sm:px-5">
      <h2 className="text-base font-semibold text-slate-900">How accurate is it?</h2>
      <p className="mt-1 text-sm leading-relaxed text-slate-600">
        A fixed set of {report?.runs[0]?.items.length ?? 23} questions is asked of the sample report, once as a normal
        PDF and once as a scanned copy that has to be read with OCR. Some questions have no answer in the document, to
        check that it says so instead of guessing. Re-run any time with <code className="rounded bg-slate-100 px-1">eval/run_eval.py</code>.
      </p>
      {error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {report && !report.runs.length && <p className="mt-4 text-sm text-slate-500">No accuracy run yet.</p>}
      {report?.runs.length ? (
        <p className="mt-3 text-xs text-slate-500">
          {report.mode === 'llm' ? `Answers by ${report.provider === 'gemini' ? 'Gemini' : report.provider === 'anthropic' ? 'Claude' : 'OpenAI'} · ${report.model}` : 'No-key mode: passages only, no written answers'}
          {report.generated_at ? ` · run ${new Date(report.generated_at).toLocaleString()}` : ''}
        </p>
      ) : null}
      <div className="mt-4 space-y-6">
        {report?.runs.map((r) => <Run key={r.doc} run={r} />)}
      </div>
    </div>
  )
}

function Run({ run }: { run: EvalRun }) {
  const s = run.summary
  const [open, setOpen] = useState(false)
  const stat = (label: string, value: number | null, hint: string) => (
    <div className="rounded-xl border border-slate-200 bg-white p-3" title={hint}>
      <div className="text-xl font-semibold tabular-nums text-slate-900">{value === null ? '–' : `${Math.round(value)}%`}</div>
      <div className="mt-0.5 text-xs leading-snug text-slate-500">{label}</div>
    </div>
  )
  return (
    <section>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">{run.kind}</h3>
        <span className="text-xs text-slate-500">
          {s.correct}/{s.questions} correct · avg {(s.avg_ms / 1000).toFixed(1)} s
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stat('Correct answers', s.answerable_accuracy, 'Answerable questions whose answer contains the right facts')}
        {stat('Says "not in the document" when it isn\'t', s.refusal_accuracy, 'Unanswerable questions correctly declined')}
        {stat('Right page found by search', s.retrieval_hit_rate, 'The page with the answer was among the passages searched')}
        {stat('Citations on the right page', s.citation_page_precision, 'Verified citations that point at the page holding the answer')}
      </div>
      <button onClick={() => setOpen((o) => !o)} className="mt-2 text-xs font-medium text-blue-700 hover:underline">
        {open ? 'Hide' : 'Show'} every question
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {run.items.map((i) => (
            <li key={i.q} className="flex gap-3 px-3 py-2 text-sm">
              <span className={`mt-0.5 shrink-0 font-bold ${i.correct ? 'text-emerald-600' : 'text-rose-600'}`}>
                {i.correct ? '✓' : '✗'}
              </span>
              <div className="min-w-0">
                <div className="text-slate-800">
                  {i.q}
                  {!i.answerable && <span className="ml-1 rounded bg-slate-100 px-1 text-[10px] text-slate-500">not in doc</span>}
                </div>
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{i.found ? i.answer : 'Answered: not in the document'}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
