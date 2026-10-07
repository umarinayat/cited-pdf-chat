export type Rect = [number, number, number, number]

export interface DocMeta {
  id: string
  name: string
  kind: string
  sample: boolean
  pages: number
  ocr_pages: number
  chunks: number
  numbers: number
  embeddings: boolean
  ingest_ms: number
}

export interface Citation {
  n: number
  page: number
  rects: Rect[]
  text: string
  quote: string
  similarity: number
  support: number
  status: 'verified' | 'partial' | 'unverified'
  score: number
  label: 'high' | 'medium' | 'low'
  warnings?: string[]
}

export interface Sentence {
  text: string
  cites: number[]
  status: 'supported' | 'weak' | 'unsupported' | 'passage'
  unsourced_numbers?: string[]
}

export interface Passage {
  page: number
  text: string
  rects: Rect[]
}

export interface Answer {
  mode: 'llm' | 'extractive'
  provider: string | null
  model: string | null
  found: boolean
  sentences: Sentence[]
  citations: Citation[]
  closest?: Passage[]
  sources: { chunk: number; page: number; score: number }[]
  ms: number
  note?: string
}

export interface NumberItem {
  id: number
  page: number
  value: string
  number: number
  unit: string
  label: string
  context: string
  rects: Rect[]
}

export interface Health {
  mode: 'llm' | 'extractive'
  provider: string | null
  model: string | null
  embeddings: boolean
  max_upload_mb: number
  max_pages: number
  upload_ttl_hours: number
}

export interface EvalItem {
  q: string
  answerable: boolean
  correct: boolean
  found: boolean
  answer: string
  ms: number
  retrieval_hit: boolean | null
  cited_pages: number[]
}

export interface EvalSummary {
  questions: number
  correct: number
  accuracy: number | null
  answerable_accuracy: number | null
  refusal_accuracy: number | null
  retrieval_hit_rate: number | null
  citation_page_precision: number | null
  grounded_sentences: number | null
  avg_ms: number
}

export interface EvalRun {
  doc: string
  doc_name: string
  kind: string
  summary: EvalSummary
  items: EvalItem[]
}

export interface EvalReport {
  generated_at?: string
  mode?: 'llm' | 'extractive'
  provider?: string | null
  model?: string | null
  embeddings?: boolean
  runs: EvalRun[]
}

export type Tone = 'active' | 'related' | 'number' | 'passage'

export interface Highlight {
  key: string
  page: number
  rects: Rect[]
  tone: Tone
  label?: string
}

export interface Focus {
  page: number
  rect?: Rect
  nonce: number
}
