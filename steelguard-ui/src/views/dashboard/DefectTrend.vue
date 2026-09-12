<template>
  <div>
    <a-card :bordered="false" style="margin-bottom: 16px">
      <a-space wrap>
        <span style="font-weight: 600">缺陷趋势看板</span>
        <a-tag color="blue">数据来源: MySQL 质检库</a-tag>
        <a-tag color="green" v-if="trend">已完成批次 {{ trend.doneBatches }} / {{ trend.totalBatches }}</a-tag>
      </a-space>
      <template #extra>
        <a-radio-group v-model:value="days" button-style="solid" @change="loadTrend">
          <a-radio-button :value="7">近 7 天</a-radio-button>
          <a-radio-button :value="30">近 30 天</a-radio-button>
          <a-radio-button :value="90">近 90 天</a-radio-button>
          <a-radio-button :value="180">近 180 天</a-radio-button>
        </a-radio-group>
      </template>
    </a-card>

    <!-- KPI -->
    <a-row :gutter="16">
      <a-col :xs="12" :md="4">
        <a-card>
          <a-statistic title="完成批次" :value="trend?.doneBatches ?? 0" />
        </a-card>
      </a-col>
      <a-col :xs="12" :md="4">
        <a-card>
          <a-statistic title="已检图片" :value="trend?.totalImages ?? 0" />
        </a-card>
      </a-col>
      <a-col :xs="12" :md="4">
        <a-card>
          <a-statistic title="缺陷图片" :value="trend?.totalDefectImages ?? 0"
                       :value-style="{ color: '#fa541c' }" />
        </a-card>
      </a-col>
      <a-col :xs="12" :md="4">
        <a-card>
          <a-statistic title="缺陷图占比" :value="defectRatePct" suffix="%"
                       :precision="1" :value-style="{ color: '#fa8c16' }" />
        </a-card>
      </a-col>
      <a-col :xs="12" :md="4">
        <a-card>
          <a-statistic title="入库案例" :value="trend?.totalCases ?? 0"
                       :value-style="{ color: '#722ed1' }" />
        </a-card>
      </a-col>
      <a-col :xs="12" :md="4">
        <a-card>
          <a-statistic title="平均置信度" :value="avgConfPct" suffix="%"
                       :precision="1" :value-style="{ color: '#13c2c2' }" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 趋势 + 严重度 -->
    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :xs="24" :lg="16">
        <a-card size="small" :title="`每日新增缺陷案例（近 ${days} 天）`">
          <a-spin :spinning="loading">
            <div ref="dailyChartRef" class="chart"></div>
          </a-spin>
        </a-card>
      </a-col>
      <a-col :xs="24" :lg="8">
        <a-card size="small" title="批次严重度分布（全部已完成批次）">
          <a-spin :spinning="loading">
            <div ref="severityChartRef" class="chart"></div>
          </a-spin>
        </a-card>
      </a-col>
    </a-row>

    <!-- 六类分布 -->
    <a-card size="small" title="六类缺陷案例分布（全部历史）" style="margin-top: 16px">
      <a-spin :spinning="loading">
        <div ref="classChartRef" class="chart-wide"></div>
      </a-spin>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { getDefectTrend, type DefectTrend } from '@/api/inspection'
import { classCn, classColor, severityMeta } from '@/utils/steel'

const days = ref(30)
const loading = ref(false)
const trend = ref<DefectTrend | null>(null)

const defectRatePct = computed(() => (trend.value ? trend.value.defectImageRate * 100 : 0))
const avgConfPct = computed(() => (trend.value ? trend.value.avgConfidence * 100 : 0))

const dailyChartRef = ref<HTMLElement>()
const classChartRef = ref<HTMLElement>()
const severityChartRef = ref<HTMLElement>()
let dailyChart: echarts.ECharts | null = null
let classChart: echarts.ECharts | null = null
let severityChart: echarts.ECharts | null = null

function renderDaily() {
  if (!dailyChart || !trend.value) return
  const d = trend.value.daily
  dailyChart.setOption(
    {
      tooltip: { trigger: 'axis' },
      grid: { left: 48, right: 20, top: 24, bottom: 48 },
      xAxis: {
        type: 'category',
        data: d.map((x) => x.date.slice(5)),
        axisLabel: { fontSize: 10 },
        boundaryGap: false,
      },
      yAxis: { type: 'value', minInterval: 1, name: '案例数' },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }],
      series: [
        {
          name: '新增案例',
          type: 'line',
          smooth: true,
          areaStyle: { opacity: 0.15 },
          itemStyle: { color: '#1677ff' },
          data: d.map((x) => x.count),
        },
      ],
    },
    { notMerge: true },
  )
}

function renderClass() {
  if (!classChart || !trend.value) return
  const dist = trend.value.classDistribution
  classChart.setOption(
    {
      tooltip: { trigger: 'axis' },
      legend: { data: ['案例数', '平均置信度'], bottom: 0 },
      grid: { left: 56, right: 56, top: 24, bottom: 48 },
      xAxis: {
        type: 'category',
        data: dist.map((c) => classCn(c.className)),
        axisLabel: { fontSize: 12 },
      },
      yAxis: [
        { type: 'value', name: '案例数', minInterval: 1 },
        { type: 'value', name: '置信度', min: 0, max: 1, axisLabel: { formatter: (v: number) => `${v * 100}%` } },
      ],
      series: [
        {
          name: '案例数',
          type: 'bar',
          barWidth: '40%',
          data: dist.map((c) => ({
            value: c.count,
            itemStyle: { color: classColor(c.className) },
          })),
          label: { show: true, position: 'top' },
        },
        {
          name: '平均置信度',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          itemStyle: { color: '#fa8c16' },
          data: dist.map((c) => c.avgConfidence),
        },
      ],
    },
    { notMerge: true },
  )
}

function renderSeverity() {
  if (!severityChart || !trend.value) return
  const dist = trend.value.severityDistribution
  severityChart.setOption(
    {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, type: 'scroll' },
      series: [
        {
          type: 'pie',
          radius: ['40%', '68%'],
          center: ['50%', '44%'],
          data: dist
            .map((s) => {
              const meta = severityMeta(s.severity)
              const colorMap: Record<string, string> = {
                critical: '#f5222d',
                high: '#fa541c',
                medium: '#faad14',
                low: '#52c41a',
              }
              return {
                name: meta.label,
                value: s.count,
                itemStyle: { color: colorMap[s.severity || ''] || '#8c8c8c' },
              }
            })
            .filter((x) => x.value > 0),
          label: { formatter: '{b}\n{c} 批' },
        },
      ],
    },
    { notMerge: true },
  )
}

function renderAll() {
  nextTick(() => {
    renderDaily()
    renderClass()
    renderSeverity()
  })
}

function handleResize() {
  dailyChart?.resize()
  classChart?.resize()
  severityChart?.resize()
}

async function loadTrend() {
  loading.value = true
  try {
    trend.value = await getDefectTrend(days.value)
    renderAll()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  dailyChart = echarts.init(dailyChartRef.value)
  classChart = echarts.init(classChartRef.value)
  severityChart = echarts.init(severityChartRef.value)
  window.addEventListener('resize', handleResize)
  await loadTrend()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  dailyChart?.dispose()
  classChart?.dispose()
  severityChart?.dispose()
})
</script>

<style scoped>
.chart {
  width: 100%;
  height: 320px;
}
.chart-wide {
  width: 100%;
  height: 300px;
}
</style>
