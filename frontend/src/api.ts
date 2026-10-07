import type { Answer, DocMeta, EvalReport, Health, NumberItem } from './types'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* not JSON */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => call<Health>('/api/health'),
  samples: () => call<DocMeta[]>('/api/samples'),
  doc: (id: string) => call<DocMeta>(`/api/docs/${id}`),
  numbers: (id: string) => call<NumberItem[]>(`/api/docs/${id}/numbers`),
  evalReport: () => call<EvalReport>('/api/eval'),
  fileUrl: (id: string) => `/api/docs/${id}/file`,
  ask: (id: string, question: string) =>
    call<Answer>(`/api/docs/${id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return call<DocMeta>('/api/docs', { method: 'POST', body: form })
  },
}
