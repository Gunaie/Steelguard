/** SteelGuard 六类缺陷/严重度/批次状态的统一展示元数据(前端唯一映射源) */

export interface ClassMeta {
  value: string
  label: string
  color: string
}

export const CLASS_OPTIONS: ClassMeta[] = [
  { value: 'crazing', label: '裂纹', color: '#f5222d' },
  { value: 'inclusion', label: '夹杂', color: '#fa8c16' },
  { value: 'patches', label: '斑块', color: '#faad14' },
  { value: 'pitted_surface', label: '麻点', color: '#52c41a' },
  { value: 'rolled-in_scale', label: '氧化皮', color: '#13c2c2' },
  { value: 'scratches', label: '划痕', color: '#2f54eb' },
]

export function classMeta(name?: string | null): ClassMeta {
  return (
    CLASS_OPTIONS.find((c) => c.value === name) ?? {
      value: name ?? '',
      label: name ?? '未知',
      color: '#8c8c8c',
    }
  )
}

export function classCn(name?: string | null): string {
  return classMeta(name).label
}

export function classColor(name?: string | null): string {
  return classMeta(name).color
}

/** 严重度 -> 中文 + Ant Design 标签色 */
export function severityMeta(sev?: string | null): { label: string; color: string } {
  switch (sev) {
    case 'critical':
      return { label: '紧急', color: 'red' }
    case 'high':
      return { label: '高风险', color: 'volcano' }
    case 'medium':
      return { label: '中风险', color: 'orange' }
    case 'low':
      return { label: '低风险', color: 'green' }
    default:
      return { label: sev || '未定级', color: 'default' }
  }
}

/** 批次来源 */
export function sourceMeta(source?: string | null): { label: string; color: string } {
  switch (source) {
    case 'dataset':
      return { label: '数据集抽样', color: 'blue' }
    case 'upload':
      return { label: '现场上传', color: 'purple' }
    case 'history':
      return { label: '历史基线', color: 'cyan' }
    default:
      return { label: source || '-', color: 'default' }
  }
}

/** 批次状态 */
export function statusMeta(status?: string | null): { label: string; color: string } {
  switch (status) {
    case 'pending':
      return { label: '待处理', color: 'default' }
    case 'detecting':
      return { label: '检测中', color: 'processing' }
    case 'done':
      return { label: '已完成', color: 'success' }
    case 'failed':
      return { label: '失败', color: 'error' }
    default:
      return { label: status || '-', color: 'default' }
  }
}

/** 0-1 比例 -> 百分比文本, 默认 1 位小数 */
export function pct(v?: number | null, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return `${(v * 100).toFixed(digits)}%`
}
