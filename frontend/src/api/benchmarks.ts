import client from './client'
import type { BenchmarkJob, ReportDetail, ReportSummary } from '@/types'

export interface CreateBenchmarkParams {
  model: string
  version: string
  mode: string
  concurrency: number
  duration: number
  payload: string
  protocol: string
}

export function createBenchmark(params: CreateBenchmarkParams) {
  return client.post<{ job_id: string }>('/ui/api/benchmarks', null, { params })
}

export function getBenchmarkStatus(jobId: string) {
  return client.get<BenchmarkJob>(`/ui/api/benchmarks/${jobId}/status`)
}

export function listReports(model?: string) {
  return client.get<{ reports: ReportSummary[] }>('/ui/api/reports', { params: model ? { model } : undefined })
}

export function getReport(id: string) {
  return client.get<ReportDetail>(`/ui/api/reports/${id}`)
}

export function deleteReport(id: string) {
  return client.delete<{ success: boolean }>(`/ui/api/reports/${id}`)
}

export function cleanupReports() {
  return client.post<{ removed: number }>('/ui/api/reports/cleanup')
}
