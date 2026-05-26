import { Table, Button, Space, message } from 'antd'
import { Link } from 'react-router-dom'
import { usePolling } from '@/hooks/usePolling'
import { listReports, deleteReport, cleanupReports } from '@/api/benchmarks'
import type { ColumnsType } from 'antd/es/table'
import type { ReportSummary } from '@/types'

export default function BenchmarkList() {
  const { data, mutate } = usePolling('reports', () => listReports().then((r) => r.data.reports), 5000)
  const reports = data || []

  const handleDelete = async (id: string) => {
    try {
      await deleteReport(id)
      message.success('Deleted')
      mutate()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleCleanup = async () => {
    try {
      const res = await cleanupReports()
      message.success(`Cleaned up ${res.data.removed} reports`)
      mutate()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns: ColumnsType<ReportSummary> = [
    { title: 'ID', dataIndex: 'id', key: 'id' },
    { title: 'Model', dataIndex: 'model', key: 'model' },
    { title: 'Version', dataIndex: 'version', key: 'version' },
    { title: 'Mode', dataIndex: 'mode', key: 'mode' },
    { title: 'Concurrency', dataIndex: 'concurrency', key: 'concurrency' },
    { title: 'Duration', dataIndex: 'duration', key: 'duration' },
    {
      title: 'Action',
      key: 'action',
      render: (_, record) => (
        <Space>
          <Link to={`/benchmarks/${record.id}`}>View</Link>
          <Button danger size="small" onClick={() => handleDelete(record.id)}>
            Delete
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Link to="/benchmarks/new">
          <Button type="primary">New Benchmark</Button>
        </Link>
        <Button onClick={handleCleanup}>Cleanup Expired</Button>
      </Space>
      <Table dataSource={reports} columns={columns} rowKey="id" />
    </div>
  )
}
