<template>
  <div>
    <a-card title="钢材表面缺陷检测 · YOLO vs Qwen-VL 对决" :bordered="false">
      <a-alert
        type="info"
        show-icon
        style="margin-bottom: 16px"
        message="同一张图分别由 YOLOv11s(GPU 本地, 监督训练) 与 Qwen-VL(云端零样本) 检测, 并排对比画框、速度与成本"
      />
      <a-row :gutter="16">
        <!-- 左: 上传 + 参数 -->
        <a-col :xs="24" :md="9">
          <a-upload-dragger
            :before-upload="handleBeforeUpload"
            :show-upload-list="false"
            accept="image/jpeg,image/png,image/webp"
            :disabled="loadingYolo || loadingVl"
          >
            <p class="ant-upload-drag-icon"><inbox-outlined /></p>
            <p class="ant-upload-text">点击或拖拽图片到此处上传</p>
            <p class="ant-upload-hint">支持 JPG / PNG / WEBP, 单张 ≤ 10MB</p>
          </a-upload-dragger>

          <a-card title="检测参数" size="small" style="margin-top: 12px">
            <div style="display: flex; align-items: center; gap: 12px">
              <span style="white-space: nowrap">YOLO 置信度</span>
              <a-slider v-model:value="conf" :min="0.05" :max="0.9" :step="0.05"
                        style="flex: 1" :disabled="loadingYolo || loadingVl" />
              <a-tag color="blue">{{ conf.toFixed(2) }}</a-tag>
            </div>
            <div style="display: flex; align-items: center; gap: 12px; margin-top: 8px">
              <span style="white-space: nowrap">YOLO NMS IoU</span>
              <a-slider v-model:value="iou" :min="0.3" :max="0.9" :step="0.05"
                        style="flex: 1" :disabled="loadingYolo || loadingVl" />
              <a-tag color="blue">{{ iou.toFixed(2) }}</a-tag>
            </div>
            <div style="display: flex; align-items: center; gap: 12px; margin-top: 8px">
              <span style="white-space: nowrap">VL 模型</span>
              <a-radio-group v-model:value="vlModel" size="small" button-style="solid"
                             :disabled="loadingYolo || loadingVl">
                <a-radio-button value="plus">qwen-vl-plus(快/省)</a-radio-button>
                <a-radio-button value="max">qwen-vl-max(慢/贵)</a-radio-button>
              </a-radio-group>
            </div>

            <a-space style="margin-top: 12px">
              <a-button type="primary" :loading="loadingYolo || loadingVl"
                        :disabled="!currentFile" @click="runDuel">
                <template #icon><thunderbolt-outlined /></template>
                双模型对决
              </a-button>
              <a-upload :before-upload="handleBeforeUpload" :show-upload-list="false" accept="image/*">
                <a-button :disabled="loadingYolo || loadingVl">换一张</a-button>
              </a-upload>
            </a-space>
          </a-card>
        </a-col>

        <!-- 右: 双画框并排 -->
        <a-col :xs="24" :md="15">
          <a-row v-if="imageUrl" :gutter="12">
            <!-- YOLO 画框 -->
            <a-col :xs="24" :md="12">
              <a-card size="small" :body-style="{ padding: '8px' }">
                <template #title>
                  <span style="font-size: 14px">YOLOv11s</span>
                  <a-tag color="geekblue" style="margin-left: 8px">监督训练</a-tag>
                </template>
                <template #extra><span style="font-size: 12px; color: #999">实线框</span></template>
                <a-spin :spinning="loadingYolo" tip="GPU 推理中...">
                  <div class="image-stage">
                    <img ref="yoloImgRef" :src="imageUrl" class="source-img"
                         @load="drawStage('yolo')" />
                    <canvas ref="yoloCanvasRef" class="box-canvas"></canvas>
                  </div>
                  <div class="stage-meta">
                    <a-tag v-if="yoloResult">检出 {{ yoloResult.count }} 个</a-tag>
                    <a-tag v-if="yoloResult" color="green">{{ yoloResult.inference_ms }} ms</a-tag>
                    <a-tag v-if="yoloResult" color="blue">{{ yoloResult.device }}</a-tag>
                    <a-tag v-else-if="!loadingYolo" color="red">检测失败</a-tag>
                  </div>
                </a-spin>
              </a-card>
            </a-col>

            <!-- Qwen-VL 画框 -->
            <a-col :xs="24" :md="12" class="vl-stage-col">
              <a-card size="small" :body-style="{ padding: '8px' }">
                <template #title>
                  <span style="font-size: 14px">Qwen-VL</span>
                  <a-tag color="purple" style="margin-left: 8px">零样本</a-tag>
                </template>
                <template #extra>
                  <a-space :size="4">
                    <span style="font-size: 12px; color: #999">虚线框</span>
                    <a-button type="link" size="small" :loading="loadingVl"
                              :disabled="!currentFile" @click="runVlOnly">重跑</a-button>
                  </a-space>
                </template>
                <a-spin :spinning="loadingVl" tip="云端大模型推理中...">
                  <div class="image-stage">
                    <img ref="vlImgRef" :src="imageUrl" class="source-img"
                         @load="drawStage('vl')" />
                    <canvas ref="vlCanvasRef" class="box-canvas"></canvas>
                  </div>
                  <div class="stage-meta">
                    <template v-if="vlResult">
                      <a-tag>检出 {{ vlResult.count }} 个</a-tag>
                      <a-tag :color="vlResult.inference_ms > 10000 ? 'orange' : 'green'">
                        {{ (vlResult.inference_ms / 1000).toFixed(1) }} s
                      </a-tag>
                      <a-tag color="purple">{{ vlResult.tokens.total_tokens }} tok</a-tag>
                      <a-tag color="gold">≈ ¥{{ vlCost(vlResult) }}</a-tag>
                    </template>
                    <a-tag v-else-if="vlError" color="red">{{ vlError }}</a-tag>
                  </div>
                </a-spin>
              </a-card>
            </a-col>
          </a-row>
          <a-empty v-else description="上传图片后展示双模型对决结果" style="margin-top: 48px" />
        </a-col>
      </a-row>

      <!-- 双模型检测明细 -->
      <a-row v-if="imageUrl" :gutter="16" style="margin-top: 16px">
        <a-col :xs="24" :md="12">
          <a-card title="YOLO 检测明细" size="small">
            <a-empty v-if="!yoloResult && !loadingYolo" description="暂无结果" />
            <a-result v-else-if="yoloResult && yoloResult.detections.length === 0"
                      status="success" title="未检出缺陷" :sub-title="`模型 ${yoloResult.model}`" />
            <a-list v-else-if="yoloResult" size="small" :data-source="yoloResult.detections">
              <template #renderItem="{ item, index }">
                <a-list-item>
                  <a-list-item-meta>
                    <template #avatar>
                      <a-tag :color="CLASS_COLORS[item.class_name] || 'default'" style="margin: 0">#{{ index + 1 }}</a-tag>
                    </template>
                    <template #title>
                      {{ item.class_name_cn }}
                      <span style="color: #999; font-size: 12px">({{ item.class_name }})</span>
                    </template>
                    <template #description>
                      <a-progress :percent="Math.round(item.confidence * 100)" size="small"
                                  :stroke-color="CLASS_COLORS[item.class_name]" />
                    </template>
                  </a-list-item-meta>
                  <template #actions>
                    <span style="font-variant-numeric: tabular-nums">{{ (item.confidence * 100).toFixed(1) }}%</span>
                  </template>
                </a-list-item>
              </template>
            </a-list>
          </a-card>
        </a-col>

        <a-col :xs="24" :md="12">
          <a-card title="Qwen-VL 检测明细" size="small">
            <a-empty v-if="!vlResult && !loadingVl" :description="vlError || '暂无结果'" />
            <a-result v-else-if="vlResult && vlResult.detections.length === 0"
                      status="success" title="未检出缺陷" :sub-title="`模型 ${vlResult.model}`" />
            <a-list v-else-if="vlResult" size="small" :data-source="vlResult.detections">
              <template #renderItem="{ item, index }">
                <a-list-item>
                  <a-list-item-meta>
                    <template #avatar>
                      <a-tag :color="CLASS_COLORS[item.class_name] || 'default'" style="margin: 0">V{{ index + 1 }}</a-tag>
                    </template>
                    <template #title>
                      {{ item.class_name_cn }}
                      <span style="color: #999; font-size: 12px">({{ item.class_name }})</span>
                    </template>
                    <template #description>
                      <a-progress :percent="Math.round(item.confidence * 100)" size="small"
                                  :stroke-color="CLASS_COLORS[item.class_name]" />
                    </template>
                  </a-list-item-meta>
                  <template #actions>
                    <span style="font-variant-numeric: tabular-nums">{{ (item.confidence * 100).toFixed(1) }}%</span>
                  </template>
                </a-list-item>
              </template>
            </a-list>
          </a-card>
        </a-col>
      </a-row>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { InboxOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import {
  detect,
  detectVl,
  type DetectResponse,
  type VlDetectResponse,
  type Detection,
} from '@/api/inference'

// 6 类固定配色(与类别字母序无关, 仅用于前端可视化)
const CLASS_COLORS: Record<string, string> = {
  crazing: '#f5222d',
  inclusion: '#fa8c16',
  patches: '#faad14',
  pitted_surface: '#52c41a',
  rolled_in_scale: '#13c2c2',
  scratches: '#2f54eb',
}

// qwen-vl-plus 官方单价(元/百万 token, 2026-09): 输入 0.8 / 输出 2
function vlCost(r: VlDetectResponse): string {
  const cny = (r.tokens.prompt_tokens * 0.8 + r.tokens.completion_tokens * 2) / 1_000_000
  return cny.toFixed(4)
}

const loadingYolo = ref(false)
const loadingVl = ref(false)
const imageUrl = ref('')
const currentFile = ref<File | null>(null)
const conf = ref(0.25)
const iou = ref(0.7)
const vlModel = ref<'plus' | 'max'>('plus')
const yoloResult = ref<DetectResponse | null>(null)
const vlResult = ref<VlDetectResponse | null>(null)
const vlError = ref('')

const yoloImgRef = ref<HTMLImageElement | null>(null)
const yoloCanvasRef = ref<HTMLCanvasElement | null>(null)
const vlImgRef = ref<HTMLImageElement | null>(null)
const vlCanvasRef = ref<HTMLCanvasElement | null>(null)

function beforeUploadCheck(file: UploadFile): boolean {
  if (!file.type?.startsWith('image/')) {
    message.error('仅支持图片文件')
    return false
  }
  if (file.size && file.size > 10 * 1024 * 1024) {
    message.error('图片不能超过 10MB')
    return false
  }
  return true
}

function handleBeforeUpload(file: UploadFile) {
  if (!beforeUploadCheck(file)) return false
  currentFile.value = file as unknown as File
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = URL.createObjectURL(file as unknown as File)
  yoloResult.value = null
  vlResult.value = null
  vlError.value = ''
  runDuel()
  return false // 阻止组件自动上传
}

async function runDuel() {
  if (!currentFile.value) return
  const f = currentFile.value
  loadingYolo.value = true
  loadingVl.value = true
  yoloResult.value = null
  vlResult.value = null
  vlError.value = ''

  // 两模型互不阻塞: 任一失败不影响另一侧展示
  const yoloTask = detect(f, conf.value, iou.value)
    .then((r) => {
      yoloResult.value = r
      drawStage('yolo')
    })
    .catch((e: unknown) => {
      message.error('YOLO 检测失败: ' + (e as Error)?.message)
    })
    .finally(() => {
      loadingYolo.value = false
    })

  const vlTask = detectVl(f, vlModel.value)
    .then((r) => {
      vlResult.value = r
      drawStage('vl')
    })
    .catch((e: unknown) => {
      vlError.value = 'VL 检测失败'
      message.error('Qwen-VL 检测失败: ' + (e as Error)?.message)
    })
    .finally(() => {
      loadingVl.value = false
    })

  await Promise.allSettled([yoloTask, vlTask])
}

async function runVlOnly() {
  if (!currentFile.value) return
  loadingVl.value = true
  vlResult.value = null
  vlError.value = ''
  try {
    vlResult.value = await detectVl(currentFile.value, vlModel.value)
    drawStage('vl')
  } catch (e: unknown) {
    vlError.value = 'VL 检测失败'
    message.error('Qwen-VL 检测失败: ' + (e as Error)?.message)
  } finally {
    loadingVl.value = false
  }
}

/** 在指定画布上按显示比例叠加检测框(vl 使用虚线区分) */
function drawStage(kind: 'yolo' | 'vl') {
  const canvas = kind === 'yolo' ? yoloCanvasRef.value : vlCanvasRef.value
  const img = kind === 'yolo' ? yoloImgRef.value : vlImgRef.value
  const res = kind === 'yolo' ? yoloResult.value : vlResult.value
  if (!canvas || !img || !res || !img.clientWidth || !img.clientHeight) return

  const dpr = window.devicePixelRatio || 1
  const cssW = img.clientWidth
  const cssH = img.clientHeight
  canvas.width = cssW * dpr
  canvas.height = cssH * dpr
  canvas.style.width = `${cssW}px`
  canvas.style.height = `${cssH}px`

  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, cssW, cssH)

  const sx = cssW / res.image_width
  const sy = cssH / res.image_height
  const lineWidth = Math.max(1.5, Math.min(cssW, cssH) / 120)
  const fontSize = Math.max(11, Math.min(cssW, cssH) / 16)

  // 已放置标签矩形, 用于相邻标签碰撞避让(防止互相遮挡文字)
  const placed: Array<{ x: number; y: number; w: number; h: number }> = []

  res.detections.forEach((d: Detection, idx: number) => {
    const color = CLASS_COLORS[d.class_name] || '#f5222d'
    const x = d.bbox.x1 * sx
    const y = d.bbox.y1 * sy
    const w = (d.bbox.x2 - d.bbox.x1) * sx
    const h = (d.bbox.y2 - d.bbox.y1) * sy

    ctx.lineWidth = lineWidth
    ctx.strokeStyle = color
    // Qwen-VL 一律虚线框, 与 YOLO 实线框视觉区分
    ctx.setLineDash(kind === 'vl' ? [6, 4] : [])
    ctx.strokeRect(x, y, w, h)
    ctx.setLineDash([])

    const prefix = kind === 'vl' ? `V${idx + 1}` : `${idx + 1}`
    const label = `${prefix} ${d.class_name_cn} ${(d.confidence * 100).toFixed(0)}%`
    ctx.font = `${fontSize}px sans-serif`
    const tw = Math.min(ctx.measureText(label).width + 8, cssW)
    const th = fontSize + 6
    // 右缘越界时标签左移到画布内, 避免文字被 canvas 裁切
    const lx = Math.max(0, Math.min(x, cssW - tw))
    // 首选框顶上方, 顶部越界则放框内; 与已绘制标签重叠时逐行下移避让
    let ly = y - th >= 0 ? y - th : y
    for (let guard = 0; guard < 8; guard++) {
      const hit = placed.some(
        (p) => lx < p.x + p.w && lx + tw > p.x && ly < p.y + p.h && ly + th > p.y,
      )
      if (!hit) break
      ly += th + 2
    }
    // 下移超出画布时贴底保底
    if (ly + th > cssH) ly = Math.max(0, cssH - th)
    placed.push({ x: lx, y: ly, w: tw, h: th })

    ctx.fillStyle = color
    ctx.fillRect(lx, ly, tw, th)
    ctx.fillStyle = '#fff'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, lx + 4, ly + th / 2 + 0.5)
  })
}
</script>

<style scoped>
.image-stage {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #f5f5f5;
  border-radius: 4px;
  min-height: 200px;
  line-height: 0;
}
.source-img {
  max-width: 100%;
  max-height: 420px;
  image-rendering: pixelated;
}
.box-canvas {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  pointer-events: none;
}
.stage-meta {
  margin-top: 8px;
  min-height: 24px;
  text-align: center;
}
/* 窄屏两个画框卡片上下堆叠时留间距; ≥md(768px) 并排时取消 */
.vl-stage-col {
  margin-top: 12px;
}
@media (min-width: 768px) {
  .vl-stage-col {
    margin-top: 0;
  }
}
</style>
