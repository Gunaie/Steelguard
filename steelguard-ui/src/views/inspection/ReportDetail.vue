<template>
  <div>
    <!-- 操作栏(不进入 PDF 截图); 注意 #extra 必须是 a-card 的直接子插槽 -->
    <a-card :bordered="false" style="margin-bottom: 16px">
      <template #extra>
        <a-space wrap>
          <a-button type="primary" :loading="generating"
                    :disabled="!canGenerate" @click="handleGenerate">
            <template #icon><robot-outlined /></template>
            {{ detail?.reported === 1 ? '重新生成报告' : '生成 AI 报告' }}
          </a-button>
          <a-button :disabled="!report" :loading="exportingPdf" @click="handleExportPdf">
            <template #icon><file-pdf-outlined /></template>
            导出 PDF
          </a-button>
          <a-button :disabled="!report" @click="handleExportExcel">
            <template #icon><file-excel-outlined /></template>
            导出 Excel
          </a-button>
        </a-space>
      </template>
      <a-space wrap>
        <a-button @click="goBack">
          <template #icon><arrow-left-outlined /></template>
          返回批次
        </a-button>
        <a-divider type="vertical" />
        <span style="font-size: 16px; font-weight: 600">
          {{ detail?.name || '批次报告' }}
        </span>
        <a-tag v-if="detail" :color="sourceMeta(detail.source).color">
          {{ sourceMeta(detail.source).label }}
        </a-tag>
        <a-tag v-if="report" :color="severityMeta(report.severity).color">
          程序定级: {{ severityMeta(report.severity).label }}
        </a-tag>
        <a-tag v-if="report" color="purple">AI 复核: {{ severityMeta(report.narrative.severity).label }}</a-tag>
      </a-space>
      <div v-if="detail?.errorMsg" style="margin-top: 8px">
        <a-alert type="warning" show-icon :message="`跑批存在失败图片: ${detail.errorMsg}`" />
      </div>
    </a-card>

    <a-spin :spinning="loading" tip="加载批次详情...">
      <!-- 未生成报告: 批次速览 + 生成入口 -->
      <a-card v-if="!loading && detail && !report" :bordered="false">
        <a-descriptions bordered :column="3" size="small" style="margin-bottom: 24px">
          <a-descriptions-item label="批次编号">{{ detail.batchNo }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="statusMeta(detail.status).color">{{ statusMeta(detail.status).label }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="检测模型">{{ detail.model || '-' }}</a-descriptions-item>
          <a-descriptions-item label="图片总数">{{ detail.imageCount }}</a-descriptions-item>
          <a-descriptions-item label="缺陷图片">{{ detail.defectImageCount }}</a-descriptions-item>
          <a-descriptions-item label="缺陷框数">{{ detail.defectCount }}</a-descriptions-item>
        </a-descriptions>
        <a-empty v-if="canGenerate" description="本批次尚未生成 AI 结构化质检报告">
          <a-button type="primary" :loading="generating" @click="handleGenerate">
            <template #icon><robot-outlined /></template>
            立即生成(qwen-plus, 约 15~30 秒)
          </a-button>
        </a-empty>
        <a-empty v-else description="批次尚未完成检测, 无法生成报告">
          <a-button type="primary" @click="goBack">返回批次列表</a-button>
        </a-empty>
      </a-card>

      <a-result v-if="!loading && detail && reportError" status="error"
                title="报告 JSON 解析失败" :sub-title="reportError" />

      <!-- ========== 报告正文(PDF 截图根节点) ========== -->
      <div v-if="report" ref="captureRef" class="report-capture">
        <!-- 打印抬头 -->
        <div class="report-header">
          <div>
            <div class="report-title">SteelGuard 结构化质检报告</div>
            <div class="report-sub">
              {{ report.facts.batch_no }} · {{ report.facts.name }}
            </div>
          </div>
          <div class="report-header-meta">
            <a-tag :color="severityMeta(report.severity).color" style="font-size: 14px; padding: 2px 12px">
              {{ severityMeta(report.severity).label }}
            </a-tag>
            <div>生成时间: {{ formatTime(report.generated_at) }}</div>
            <div>模型: {{ report.model }} · {{ report.provider }}</div>
          </div>
        </div>

        <a-alert
          v-if="report.severity_adjusted"
          type="warning" show-icon style="margin-bottom: 16px"
          message="AI 复核定级与程序规则定级不一致, 本报告严重度以程序规则为准, 建议人工复核查验"
        />

        <!-- 事实卡片: 数字全部来自程序统计(防幻觉) -->
        <a-card size="small" title="① 批次事实(程序统计, 唯一数字来源)">
          <a-row :gutter="[12, 16]">
            <a-col :xs="12" :sm="6" v-for="card in factCards" :key="card.label">
              <div class="fact-box">
                <div class="fact-value" :style="{ color: card.color }">
                  {{ card.value }}<span v-if="card.suffix" class="fact-suffix">{{ card.suffix }}</span>
                </div>
                <div class="fact-label">{{ card.label }}</div>
              </div>
            </a-col>
          </a-row>
        </a-card>

        <!-- 类别分布 -->
        <a-row :gutter="16" style="margin-top: 16px">
          <a-col :xs="24" :md="10">
            <a-card size="small" title="② 缺陷类别分布">
              <div ref="pieRef" class="pie-chart"></div>
            </a-card>
          </a-col>
          <a-col :xs="24" :md="14">
            <a-card size="small" title="③ 类别统计明细">
              <a-table
                :data-source="report.class_stats"
                :pagination="false"
                size="small"
                row-key="class_name"
                :columns="classColumns"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'class_name'">
                    <a-tag :color="classMeta(record.class_name).color">
                      {{ record.class_name_cn }}
                    </a-tag>
                    <span style="color: #999; font-size: 12px">{{ record.class_name }}</span>
                  </template>
                  <template v-else-if="column.key === 'ratio'">
                    <a-progress :percent="Math.round(record.ratio * 100)" size="small"
                                :stroke-color="classMeta(record.class_name).color" />
                  </template>
                  <template v-else-if="column.key === 'avg_confidence'">
                    {{ (record.avg_confidence * 100).toFixed(1) }}%
                  </template>
                </template>
              </a-table>
            </a-card>
          </a-col>
        </a-row>

        <!-- AI 总体结论 -->
        <a-card size="small" title="④ AI 总体评价与定级理由" style="margin-top: 16px">
          <a-typography-paragraph>{{ report.narrative.overall_assessment }}</a-typography-paragraph>
          <a-divider style="margin: 10px 0" />
          <div class="narrative-label">严重度判定理由</div>
          <a-typography-paragraph type="secondary">
            {{ report.narrative.severity_reason }}
          </a-typography-paragraph>
        </a-card>

        <!-- 逐类分析 -->
        <a-card size="small" title="⑤ 逐类缺陷分析" style="margin-top: 16px">
          <a-row :gutter="[12, 12]">
            <a-col :xs="24" :md="12" v-for="cs of report.class_stats" :key="cs.class_name">
              <div class="class-analysis-card">
                <div class="class-analysis-head">
                  <a-tag :color="classMeta(cs.class_name).color">
                    {{ cs.class_name_cn }}
                  </a-tag>
                  <span class="class-analysis-stat">
                    {{ cs.count }} 例 · 占比 {{ pct(cs.ratio) }} · 均置 {{ pct(cs.avg_confidence) }}
                  </span>
                </div>
                <template v-if="analysisMap[cs.class_name]">
                  <p><b>表现：</b>{{ analysisMap[cs.class_name].finding }}</p>
                  <p><b>建议：</b>{{ analysisMap[cs.class_name].suggestion }}</p>
                </template>
                <p v-else style="color: #999">AI 未返回该类分析</p>
              </div>
            </a-col>
          </a-row>
        </a-card>

        <!-- 处置建议 + 风险研判 -->
        <a-row :gutter="16" style="margin-top: 16px">
          <a-col :xs="24" :md="13">
            <a-card size="small" title="⑥ 可执行处置建议(按优先级)">
              <a-timeline>
                <a-timeline-item v-for="(d, i) in report.narrative.disposition" :key="i"
                                :color="i === 0 ? 'red' : 'blue'">
                  {{ d }}
                </a-timeline-item>
              </a-timeline>
            </a-card>
          </a-col>
          <a-col :xs="24" :md="11">
            <a-card size="small" title="⑦ 放行 / 返修风险研判">
              <a-alert type="error" show-icon :message="report.narrative.risk_summary"
                       style="white-space: pre-wrap; align-items: flex-start" />
            </a-card>
          </a-col>
        </a-row>

        <!-- 相似历史案例图片墙 -->
        <a-card size="small" style="margin-top: 16px"
                :title="`⑧ 相似历史案例证据(Milvus 检索, ${report.similar_cases.length} 条)`">
          <a-empty v-if="!report.similar_cases.length"
                   description="无相似历史案例(历史库为空或检索基础设施降级)" />
          <a-image-preview-group v-else>
            <a-row :gutter="[12, 12]">
              <a-col :xs="12" :sm="8" :md="4" v-for="(s, i) in report.similar_cases" :key="s.milvus_pk">
                <div class="case-card">
                  <a-image
                    :src="s.crop_url || undefined"
                    :alt="`${i + 1}-裁剪图 ${s.class_name_cn || s.class_name}`"
                    class="case-img"
                    :fallback="fallbackImg"
                  />
                  <!-- 原图并入同一预览组, 列表中隐藏, 预览时可左右滑动查看 -->
                  <a-image v-if="s.source_image_url" :src="s.source_image_url"
                           :alt="`${i + 1}-原图 ${s.image_name}`"
                           class="case-img-hidden" />
                  <div class="case-meta">
                    <a-tag :color="classMeta(s.class_name).color" style="margin: 0">
                      {{ s.class_name_cn || classMeta(s.class_name).label }}
                    </a-tag>
                    <span class="case-score">相似 {{ (s.score * 100).toFixed(1) }}%</span>
                  </div>
                  <div class="case-sub" :title="s.batch_no">批次 {{ s.batch_no }}</div>
                  <div class="case-sub" :title="s.image_name">{{ s.image_name }}</div>
                </div>
              </a-col>
            </a-row>
          </a-image-preview-group>
        </a-card>

        <!-- 生成元信息 -->
        <div class="report-footer">
          Schema v{{ report.schema_version }} ·
          数字结论由程序统计注入, 文字由 {{ report.model }} 生成 ·
          Tokens {{ report.tokens.total_tokens }}
          (prompt {{ report.tokens.prompt_tokens }} / completion {{ report.tokens.completion_tokens }}) ·
          生成耗时 {{ (report.latency_ms / 1000).toFixed(1) }}s
        </div>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeftOutlined,
  RobotOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import * as echarts from 'echarts'
import { getBatchDetail, generateReport,
  type BatchDetailVO, type StructuredReport } from '@/api/inspection'
import {
  classMeta, pct, severityMeta, sourceMeta, statusMeta,
} from '@/utils/steel'
import { exportReportExcel, exportReportPdf, parseReport } from '@/utils/reportExport'

const route = useRoute()
const router = useRouter()
const batchId = Number(route.params.id)

// 透明 1x1 占位图, 预签名失效/裁剪图缺失时兜底
const fallbackImg =
  'data:image/svg+xml;charset=utf-8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">' +
      '<rect width="100%" height="100%" fill="#f0f0f0"/>' +
      '<text x="50%" y="50%" font-size="14" fill="#999" text-anchor="middle">图片不可用</text>' +
      '</svg>',
  )

const loading = ref(true)
const generating = ref(false)
const exportingPdf = ref(false)
const detail = ref<BatchDetailVO | null>(null)
const report = ref<StructuredReport | null>(null)
const reportError = ref('')

const captureRef = ref<HTMLElement | null>(null)
const pieRef = ref<HTMLElement | null>(null)
let pieChart: echarts.ECharts | null = null

const canGenerate = computed(
  () => !!detail.value && ['done', 'failed'].includes(detail.value.status),
)

const factCards = computed(() => {
  const f = report.value?.facts
  if (!f) return []
  return [
    { label: '图片总数', value: f.image_count, suffix: '张', color: '#1677ff' },
    { label: '缺陷图片', value: f.defect_image_count, suffix: '张', color: '#fa541c' },
    { label: '缺陷图占比', value: pct(f.defect_rate), suffix: '', color: '#fa8c16' },
    { label: '缺陷框总数', value: f.defect_count, suffix: '个', color: '#f5222d' },
    { label: '框密度(框/图)', value: f.box_density.toFixed(2), suffix: '', color: '#faad14' },
    { label: '入库案例', value: f.case_count, suffix: '条', color: '#722ed1' },
    { label: '高危类框数', value: f.high_risk_count, suffix: '个', color: '#eb2f96' },
    { label: '单图均耗时', value: f.avg_inference_ms.toFixed(0), suffix: 'ms', color: '#13c2c2' },
  ]
})

const classColumns = [
  { key: 'class_name', title: '类别' },
  { key: 'count', title: '案例数', width: 80 },
  { key: 'ratio', title: '占比' },
  { key: 'avg_confidence', title: '平均置信度', width: 110 },
]

/** className -> AI 逐类分析 */
const analysisMap = computed(() => {
  const m: Record<string, StructuredReport['narrative']['class_analysis'][number]> = {}
  report.value?.narrative.class_analysis.forEach((a) => {
    m[a.class_name] = a
  })
  return m
})

function formatTime(t?: string) {
  return t ? t.replace('T', ' ').slice(0, 19) : '-'
}

function renderPie() {
  if (!pieRef.value || !report.value) return
  if (!pieChart) pieChart = echarts.init(pieRef.value)
  pieChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}<br/>${p.value} 例 (${p.percent}%)`,
    },
    legend: { bottom: 0, type: 'scroll', textStyle: { fontSize: 11 } },
    series: [
      {
        type: 'pie',
        radius: ['38%', '66%'],
        center: ['50%', '44%'],
        data: report.value.class_stats.map((c) => ({
          name: c.class_name_cn,
          value: c.count,
          itemStyle: { color: classMeta(c.class_name).color },
        })),
        label: { formatter: '{b}\n{c} 例' },
      },
    ],
  })
}

function handleResize() {
  pieChart?.resize()
}

async function loadDetail() {
  loading.value = true
  reportError.value = ''
  try {
    detail.value = await getBatchDetail(batchId)
    const parsed = parseReport(detail.value)
    if (detail.value.reportJson && !parsed) {
      reportError.value = 'reportJson 无法解析, 请重新生成报告'
    }
    report.value = parsed
    if (parsed) {
      await nextTick()
      renderPie()
    }
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const msg = await generateReport(batchId)
    message.success(msg)
    await loadDetail()
  } catch {
    /* 拦截器已提示 */
  } finally {
    generating.value = false
  }
}

function handleExportExcel() {
  if (!report.value) return
  try {
    exportReportExcel(report.value)
    message.success('Excel 已开始下载')
  } catch (e) {
    message.error('Excel 导出失败: ' + (e as Error).message)
  }
}

async function handleExportPdf() {
  if (!captureRef.value || !report.value) return
  exportingPdf.value = true
  try {
    // 等待图片墙中的预签名图进入加载态, 降低截图缺图概率
    await new Promise((r) => setTimeout(r, 600))
    await exportReportPdf(captureRef.value, report.value)
    message.success('PDF 已开始下载')
  } catch (e) {
    message.error('PDF 导出失败: ' + (e as Error).message)
  } finally {
    exportingPdf.value = false
  }
}

function goBack() {
  router.push('/inspection/batches')
}

onMounted(loadDetail)

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  pieChart?.dispose()
})
</script>

<style scoped>
.report-capture {
  background: #f5f7fa;
  padding: 4px 0;
}
.report-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
  border-left: 4px solid #1677ff;
}
.report-title {
  font-size: 20px;
  font-weight: 700;
  color: #1f1f1f;
}
.report-sub {
  color: #888;
  font-size: 13px;
  margin-top: 4px;
}
.report-header-meta {
  text-align: right;
  font-size: 12px;
  color: #888;
  line-height: 1.9;
}
.fact-box {
  text-align: center;
  background: #fafafa;
  border-radius: 6px;
  padding: 12px 4px;
}
.fact-value {
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.fact-suffix {
  font-size: 12px;
  font-weight: 400;
  margin-left: 2px;
}
.fact-label {
  color: #888;
  font-size: 12px;
  margin-top: 4px;
}
.pie-chart {
  width: 100%;
  height: 300px;
}
.narrative-label {
  font-weight: 600;
  margin-bottom: 4px;
}
.class-analysis-card {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 10px 12px;
  height: 100%;
  background: #fcfcfd;
}
.class-analysis-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.class-analysis-stat {
  color: #999;
  font-size: 12px;
}
.class-analysis-card p {
  margin: 4px 0;
  font-size: 13px;
  line-height: 1.7;
}
.case-card {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}
.case-img {
  display: block;
  width: 100%;
  height: 120px;
  object-fit: cover;
  background: #f5f5f5;
}
.case-img-hidden {
  display: none;
}
.case-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px 0;
}
.case-score {
  font-size: 12px;
  color: #1677ff;
  font-variant-numeric: tabular-nums;
}
.case-sub {
  font-size: 11px;
  color: #999;
  padding: 0 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.report-footer {
  text-align: center;
  color: #aaa;
  font-size: 12px;
  margin: 20px 0 8px;
}
</style>
