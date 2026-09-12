/**
 * 阶段 4.3 结构化报告导出(纯前端生成, 无需后端文件服务):
 * - Excel: xlsx(SheetJS) 多 Sheet 工作簿, 全部数据来自 reportJson(程序事实, 防幻觉)
 * - PDF: html2canvas-pro 按页面真实渲染截图 -> jsPDF A4 分页, 中文由浏览器原生渲染,
 *   无需向服务端嵌入中文字体; MinIO 预签名图需允许跨域(已验证默认开启 GET CORS)
 */
import * as XLSX from 'xlsx'
import { jsPDF } from 'jspdf'
import html2canvas from 'html2canvas-pro'
import type { BatchDetailVO, StructuredReport } from '@/api/inspection'
import { severityMeta } from '@/utils/steel'

// 注: BatchDetailVO 仅用于 parseReport 入参约束, 导出本身只依赖结构化报告

/** 文件名安全化 + 时间戳 */
function fileBase(report: StructuredReport): string {
  const no = report.facts.batch_no || `batch-${report.facts.batch_id}`
  const safe = no.replace(/[\\/:*?"<>|]/g, '_')
  return `质检报告_${safe}_${report.generated_at.slice(0, 10)}`
}

export function exportReportExcel(report: StructuredReport) {
  const f = report.facts
  const n = report.narrative
  const sev = severityMeta(report.severity)

  // Sheet1 报告概览
  const overview: Array<[string, string | number]> = [
    ['报告版本', report.schema_version],
    ['生成时间', report.generated_at],
    ['生成模型', report.model],
    ['服务提供方', report.provider],
    ['批次编号', f.batch_no],
    ['批次名称', f.name],
    ['批次来源', f.source],
    ['检测模型', f.detect_model ?? '-'],
    ['程序定级', `${sev.label}(${report.severity})`],
    ['AI 复核定级', n.severity],
    ['AI 与规则定级分歧', report.severity_adjusted ? '是(建议人工复核)' : '否'],
    ['图片总数', f.image_count],
    ['缺陷图片数', f.defect_image_count],
    ['缺陷图占比', `${(f.defect_rate * 100).toFixed(2)}%`],
    ['缺陷框总数', f.defect_count],
    ['框密度(框/图)', f.box_density],
    ['入库案例数', f.case_count],
    ['高危类(裂纹+划痕)框数', f.high_risk_count],
    ['单图平均检测耗时(ms)', f.avg_inference_ms],
    ['Prompt Tokens', report.tokens.prompt_tokens],
    ['Completion Tokens', report.tokens.completion_tokens],
    ['总 Tokens', report.tokens.total_tokens],
    ['生成耗时(ms)', Math.round(report.latency_ms)],
  ]
  const wsOverview = XLSX.utils.aoa_to_sheet([
    ['SteelGuard 结构化质检报告 - 概览'],
    ...overview,
  ])
  wsOverview['!cols'] = [{ wch: 28 }, { wch: 42 }]

  // Sheet2 类别统计(附上 AI 逐类解读)
  const analysisByClass = new Map(n.class_analysis.map((a) => [a.class_name, a]))
  const classRows = report.class_stats.map((c) => {
    const a = analysisByClass.get(c.class_name)
    return {
      类别中文名: c.class_name_cn,
      类别标识: c.class_name,
      案例数: c.count,
      占比: `${(c.ratio * 100).toFixed(2)}%`,
      平均置信度: c.avg_confidence,
      AI表现解读: a?.finding ?? '',
      AI处置建议: a?.suggestion ?? '',
    }
  })
  const wsClass = XLSX.utils.json_to_sheet(classRows)
  wsClass['!cols'] = [
    { wch: 12 }, { wch: 16 }, { wch: 8 }, { wch: 10 },
    { wch: 12 }, { wch: 60 }, { wch: 60 },
  ]

  // Sheet3 相似历史案例(检索证据)
  const caseRows = report.similar_cases.map((s, i) => ({
    序号: i + 1,
    类别: s.class_name_cn || s.class_name,
    相似度: s.score,
    检测置信度: s.detect_confidence,
    所属历史批次: s.batch_no,
    图片名称: s.image_name,
    Milvus主键: s.milvus_pk,
    记录ID: s.record_id,
  }))
  const wsCases = XLSX.utils.json_to_sheet(
    caseRows.length ? caseRows : [{ 提示: '本报告无相似历史案例证据(基础设施降级或历史库为空)' }],
  )
  wsCases['!cols'] = [
    { wch: 6 }, { wch: 12 }, { wch: 10 }, { wch: 12 },
    { wch: 24 }, { wch: 28 }, { wch: 20 }, { wch: 10 },
  ]

  // Sheet4 结论与处置
  const dispositionRows: Array<[string, string]> = n.disposition.map(
    (d, i): [string, string] => [`处置建议${i + 1}`, d],
  )
  const conclusion: Array<[string, string]> = [
    ['总体评价', n.overall_assessment],
    ['严重度判定理由', n.severity_reason],
    ...dispositionRows,
    ['放行/返修风险研判', n.risk_summary],
  ]
  const wsConclusion = XLSX.utils.aoa_to_sheet([
    ['AI 结论与处置建议(仅文字由 qwen-plus 生成, 数字以概览/类别页为准)'],
    ...conclusion,
  ])
  wsConclusion['!cols'] = [{ wch: 20 }, { wch: 100 }]

  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, wsOverview, '报告概览')
  XLSX.utils.book_append_sheet(wb, wsClass, '类别统计')
  XLSX.utils.book_append_sheet(wb, wsCases, '相似案例')
  XLSX.utils.book_append_sheet(wb, wsConclusion, '结论与处置')
  XLSX.writeFile(wb, `${fileBase(report)}.xlsx`)
}

/**
 * 将报告 DOM 节点截图导出为 A4 纵向多页 PDF。
 * 跨域图片通过 useCORS 拉取(MinIO 已返回 Access-Control-Allow-Origin)。
 */
export async function exportReportPdf(
  element: HTMLElement,
  report: StructuredReport,
): Promise<void> {
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#f5f7fa',
    logging: false,
    windowWidth: element.scrollWidth,
  })

  const pdf = new jsPDF('p', 'mm', 'a4')
  const pageW = pdf.internal.pageSize.getWidth()
  const pageH = pdf.internal.pageSize.getHeight()
  const margin = 6
  const imgW = pageW - margin * 2
  const contentH = pageH - margin * 2
  const imgH = (canvas.height * imgW) / canvas.width
  const imgData = canvas.toDataURL('image/jpeg', 0.92)

  let heightLeft = imgH
  let position = margin
  pdf.addImage(imgData, 'JPEG', margin, position, imgW, imgH)
  heightLeft -= contentH
  while (heightLeft > 0) {
    position = margin - (imgH - heightLeft)
    pdf.addPage()
    pdf.addImage(imgData, 'JPEG', margin, position, imgW, imgH)
    heightLeft -= contentH
  }
  pdf.save(`${fileBase(report)}.pdf`)
}

/** 供按钮禁用态判断: 详情里报告原文可解析时才允许导出 */
export function parseReport(detail: BatchDetailVO): StructuredReport | null {
  if (!detail.reportJson) return null
  try {
    return JSON.parse(detail.reportJson) as StructuredReport
  } catch {
    return null
  }
}
