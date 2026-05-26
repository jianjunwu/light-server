import { useState } from 'react'
import { Form, Input, InputNumber, Select, Slider, Button, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { createBenchmark } from '@/api/benchmarks'

export default function BenchmarkCreate() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: any) => {
    setLoading(true)
    try {
      const res = await createBenchmark({
        ...values,
        payload: values.payload,
      })
      message.success(`Benchmark started: ${res.data.job_id}`)
      navigate('/benchmarks')
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2>New Benchmark</h2>
      <Form layout="vertical" onFinish={onFinish} style={{ maxWidth: 600 }}>
        <Form.Item label="Model" name="model" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item label="Version" name="version" initialValue="1">
          <Input />
        </Form.Item>
        <Form.Item label="Mode" name="mode" initialValue="fixed">
          <Select options={[{ value: 'fixed' }, { value: 'throughput' }]} />
        </Form.Item>
        <Form.Item label="Concurrency" name="concurrency" initialValue={8}>
          <Slider min={1} max={64} />
        </Form.Item>
        <Form.Item label="Duration (s)" name="duration" initialValue={30}>
          <InputNumber min={1} />
        </Form.Item>
        <Form.Item label="Payload (JSON)" name="payload" initialValue='{"input": 1.0}'>
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item label="Protocol" name="protocol" initialValue="http">
          <Select options={[{ value: 'http' }, { value: 'websocket' }]} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            Start
          </Button>
        </Form.Item>
      </Form>
    </div>
  )
}
