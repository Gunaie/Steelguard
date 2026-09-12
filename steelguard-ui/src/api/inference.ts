import request from './request'

/** 检测框(像素绝对坐标) */
export interface BBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

/** 单个缺陷检测结果(字段与 Python/Java 网关严格对齐) */
export interface Detection {
  class_id: number
  class_name: string
  class_name_cn: string
  confidence: number
  bbox: BBox
}

/** YOLO 检测响应 */
export interface DetectResponse {
  model: string
  device: string
  image_width: number
  image_height: number
  inference_ms: number
  count: number
  detections: Detection[]
}

/** Qwen-VL token 用量 */
export interface VlTokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

/** Qwen-VL 零样本检测响应(无 device, 多 provider/tokens) */
export interface VlDetectResponse {
  model: string
  provider: string
  image_width: number
  image_height: number
  inference_ms: number
  count: number
  detections: Detection[]
  tokens: VlTokenUsage
}

/** 上传图片做缺陷检测(Java 网关 -> Python FastAPI -> GPU) */
export function detect(file: File, conf = 0.25, iou = 0.7) {
  const form = new FormData()
  form.append('file', file)
  form.append('conf', String(conf))
  form.append('iou', String(iou))
  return request.post<unknown, DetectResponse>('/inference/detect', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000, // 首次/冷启动留余量
  })
}

/**
 * 上传图片做 Qwen-VL 零样本检测(Java 网关 -> Python -> 阿里云百炼)
 * @param model 可选: plus(默认, 快且省) / max(更慢更贵)
 */
export function detectVl(file: File, model?: string) {
  const form = new FormData()
  form.append('file', file)
  if (model) form.append('model', model)
  return request.post<unknown, VlDetectResponse>('/inference/detect-vl', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000, // 云端 VLM 存在 60s+ 长尾, Python 侧还会重试一次
  })
}
