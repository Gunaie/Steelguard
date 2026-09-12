import request from './request'
import type { PageResult } from './dataset'

/** 批次列表行 */
export interface BatchVO {
  id: number
  batchNo: string
  name: string
  source: string
  status: string
  model?: string | null
  imageCount: number
  processedCount: number
  defectImageCount: number
  defectCount: number
  caseCount: number
  severity?: string | null
  totalInferenceMs?: number | null
  errorMsg?: string | null
  reported: number
  createTime?: string
}

/** 检测框(与 inspect_record.result_json 对齐) */
export interface RecordBBox {
  class_id: number
  class_name: string
  class_name_cn?: string
  confidence: number
  bbox: { x1: number; y1: number; x2: number; y2: number }
}

/** 批次详情中的单图记录 */
export interface RecordVO {
  id: number
  imageName: string
  width?: number
  height?: number
  model?: string | null
  inferenceMs?: number | null
  detCount: number
  resultJson?: string | null
  url?: string | null
}

/** 类别统计行(后端 Map 序列化, 数字可能是字符串) */
export interface ClassStat {
  className: string
  count: number
  avgConfidence: number
}

/** 批次详情 */
export interface BatchDetailVO extends Omit<BatchVO, 'createTime'> {
  createTime?: string
  classStats: ClassStat[]
  records: RecordVO[]
  totalRecords: number
  /** 4.2 结构化报告 JSON 原文(相似案例 URL 已由后端刷新签名) */
  reportJson?: string | null
  reportModel?: string | null
  llmTokens?: number | null
}

// ---------- 4.2 结构化报告(reportJson 解析后) ----------

export interface ReportFacts {
  batch_id: number
  batch_no: string
  name: string
  source: string
  detect_model?: string | null
  image_count: number
  defect_image_count: number
  defect_count: number
  case_count: number
  defect_rate: number
  box_density: number
  avg_inference_ms: number
  high_risk_count: number
  rule_severity: string
}

export interface ReportClassStat {
  class_name: string
  class_name_cn: string
  count: number
  ratio: number
  avg_confidence: number
}

export interface SimilarCase {
  case_id: number
  milvus_pk: string
  score: number
  class_name: string
  class_name_cn?: string
  detect_confidence: number
  record_id: number
  batch_id: number
  batch_no: string
  batch_name?: string
  image_name: string
  crop_url?: string | null
  source_image_url?: string | null
}

export interface ClassAnalysisItem {
  class_name: string
  finding: string
  suggestion: string
}

export interface ReportNarrative {
  overall_assessment: string
  severity: string
  severity_reason: string
  class_analysis: ClassAnalysisItem[]
  disposition: string[]
  risk_summary: string
}

export interface ReportTokens {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface StructuredReport {
  schema_version: string
  generated_at: string
  model: string
  provider: string
  severity: string
  severity_adjusted: boolean
  facts: ReportFacts
  class_stats: ReportClassStat[]
  similar_cases: SimilarCase[]
  narrative: ReportNarrative
  tokens: ReportTokens
  latency_ms: number
}

/** 趋势看板 */
export interface DailyCount {
  date: string
  count: number
}

export interface DefectTrend {
  days: number
  fromDate: string
  totalBatches: number
  doneBatches: number
  totalImages: number
  totalDefectImages: number
  defectImageRate: number
  totalCases: number
  avgConfidence: number
  classDistribution: ClassStat[]
  severityDistribution: Array<{ severity: string | null; count: number }>
  daily: DailyCount[]
}

export interface BatchPageQuery {
  page?: number
  size?: number
  status?: string
}

export interface CreateDatasetBatchBody {
  name: string
  sampleCount: number
  classNames?: string[]
  seed?: number
}

/** 批次分页 */
export function pageBatches(params: BatchPageQuery) {
  return request.get<unknown, PageResult<BatchVO>>('/inspection/batches', { params })
}

/** 数据集抽样建批 */
export function createDatasetBatch(body: CreateDatasetBatchBody) {
  return request.post<unknown, BatchVO>('/inspection/batches/dataset', body)
}

/** 现场上传建批 */
export function uploadBatch(name: string, files: File[]) {
  const form = new FormData()
  form.append('name', name)
  files.forEach((f) => form.append('files', f))
  return request.post<unknown, BatchVO>('/inspection/batches/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

/** 启动异步跑批 */
export function runBatch(id: number) {
  return request.post<unknown, string>(`/inspection/batches/${id}/run`)
}

/** 批次详情(含 reportJson) */
export function getBatchDetail(id: number, limit = 100) {
  return request.get<unknown, BatchDetailVO>(`/inspection/batches/${id}`, {
    params: { limit },
  })
}

/** 生成/重新生成结构化报告(qwen-plus, 18s 量级, 长尾留 3 分钟) */
export function generateReport(id: number) {
  return request.post<unknown, string>(`/inspection/batches/${id}/report`, null, {
    timeout: 180000,
  })
}

/** 缺陷趋势看板 */
export function getDefectTrend(days: number) {
  return request.get<unknown, DefectTrend>('/inspection/stats/trend', {
    params: { days },
  })
}
