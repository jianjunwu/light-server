import client from './client'
import type { FullConfig } from '@/types'

export function getConfig() {
  return client.get<FullConfig>('/ui/api/config')
}

export function saveConfig(config: FullConfig) {
  return client.post<{ success: boolean }>('/ui/api/config', config)
}
