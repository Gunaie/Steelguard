import request from './request'

/** 数据集版本 */
export interface DatasetVersion {
  id: number
  version: string
  datasetName: string
  source: string
  imageCount: number
  annotationCount: number
  augmentFactor: number
  totalCount: number
  status: string
  remark?: string
  createTime?: string
}

export interface ClassCountItem {
  className: string
  imageCount: number
  bboxCount: number
}

export interface BboxCountItem {
  bboxCount: number
  imageCount: number
}

export interface MethodCountItem {
  augmentMethod: string | null
  imageCount: number
}

export interface DatasetEda {
  versionId: number
  version: string
  status: string
  totalImages: number
  totalAnnotations: number
  avgBboxesPerImage: number
  classDistribution: ClassCountItem[]
  bboxPerImageDistribution: BboxCountItem[]
  augmentMethodDistribution: MethodCountItem[]
  imageSize: Record<string, number | number[]>
  bboxSize: Record<string, number>
}

export interface DatasetImage {
  id: number
  fileName: string
  className: string
  width: number
  height: number
  split: string
  augmentMethod?: string | null
  fileSize: number
  url: string
}

export interface PageResult<T> {
  total: number
  page: number
  size: number
  list: T[]
}

export interface ImageQuery {
  versionId?: number
  className?: string
  split?: string
  page?: number
  size?: number
}

/** 版本列表 */
export function getVersions() {
  return request.get<unknown, DatasetVersion[]>('/dataset/versions')
}

/** EDA 统计 */
export function getEda(versionId?: number) {
  return request.get<unknown, DatasetEda>('/dataset/eda', {
    params: versionId ? { versionId } : {},
  })
}

/** 图片分页 */
export function getImages(params: ImageQuery) {
  return request.get<unknown, PageResult<DatasetImage>>('/dataset/images', { params })
}
