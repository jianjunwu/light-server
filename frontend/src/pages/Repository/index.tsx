import { Table, Card } from 'antd'
import { usePolling } from '@/hooks/usePolling'
import { listRepository } from '@/api/repository'
import FileUpload from '@/components/FileUpload'
import type { ColumnsType } from 'antd/es/table'
import type { RepoModel } from '@/api/repository'

const columns: ColumnsType<RepoModel> = [
  { title: 'Name', dataIndex: 'name', key: 'name' },
  { title: 'Version', dataIndex: 'version', key: 'version' },
  { title: 'Type', dataIndex: 'type', key: 'type' },
]

export default function Repository() {
  const { data } = usePolling('repository', () => listRepository().then((r) => r.data.models), 10000)
  const models = data || []

  return (
    <div>
      <Card title="Upload Artifact" style={{ marginBottom: 16 }}>
        <FileUpload />
      </Card>
      <Card title="Models">
        <Table dataSource={models} columns={columns} rowKey={(r) => `${r.name}-${r.version}`} />
      </Card>
    </div>
  )
}
