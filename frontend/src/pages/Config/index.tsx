import { useEffect, useState } from 'react'
import { Card, Descriptions, Tag, Spin, Alert } from 'antd'
import { getConfig } from '@/api/config'
import type { FullConfig } from '@/types'

export default function ConfigPage() {
  const [config, setConfig] = useState<FullConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    getConfig()
      .then((res) => setConfig(res.data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (error) return <Alert type="error" message={error} />
  if (!config) return <Alert type="warning" message="No config data" />

  const { server, grpc, metrics, webui, model_repository, features, logging } = config

  return (
    <div>
      <h2>Server Settings</h2>

      <Card title="Server" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="HTTP Port">{server.http_port}</Descriptions.Item>
          <Descriptions.Item label="gRPC Port">{server.grpc_port}</Descriptions.Item>
          <Descriptions.Item label="Metrics Port">{server.metrics_port}</Descriptions.Item>
          <Descriptions.Item label="Host">{server.host}</Descriptions.Item>
          <Descriptions.Item label="Timeout">{server.timeout}s</Descriptions.Item>
          <Descriptions.Item label="Log Level">
            <Tag color={server.log_level === 'debug' ? 'orange' : 'blue'}>{server.log_level}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Accelerator">{server.accelerator}</Descriptions.Item>
          <Descriptions.Item label="Transport">{server.transport}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="Features (Hot-swap)" style={{ marginBottom: 16 }}>
        <Descriptions column={4} size="small">
          <Descriptions.Item label="Timeline">
            <Tag color={features.timeline ? 'green' : 'default'}>{features.timeline ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="System Overview">
            <Tag color={features.system_overview ? 'green' : 'default'}>{features.system_overview ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Custom Metrics">
            <Tag color={features.custom_metrics ? 'green' : 'default'}>{features.custom_metrics ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Benchmarks">
            <Tag color={features.benchmarks ? 'green' : 'default'}>{features.benchmarks ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Playground">
            <Tag color={features.playground ? 'green' : 'default'}>{features.playground ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Alerts">
            <Tag color={features.alerts ? 'green' : 'default'}>{features.alerts ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Version Compare">
            <Tag color={features.version_compare ? 'green' : 'default'}>{features.version_compare ? 'ON' : 'OFF'}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="gRPC" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="Enabled">
            <Tag color={grpc.enabled ? 'green' : 'red'}>{grpc.enabled ? 'Yes' : 'No'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Max Workers">{grpc.max_workers}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="Metrics" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="Enabled">
            <Tag color={metrics.enabled ? 'green' : 'red'}>{metrics.enabled ? 'Yes' : 'No'}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="WebUI" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="Enabled">
            <Tag color={webui.enabled ? 'green' : 'red'}>{webui.enabled ? 'Yes' : 'No'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Report Retention">{webui.report_retention_days} days</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="Model Repository" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="Path">{String(model_repository.path || '')}</Descriptions.Item>
          <Descriptions.Item label="Control Mode">
            <Tag>{String(model_repository.control_mode || 'explicit')}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Poll Interval">{String(model_repository.poll_interval || 5)}s</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="Logging">
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="Mode">{String(logging.mode || 'queue')}</Descriptions.Item>
          <Descriptions.Item label="Level">{String(logging.level || 'info')}</Descriptions.Item>
          <Descriptions.Item label="Format">{String(logging.format || 'json')}</Descriptions.Item>
          <Descriptions.Item label="Rotation">{String(logging.rotation || 'daily')}</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  )
}
