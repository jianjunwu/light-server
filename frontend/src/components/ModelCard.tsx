import { Card, Tag, Button, Space, Statistic, Dropdown } from 'antd'
import {
  ThunderboltOutlined,
  SwapOutlined,
  EllipsisOutlined,
  EyeOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { ModelInfo } from '@/types'

interface Props {
  model: ModelInfo
  onLoad: (name: string) => void
  onUnload: (name: string) => void
  onReload: (name: string) => void
  onDetail: (name: string) => void
}

export default function ModelCard({ model, onLoad, onUnload, onReload, onDetail }: Props) {
  const isReady = model.status === 'READY'
  const isLoading = model.status === 'LOADING'

  const statusColor = isReady ? 'success' : isLoading ? 'processing' : 'default'
  const cardOpacity = isReady ? 1 : 0.7

  const moreItems = [
    {
      key: 'detail',
      icon: <EyeOutlined />,
      label: 'View Detail',
      onClick: () => onDetail(model.name),
    },
    ...(isReady
      ? [
          {
            key: 'reload',
            icon: <ReloadOutlined />,
            label: 'Hot Reload',
            onClick: () => onReload(model.name),
          },
        ]
      : []),
  ]

  return (
    <Card
      title={
        <span style={{ cursor: 'pointer' }} onClick={() => onDetail(model.name)}>
          {model.name}
        </span>
      }
      extra={
        <Space>
          <Tag color={statusColor}>{model.status}</Tag>
          <Dropdown menu={{ items: moreItems }} placement="bottomRight">
            <Button type="text" icon={<EllipsisOutlined />} size="small" />
          </Dropdown>
        </Space>
      }
      style={{ marginBottom: 16, opacity: cardOpacity }}
      bodyStyle={{ padding: '16px 20px' }}
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
          {!isReady ? (
            <Button type="primary" onClick={() => onLoad(model.name)} loading={isLoading}>
              Load
            </Button>
          ) : (
            <Button danger onClick={() => onUnload(model.name)}>
              Unload
            </Button>
          )}
          <Button onClick={() => onDetail(model.name)}>Detail</Button>
        </Space>
      </Space>
    </Card>
  )
}
