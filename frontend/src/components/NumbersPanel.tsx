import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { DocMeta, NumberItem } from '../types'

type SortKey = 'page' | 'value' | 'label'

export default function NumbersPanel({ doc, activeId, onSelect }: { doc: DocMeta; activeId: number | null; onSelect: (n: NumberItem) => void }) {
  const [items, setItems] = useState<NumberItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'page', dir: 1 })

  useEffect(() => {
    setItems(null)
    setError(null)
    api.numbers(doc.id).then(setItems).catch((e) => setError((e as Error).message))
  }, [doc.id])

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = (items ?? []).filter(
      (n) => !q || n.value.toLowerCase().includes(q) || n.label.toLowerCase().includes(q) || n.context.toLowerCase().includes(q),
    )
    const cmp = (a: NumberItem, b: NumberItem) => {
      if (sort.key === 'value') return a.number - b.number
      if (sort.key === 'label') return a.label.localeCompare(b.label)
      return a.page - b.page || a.id - b.id
    }
    return [...list].sort((a, b) => cmp(a, b) * sort.dir)
  }, [items, query, sort])

  const exportCsv = () => {
    const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`
    const lines = [['Value', 'Number', 'Unit', 'What it measures', 'Page', 'Context'].map(esc).join(',')]
    for (const n of rows) lines.push([n.value, n.number, n.unit, n.label, n.page + 1, n.context].map(esc).join(','))
    const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${doc.name.replace(/[^\w-]+/g, '_')}-numbers.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const header = (key: SortKey, label: string, className = '') => (
    <th className={`px-3 py-2 font-medium ${className}`}>
      <button
        className="inline-flex items-center gap-1 hover:text-slate-900"
        onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))}
      >
        {label}
        <span className="text-[10px] text-slate-400">{sort.key === key ? (sort.dir === 1 ? '▲' : '▼') : ''}</span>
      </button>
    </th>
  )

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-slate-200 bg-white px-4 py-3">
        <p className="text-sm text-slate-600">
          Every figure in the document, found without AI so none are missed. Click a row to see it on the page.
        </p>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter, e.g. revenue or %"
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          />
          <button
            onClick={exportCsv}
            disabled={!rows.length}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            Export CSV
          </button>
        </div>
      </div>
      <div className="thin-scroll min-h-0 flex-1 overflow-auto">
        {error && <p className="m-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {!items && !error && <p className="p-4 text-sm text-slate-500">Loading…</p>}
        {items && (
          <table className="w-full table-fixed text-left text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs text-slate-500 shadow-[0_1px_0_#e2e8f0]">
              <tr>
                {header('value', 'Value', 'w-28')}
                {header('label', 'What it measures')}
                {header('page', 'Page', 'w-16')}
              </tr>
            </thead>
            <tbody>
              {rows.map((n) => (
                <tr
                  key={n.id}
                  onClick={() => onSelect(n)}
                  className={`cursor-pointer border-b border-slate-100 align-top transition ${
                    activeId === n.id ? 'bg-sky-50' : 'bg-white hover:bg-slate-50'
                  }`}
                >
                  <td className="px-3 py-2 font-semibold tabular-nums text-slate-900">{n.value}</td>
                  <td className="px-3 py-2">
                    <div className="text-slate-800">{n.label || <span className="text-slate-400">—</span>}</div>
                    <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{n.context}</div>
                  </td>
                  <td className="px-3 py-2 tabular-nums text-slate-500">{n.page + 1}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {items && !rows.length && <p className="p-4 text-sm text-slate-500">No figures match that filter.</p>}
      </div>
      {items && (
        <div className="border-t border-slate-200 bg-white px-4 py-2 text-xs text-slate-500">
          {rows.length} of {items.length} figures
        </div>
      )}
    </div>
  )
}
