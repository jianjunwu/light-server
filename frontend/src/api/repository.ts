import client from './client'

export interface RepoModel {
  name: string
  version: string
  type: string
}

export function listRepository() {
  return client.post<{ models: RepoModel[] }>('/v2/repository/index')
}

export function uploadArtifact(file: File, verifySignature = false) {
  const form = new FormData()
  form.append('file', file)
  form.append('verify_signature', String(verifySignature))
  return client.post<{ success: boolean; name: string; version: string }>('/ui/api/artifacts/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
