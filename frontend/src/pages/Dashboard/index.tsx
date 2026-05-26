import { useState, useMemo } from 'react'
import { Row, Col, Button, Space, Input, Card, Statistic, message, Upload, Modal } from 'antd'
import { ReloadOutlined, SettingOutlined, SearchOutlined, UploadOutlined, CloudUploadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { usePolling } from '@/hooks/usePolling'
import { fetchMetricsSummary, loadModel, unloadModel, reloadModel } from '@/api/models'
import { uploadArtifact } from '@/api/repository'
import ModelCard from '@/components/ModelCard'

export default function Dashboard() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const { data, error } = usePolling(
    refreshKey >= 0 ? 'metrics-summary' : null,
    () => fetchMetricsSummary().then((r) => r.data.models),
    3000
  )

  const models = data || []

  const filtered = useMemo(() => {
    if (!search.trim()) return models
    return models.filter((m) => m.name.toLowerCase().includes(search.toLowerCase()))
  }, [models, search])

  const loadedCount = models.filter((m) => m.status === 'READY').length
  const totalQps = models.reduce((sum, m) => sum + m.qps, 0)
  const avgP99 = models.length > 0
    ? models.reduce((sum, m) => sum + m.p99_ms, 0) / models.filter((m) => m.p99_ms > 0).length || 0
    : 0
  const totalQueue = models.reduce((sum, m) => sum + m.queue_depth, 0)

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

  const handleReload = async (name: string) => {
    try {
      await reloadModel(name)
      message.success(`${name} reloaded`)
      setRefreshKey((k) => k + 1)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleUpload = async () => {
    if (!uploadFile) return
    setUploading(true)
    try {
      const res = await uploadArtifact(uploadFile)
      message.success(`Uploaded ${res.data.name} v${res.data.version}`)
      setUploadOpen(false)
      setUploadFile(null)
      setRefreshKey((k) => k + 1)
    } catch (e: any) {
      message.error(e.response?.data?.detail || e.message)
    } finally {
      setUploading(false)
    }
  }

  if (error) {
    return <div style={{ color: 'red' }}>Failed to load: {error.message}</div>
  }

  return (
    <div>
      {/* Global Overview */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Models Online" value={`${loadedCount} / ${models.length}`} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Total QPS" value={totalQps.toFixed(1)} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Avg P99 (ms)" value={avgP99.toFixed(1)} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Total Queue" value={totalQueue} />
          </Card>
        </Col>
      </Row>

      {/* Toolbar */}
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
            Upload Model
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((k) => k + 1)}>
            Refresh
          </Button>
        </Space>
        <Space>
          <Input
            placeholder="Search models..."
            prefix={<SearchOutlined />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 240 }}
          />
          <Button icon={<SettingOutlined />} onClick={() => navigate('/config')}>
            Settings
          </Button>
        </Space>
      </Space>

      {/* Model Grid */}
      <Row gutter={[16, 16]}>
        {filtered.map((m) => (
          <Col key={m.name} xs={24} sm={12} lg={8}>
            <ModelCard
              model={m}
              onLoad={handleLoad}
              onUnload={handleUnload}
              onReload={handleReload}
              onDetail={() => navigate(`/models/${m.name}`)}
            />
          </Col>
        ))}
      </Row>
      {filtered.length === 0 && <p>No models found.</p>}

      {/* Upload Modal */}
      <Modal
        title="Upload Model Artifact"
        open={uploadOpen}
        onOk={handleUpload}
        onCancel={() => { setUploadOpen(false); setUploadFile(null) }}
        confirmLoading={uploading}
        okText="Upload"
      >
        <Upload.Dragger
          beforeUpload={(file) => { setUploadFile(file); return false }}
          accept=".lma"
          maxCount={1}
          onRemove={() => setUploadFile(null)}
        >
          <p className="ant-upload-drag-icon">
            <CloudUploadOutlined />
          </p>
          <p>Click or drag .lma file to upload</p>
        </Upload.Dragger>
      </Modal>
    </div>
  )
}
