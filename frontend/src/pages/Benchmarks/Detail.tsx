import { useParams } from 'react-router-dom'
import { Card, Statistic, Row, Col } from 'antd'
import { usePolling } from '@/hooks/usePolling'
import { getReport } from '@/api/benchmarks'
import MetricChart from '@/components/MetricChart'

export default function BenchmarkDetail() {
  const { id } = useParams<{ id: string }>()
  const { data } = usePolling(id ? `report-${id}` : null, () => getReport(id!).then((r) => r.data), 5000)

  if (!data) {
    return <p>Loading...</p>
  }

  const histoOption = data.latency_histogram
    ? {
        title: { text: 'Latency Distribution' },
        xAxis: { type: 'category' as const, data: data.latency_histogram.buckets.map((b) => `${b}ms`) },
        yAxis: { type: 'value' as const },
        series: [{ data: data.latency_histogram.counts, type: 'bar' as const }],
      }
    : null

  const percentileOption = {
    title: { text: 'Latency Percentiles' },
    xAxis: { type: 'category' as const, data: ['P50', 'P90', 'P95', 'P99'] },
    yAxis: { type: 'value' as const },
    series: [{ data: [data.p50_ms, data.p90_ms, data.p95_ms || 0, data.p99_ms], type: 'bar' as const }],
  }

  return (
    <div>
      <h2>Report: {data.id}</h2>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Statistic title="QPS" value={data.qps.toFixed(2)} />
        </Col>
        <Col span={6}>
          <Statistic title="Avg Latency" value={`${data.avg_latency_ms.toFixed(2)} ms`} />
        </Col>
        <Col span={6}>
          <Statistic title="P99" value={`${data.p99_ms.toFixed(2)} ms`} />
        </Col>
        <Col span={6}>
          <Statistic title="Error Rate" value={`${(data.error_rate * 100).toFixed(2)}%`} />
        </Col>
      </Row>
      {histoOption && (
        <Card title="Latency Histogram" style={{ marginBottom: 16 }}>
          <MetricChart option={histoOption} height={300} />
        </Card>
      )}
      <Card title="Percentiles">
        <MetricChart option={percentileOption} height={300} />
      </Card>
    </div>
  )
}
