import { useState } from 'react'
import { Row, Col, message } from 'antd'
import { usePolling } from '@/hooks/usePolling'
import { fetchMetricsSummary, loadModel, unloadModel } from '@/api/models'
import ModelCard from '@/components/ModelCard'

export default function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0)
  const { data, error } = usePolling(
    refreshKey >= 0 ? 'metrics-summary' : null,
    () => fetchMetricsSummary().then((r) => r.data.models),
    3000
  )

  if (error) {
    return <div style={{ color: 'red' }}>Failed to load: {error.message}</div>
  }

  const models = data || []

  const handleLoad = async (name: string) => {
    try {
      await loadModel(name)
      setRefreshKey((k) => k + 1)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleUnload = async (name: string) => {
    try {
      await unloadModel(name)
      setRefreshKey((k) => k + 1)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        {models.map((m) => (
          <Col key={m.name} xs={24} sm={12} lg={8}>
            <ModelCard model={m} onLoad={handleLoad} onUnload={handleUnload} />
          </Col>
        ))}
      </Row>
      {models.length === 0 && <p>No models found.</p>}
    </div>
  )
}
