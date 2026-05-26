export interface ModelInfo {
  name: string
  status: string
  version: string
  model_type: string
  active_version: string | null
  workers: number
  qps: number
  p99_ms: number
  queue_depth: number
  stream: boolean
  bidirectional: boolean
}

export interface VersionInfo {
  version: string
  status: string
  model_type: string
  workers: number
}

export interface ModelMetrics {
  qps?: number
  p99_ms?: number
  queue_depth?: number
  [key: string]: unknown
}

export interface BenchmarkJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  report_id?: string
  error?: string
}

export interface ReportSummary {
  id: string
  model: string
  version: string
  mode: string
  concurrency: number
  duration: number
  created_at: string
}

export interface ReportDetail extends ReportSummary {
  qps: number
  avg_latency_ms: number
  p50_ms: number
  p90_ms: number
  p95_ms: number
  p99_ms: number
  error_rate: number
  latency_histogram?: { buckets: number[]; counts: number[] }
}

export interface ServerConfig {
  http_port: number
  grpc_port: number
  metrics_port: number
  host: string
  accelerator: string
  devices: string | number
  workers_per_device: number
  timeout: number
  log_level: string
  num_api_servers: number
  http_workers: number | null
  transport: string
}

export interface FullConfig {
  server: ServerConfig
  grpc: { enabled: boolean; max_workers: number }
  metrics: { enabled: boolean }
  logging: Record<string, unknown>
  model_repository: Record<string, unknown>
  webui: { enabled: boolean; report_retention_days: number }
  load_models: string[]
}
