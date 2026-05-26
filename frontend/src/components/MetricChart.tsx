import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

interface Props {
  option: EChartsOption
  height?: number
}

export default function MetricChart({ option, height = 300 }: Props) {
  return <ReactECharts option={option} style={{ height }} />
}
