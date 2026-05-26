import { useParams } from 'react-router-dom'
import { Card, Table, Tag, Button, message } from 'antd'
import { usePolling } from '@/hooks/usePolling'
import { listVersions, fetchModelMetrics, activateVersion } from '@/api/models'
import type { ColumnsType } from 'antd/es/table'
import type { VersionInfo } from '@/types'

export default function ModelDetail() {
  const { name } = useParams<{ name: string }>()
  const { data: versionsData } = usePolling(
    name ? `versions-${name}` : null,
    () => listVersions(name!).then((r) => r.data.versions),
    5000
  )
  const { data: metrics } = usePolling(
    name ? `metrics-${name}` : null,
    () => fetchModelMetrics(name!, '1').then((r) => r.data),
    5000
  )

  const versions = versionsData || []

  const handleActivate = async (version: string) => {
    try {
      await activateVersion(name!, version)
      message.success('Activated')
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns: ColumnsType<VersionInfo> = [
    { title: 'Version', dataIndex: 'version', key: 'version' },
    { title: 'Status', dataIndex: 'status', key: 'status', render: (s: string) => <Tag>{s}</Tag> },
    { title: 'Workers', dataIndex: 'workers', key: 'workers' },
    {
      title: 'Action',
      key: 'action',
      render: (_, record) => (
        <Button size="small" onClick={() => handleActivate(record.version)}>
          Activate
        </Button>
      ),
    },
  ]

  return (
    <div>
      <h2>{name}</h2>
      <Card title="Versions" style={{ marginBottom: 16 }}>
        <Table dataSource={versions} columns={columns} rowKey="version" pagination={false} />
      </Card>
      <Card title="Metrics">
        <p>QPS: {metrics?.qps ?? '-'}</p>
        <p>P99: {metrics?.p99_ms ?? '-'} ms</p>
        <p>Queue Depth: {metrics?.queue_depth ?? '-'}</p>
      </Card>
    </div>
  )
}
