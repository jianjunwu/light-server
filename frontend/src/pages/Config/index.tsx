import { useEffect, useState } from 'react'
import { Form, Input, InputNumber, Switch, Button, Collapse, message } from 'antd'
import { getConfig, saveConfig } from '@/api/config'
import type { FullConfig } from '@/types'

export default function ConfigPage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [yamlPreview, setYamlPreview] = useState('')

  useEffect(() => {
    getConfig().then((res) => {
      form.setFieldsValue(res.data)
      updateYaml(res.data)
    })
  }, [form])

  const updateYaml = (values: FullConfig) => {
    setYamlPreview(JSON.stringify(values, null, 2))
  }

  const onValuesChange = (_: any, all: FullConfig) => {
    updateYaml(all)
  }

  const onFinish = async (values: FullConfig) => {
    setLoading(true)
    try {
      await saveConfig(values)
      message.success('Config saved')
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2>Server Configuration</h2>
      <Form form={form} layout="vertical" onFinish={onFinish} onValuesChange={onValuesChange}>
        <Collapse defaultActiveKey={['server']}>
          <Collapse.Panel header="Server" key="server">
            <Form.Item name={['server', 'http_port']} label="HTTP Port">
              <InputNumber />
            </Form.Item>
            <Form.Item name={['server', 'grpc_port']} label="gRPC Port">
              <InputNumber />
            </Form.Item>
            <Form.Item name={['server', 'metrics_port']} label="Metrics Port">
              <InputNumber />
            </Form.Item>
            <Form.Item name={['server', 'host']} label="Host">
              <Input />
            </Form.Item>
            <Form.Item name={['server', 'timeout']} label="Timeout">
              <InputNumber />
            </Form.Item>
          </Collapse.Panel>
          <Collapse.Panel header="gRPC" key="grpc">
            <Form.Item name={['grpc', 'enabled']} label="Enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name={['grpc', 'max_workers']} label="Max Workers">
              <InputNumber />
            </Form.Item>
          </Collapse.Panel>
          <Collapse.Panel header="Metrics" key="metrics">
            <Form.Item name={['metrics', 'enabled']} label="Enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Collapse.Panel>
          <Collapse.Panel header="WebUI" key="webui">
            <Form.Item name={['webui', 'enabled']} label="Enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name={['webui', 'report_retention_days']} label="Report Retention (days)">
              <InputNumber />
            </Form.Item>
          </Collapse.Panel>
        </Collapse>
        <Form.Item style={{ marginTop: 16 }}>
          <Button type="primary" htmlType="submit" loading={loading}>
            Save
          </Button>
        </Form.Item>
      </Form>
      <h3>YAML Preview</h3>
      <pre style={{ background: '#f5f5f5', padding: 16, borderRadius: 4 }}>{yamlPreview}</pre>
    </div>
  )
}
