import { Card, Tag, Button, Space, Statistic } from 'antd'
import { ThunderboltOutlined, SwapOutlined } from '@ant-design/icons'
import type { ModelInfo } from '@/types'

interface Props {
  model: ModelInfo
  onLoad: (name: string) => void
  onUnload: (name: string) => void
}

export default function ModelCard({ model, onLoad, onUnload }: Props) {
  const statusColor =
    model.status === 'READY' ? 'success' :
    model.status === 'LOADING' ? 'processing' :
    'default'

  return (
    <Card
      title={model.name}
      extra={<Tag color={statusColor}>{model.status}</Tag>}
      style={{ marginBottom: 16 }}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space>
          <Tag>v{model.version}</Tag>
          {model.stream && <Tag icon={<ThunderboltOutlined />}>stream</Tag>}
          {model.bidirectional && <Tag icon={<SwapOutlined />}>bidir</Tag>}
        </Space>
        <Space size="large">
          <Statistic title="Workers" value={model.workers} />
          <Statistic title="QPS" value={model.qps.toFixed(1)} />
          <Statistic title="P99 (ms)" value={model.p99_ms.toFixed(1)} />
          <Statistic title="Queue" value={model.queue_depth} />
        </Space>
        <Space>
          {model.status !== 'READY' ? (
            <Button type="primary" onClick={() => onLoad(model.name)}>Load</Button>
          ) : (
            <Button danger onClick={() => onUnload(model.name)}>Unload</Button>
          )}
        </Space>
      </Space>
    </Card>
  )
}
