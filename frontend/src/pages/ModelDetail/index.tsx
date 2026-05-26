import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Table, Tag, Button, message, Tabs, Statistic, Space,
  Form, Input, InputNumber, Switch, Popconfirm, Upload,
  Row, Col, Alert,
} from 'antd'
import {
  ReloadOutlined, ArrowLeftOutlined, CloudUploadOutlined,
} from '@ant-design/icons'
import { usePolling } from '@/hooks/usePolling'
import {
  listVersions, fetchModelMetrics, activateVersion,
  loadModel, unloadModel, reloadModel, deleteVersion,
  getVersionConfig, setVersionConfig, getModelConfig, setModelConfig,
} from '@/api/models'
import type { ColumnsType } from 'antd/es/table'
import type { VersionInfo } from '@/types'

const { TabPane } = Tabs

export default function ModelDetail() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('monitoring')
  const [vcForm] = Form.useForm()
  const [mcForm] = Form.useForm()

  const { data: versionsData } = usePolling(
    name ? `versions-${name}` : null,
    () => listVersions(name!).then((r) => r.data.versions),
    5000,
  )
  const { data: metrics } = usePolling(
    name ? `metrics-${name}` : null,
    () => fetchModelMetrics(name!, '1').then((r) => r.data),
    5000,
  )

  const versions = versionsData || []
  const activeVersion = versions.find((v) => v.status === 'READY')?.version || '-'

  useEffect(() => {
    if (!name) return
    getVersionConfig(name, '1').then((r) => {
      vcForm.setFieldsValue(r.data)
    })
    getModelConfig(name).then((r) => {
      mcForm.setFieldsValue(r.data)
    })
  }, [name, vcForm, mcForm])

  const handleActivate = async (version: string) => {
    try {
      await activateVersion(name!, version)
      message.success('Activated')
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleLoad = async (version: string) => {
    try {
      await loadModel(name!, version)
      message.success(`${name} v${version} loaded`)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleUnload = async (version: string) => {
    try {
      await unloadModel(name!, version)
      message.success(`${name} v${version} unloaded`)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleReload = async () => {
    try {
      await reloadModel(name!)
      message.success(`${name} reloaded`)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleDeleteVersion = async (version: string) => {
    try {
      await deleteVersion(name!, version)
      message.success(`Version ${version} deleted`)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleSaveVersionConfig = async (values: Record<string, unknown>) => {
    try {
      await setVersionConfig(name!, '1', values)
      message.success('Version config saved')
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleSaveModelConfig = async (values: Record<string, unknown>) => {
    try {
      await setModelConfig(name!, values)
      message.success('Model config saved')
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const versionColumns: ColumnsType<VersionInfo> = [
    { title: 'Version', dataIndex: 'version', key: 'version' },
    { title: 'Status', dataIndex: 'status', key: 'status', render: (s: string) => <Tag color={s === 'READY' ? 'green' : 'default'}>{s}</Tag> },
    { title: 'Workers', dataIndex: 'workers', key: 'workers' },
    {
      title: 'Action',
      key: 'action',
      render: (_, record) => (
        <Space>
          {record.status !== 'READY' && (
            <Button size="small" type="primary" onClick={() => handleLoad(record.version)}>Load</Button>
          )}
          {record.status === 'READY' && (
            <Button size="small" danger onClick={() => handleUnload(record.version)}>Unload</Button>
          )}
          <Button size="small" onClick={() => handleActivate(record.version)}>Activate</Button>
          <Popconfirm title="Delete this version?" onConfirm={() => handleDeleteVersion(record.version)}>
            <Button size="small" danger>Delete</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* Top bar */}
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>Back</Button>
          <h2 style={{ margin: 0 }}>{name}</h2>
          <Tag color="blue">Active: {activeVersion}</Tag>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={handleReload}>Hot Reload</Button>
          <Button danger onClick={() => handleUnload('1')}>Unload</Button>
        </Space>
      </Space>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="Monitoring" key="monitoring">
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Card><Statistic title="QPS" value={metrics?.qps ?? 0} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card><Statistic title="P99 (ms)" value={metrics?.p99_ms ?? 0} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card><Statistic title="Avg (ms)" value={(metrics as any)?.avg_ms ?? 0} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card><Statistic title="Queue Depth" value={metrics?.queue_depth ?? 0} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card><Statistic title="Active Workers" value={(metrics as any)?.active_workers ?? 0} /></Card>
            </Col>
          </Row>
          {(metrics as any)?.timeline && (
            <Card title="Timeline">
              <Alert message="Timeline data available via API (timeline feature enabled)" type="info" />
            </Card>
          )}
        </TabPane>

        <TabPane tab="Versions" key="versions">
          <Card title="Versions" style={{ marginBottom: 16 }}>
            <Table dataSource={versions} columns={versionColumns} rowKey="version" pagination={false} />
          </Card>
          <Card title="Upload New Version">
            <Upload.Dragger
              beforeUpload={() => { return false }}
              accept=".lma,.zip,.tar.gz"
              maxCount={1}
              onRemove={() => {}}
            >
              <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p>
              <p>Click or drag model archive to upload</p>
            </Upload.Dragger>
          </Card>
        </TabPane>

        <TabPane tab="Configuration" key="config">
          <Card title="config.yaml (Version-level)" style={{ marginBottom: 16 }}>
            <Form form={vcForm} layout="vertical" onFinish={handleSaveVersionConfig}>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="max_batch_size" label="Max Batch Size">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="batch_timeout" label="Batch Timeout">
                    <InputNumber step={0.001} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_queue_size" label="Max Queue Size">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_sequence_length" label="Max Sequence Length">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="stream" label="Stream" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="bidirectional" label="Bidirectional" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="continuous_batching" label="Continuous Batching" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item>
                <Button type="primary" htmlType="submit">Save Version Config</Button>
              </Form.Item>
            </Form>
          </Card>

          <Card title="model_config.yaml (Model-level)">
            <Form form={mcForm} layout="vertical" onFinish={handleSaveModelConfig}>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="default_version" label="Default Version">
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_loaded_versions" label="Max Loaded Versions">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="hot_reload" label="Hot Reload" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="hot_reload_interval" label="Hot Reload Interval (s)">
                    <InputNumber step={0.1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item>
                <Button type="primary" htmlType="submit">Save Model Config</Button>
              </Form.Item>
            </Form>
          </Card>
        </TabPane>
      </Tabs>
    </div>
  )
}
