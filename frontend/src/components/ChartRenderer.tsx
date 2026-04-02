import { useRef, useEffect, useCallback } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ChartSpec } from '../types'

// Register only the components we need (tree-shaking friendly)
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
])

interface ChartRendererProps {
  spec: ChartSpec
}

export function ChartRenderer({ spec }: ChartRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  // Initialize or update the chart whenever spec changes
  const renderChart = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    if (!instanceRef.current) {
      instanceRef.current = echarts.init(container)
    }

    instanceRef.current.setOption(spec.echarts_option, { notMerge: true })
  }, [spec])

  useEffect(() => {
    renderChart()
  }, [renderChart])

  // Resize chart when container width changes
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      instanceRef.current?.resize()
    })
    if (containerRef.current) {
      observer.observe(containerRef.current)
    }
    return () => observer.disconnect()
  }, [])

  // Dispose on unmount
  useEffect(() => {
    return () => {
      instanceRef.current?.dispose()
      instanceRef.current = null
    }
  }, [])

  // card type: render as a numeric summary, not an ECharts canvas
  if (spec.type === 'card') {
    const option = spec.echarts_option as Record<string, unknown>
    const value = (option.value as string | number | undefined) ?? '—'
    const title = (option.title as string | undefined) ?? ''
    return (
      <div className="chart-card">
        <div className="chart-card-label">{title}</div>
        <div className="chart-card-value">{value}</div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="chart-canvas"
      aria-label={`${spec.type} chart`}
    />
  )
}
