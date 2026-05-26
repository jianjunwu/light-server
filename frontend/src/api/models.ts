import client from './client'
import type { ModelInfo, ModelMetrics, VersionInfo } from '@/types'

export function fetchMetricsSummary() {
  return client.get<{ models: ModelInfo[] }>('/ui/api/metrics/summary')
}

export function fetchModelMetrics(model: string, version: string) {
  return client.get<ModelMetrics>(`/ui/api/metrics/${model}/${version}`)
}

export function loadModel(name: string, version = '1') {
  return client.post<{ success: boolean; models: ModelInfo[] }>(`/ui/api/models/${name}/load`, null, { params: { version } })
}

export function unloadModel(name: string, version?: string) {
  return client.post<{ success: boolean; models: ModelInfo[] }>(`/ui/api/models/${name}/unload`, null, { params: version ? { version } : undefined })
}

export function activateVersion(name: string, version: string) {
  return client.post<{ success: boolean }>(`/ui/api/models/${name}/versions/${version}/activate`)
}

export function reloadModel(name: string, version?: string) {
  return client.post<{ success: boolean; models: ModelInfo[] }>(`/ui/api/models/${name}/reload`, null, { params: version ? { version } : undefined })
}

export function deleteVersion(name: string, version: string) {
  return client.delete<{ success: boolean; models: ModelInfo[] }>(`/ui/api/models/${name}/versions/${version}`)
}

export function listVersions(name: string) {
  return client.get<{ versions: VersionInfo[] }>(`/v2/models/${name}/versions`)
}

export function getVersionConfig(name: string, version: string) {
  return client.get<Record<string, unknown>>(`/ui/api/models/${name}/versions/${version}/config`)
}

export function setVersionConfig(name: string, version: string, data: Record<string, unknown>) {
  return client.post<{ success: boolean }>(`/ui/api/models/${name}/versions/${version}/config`, data)
}

export function getModelConfig(name: string) {
  return client.get<Record<string, unknown>>(`/ui/api/models/${name}/config`)
}

export function setModelConfig(name: string, data: Record<string, unknown>) {
  return client.post<{ success: boolean }>(`/ui/api/models/${name}/config`, data)
}
