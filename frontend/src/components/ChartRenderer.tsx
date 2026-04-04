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

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])

interface Props { spec: ChartSpec }

export function ChartRenderer({ spec }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  const renderChart = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    if (!instanceRef.current) instanceRef.current = echarts.init(el)
    instanceRef.current.setOption(spec.echarts_option, { notMerge: true })
  }, [spec])

  useEffect(() => { renderChart() }, [renderChart])

  useEffect(() => {
    const observer = new ResizeObserver(() => { instanceRef.current?.resize() })
    if (containerRef.current) observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    return () => { instanceRef.current?.dispose(); instanceRef.current = null }
  }, [])

  if (spec.type === 'card') {
    const opt = spec.echarts_option as Record<string, unknown>
    return (
      <div className="card">
        <div className="chart-single-card">
          <div className="chart-single-label">{(opt.title as string | undefined) ?? ''}</div>
          <div className="chart-single-value">{(opt.value as string | number | undefined) ?? '—'}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="chart-pad">
        <div ref={containerRef} className="chart-canvas" aria-label={`${spec.type} chart`} />
      </div>
    </div>
  )
}
