<template>
  <div class="dataset-page">
    <!-- 版本切换 -->
    <a-card :bordered="false" style="margin-bottom: 16px">
      <a-space wrap>
        <span style="font-weight: 600">数据集版本：</span>
        <a-radio-group
          v-model:value="versionId"
          button-style="solid"
          @change="onVersionChange"
        >
          <a-radio-button v-for="v in versions" :key="v.id" :value="v.id">
            {{ v.version }}
            <a-tag
              :color="v.status === 'ready' ? 'green' : 'orange'"
              style="margin-left: 6px"
            >{{ v.status }}</a-tag>
          </a-radio-button>
        </a-radio-group>
        <a-tag color="blue">{{ eda?.totalImages }} 图</a-tag>
      </a-space>
      <div v-if="currentVersion" class="version-remark">
        {{ currentVersion.remark }} · 来源：{{ currentVersion.source }}
      </div>
    </a-card>

    <!-- 统计卡片 -->
    <a-row :gutter="16">
      <a-col :span="6">
        <a-card :loading="edaLoading">
          <a-statistic title="图片总数" :value="eda?.totalImages ?? 0" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card :loading="edaLoading">
          <a-statistic title="标注框总数" :value="eda?.totalAnnotations ?? 0" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card :loading="edaLoading">
          <a-statistic
            title="平均每图框数"
            :value="eda?.avgBboxesPerImage ?? 0"
            :precision="2"
          />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card :loading="edaLoading">
          <a-statistic title="增强倍数" :value="currentVersion?.augmentFactor ?? 1" suffix="×" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 图表区(注意: 不用 a-card :loading, 骨架屏会销毁图表 div 导致 echarts 实例游离;
         a-spin 只加遮罩不替换 DOM) -->
    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :span="12">
        <a-card title="六类缺陷分布（图片数 / 标注框数）">
          <a-spin :spinning="edaLoading">
            <div ref="classChartRef" class="chart"></div>
          </a-spin>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card title="每图框数分布">
          <a-spin :spinning="edaLoading">
            <div ref="bboxChartRef" class="chart"></div>
          </a-spin>
        </a-card>
      </a-col>
    </a-row>
    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :span="12">
        <a-card title="增强方式分布">
          <a-spin :spinning="edaLoading">
            <div ref="methodChartRef" class="chart"></div>
          </a-spin>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card title="图像 / 标注框尺寸统计">
          <a-descriptions :column="1" size="small" bordered>
            <a-descriptions-item label="图像尺寸">
              {{ eda?.imageSize?.widthMin }} × {{ eda?.imageSize?.heightMin }}
              <template v-if="eda?.imageSize?.widthMax !== eda?.imageSize?.widthMin">
                ~ {{ eda?.imageSize?.widthMax }} × {{ eda?.imageSize?.heightMax }}
              </template>
              像素，灰度通道 {{ (eda?.imageSize?.depths as number[])?.join('/') }}
            </a-descriptions-item>
            <a-descriptions-item label="框宽（像素）">
              min {{ eda?.bboxSize?.widthMin }} ／ max {{ eda?.bboxSize?.widthMax }}
              ／ 均值 {{ eda?.bboxSize?.widthAvg }}
            </a-descriptions-item>
            <a-descriptions-item label="框高（像素）">
              min {{ eda?.bboxSize?.heightMin }} ／ max {{ eda?.bboxSize?.heightMax }}
              ／ 均值 {{ eda?.bboxSize?.heightAvg }}
            </a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
    </a-row>

    <!-- 缩略图画廊 -->
    <a-card title="数据画廊（MinIO 预签名）" style="margin-top: 16px">
      <template #extra>
        <a-space wrap>
          <a-select
            v-model:value="className"
            style="width: 160px"
            allow-clear
            placeholder="全部类别"
            @change="reloadImages"
          >
            <a-select-option v-for="c in CLASS_OPTIONS" :key="c.value" :value="c.value">
              {{ c.label }}
            </a-select-option>
          </a-select>
          <a-radio-group v-model:value="split" button-style="solid" @change="reloadImages">
            <a-radio-button value="">全部</a-radio-button>
            <a-radio-button value="raw">原始</a-radio-button>
            <a-radio-button value="augmented">增强</a-radio-button>
          </a-radio-group>
        </a-space>
      </template>

      <a-spin :spinning="imgLoading">
        <div class="gallery">
          <div v-for="img in images" :key="img.id" class="gallery-item">
            <a-image
              :src="img.url || ''"
              :width="160"
              :height="160"
              class="gallery-img"
            />
            <div class="gallery-meta">
              <a-tag :color="splitTagColor(img.split)">{{ splitLabel(img.split) }}</a-tag>
              <a-tag>{{ classLabel(img.className) }}</a-tag>
            </div>
            <div class="gallery-name" :title="img.fileName">{{ img.fileName }}</div>
            <div v-if="img.augmentMethod" class="gallery-method">
              {{ methodLabel(img.augmentMethod) }}
            </div>
          </div>
          <a-empty v-if="!imgLoading && images.length === 0" style="width: 100%" />
        </div>
      </a-spin>

      <a-pagination
        style="margin-top: 16px; text-align: right"
        :current="page"
        :page-size="size"
        :total="total"
        show-size-changer
        :page-size-options="['12', '24', '48']"
        @change="onPageChange"
        @show-size-change="onSizeChange"
      />
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import {
  getEda,
  getImages,
  getVersions,
  type DatasetEda,
  type DatasetImage,
  type DatasetVersion,
} from '@/api/dataset'

// 6 类标准类名 -> 中文
const CLASS_OPTIONS = [
  { value: 'crazing', label: '裂纹 crazing' },
  { value: 'inclusion', label: '夹杂 inclusion' },
  { value: 'patches', label: '斑块 patches' },
  { value: 'pitted_surface', label: '麻点 pitted_surface' },
  { value: 'rolled-in_scale', label: '轧入氧化皮 rolled-in_scale' },
  { value: 'scratches', label: '划痕 scratches' },
]
const classLabel = (v: string) => CLASS_OPTIONS.find((c) => c.value === v)?.label ?? v
const METHOD_LABELS: Record<string, string> = {
  horizontal_flip: '水平翻转',
  vertical_flip: '垂直翻转',
  rotate: '旋转 ±15°',
  brightness_contrast: '亮度对比度',
}
const methodLabel = (v?: string | null) => (v ? METHOD_LABELS[v] ?? v : '原图')
const splitLabel = (v: string) => (v === 'raw' ? '原始' : '增强')
const splitTagColor = (v: string) => (v === 'raw' ? 'blue' : 'purple')

const versions = ref<DatasetVersion[]>([])
const versionId = ref<number>()
const eda = ref<DatasetEda | null>(null)
const edaLoading = ref(false)
const images = ref<DatasetImage[]>([])
const imgLoading = ref(false)
const className = ref<string>()
const split = ref('')
const page = ref(1)
const size = ref(12)
const total = ref(0)

const currentVersion = computed(() =>
  versions.value.find((v) => v.id === versionId.value),
)

// ---------- ECharts ----------
const classChartRef = ref<HTMLElement>()
const bboxChartRef = ref<HTMLElement>()
const methodChartRef = ref<HTMLElement>()
let classChart: echarts.ECharts | null = null
let bboxChart: echarts.ECharts | null = null
let methodChart: echarts.ECharts | null = null

function renderClassChart() {
  if (!classChart || !eda.value) return
  const names = eda.value.classDistribution.map((c) => classLabel(c.className))
  classChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['图片数', '标注框数'], bottom: 0 },
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
    xAxis: { type: 'category', data: names, axisLabel: { interval: 0, rotate: 18, fontSize: 10 } },
    yAxis: { type: 'value' },
    series: [
      {
        name: '图片数',
        type: 'bar',
        data: eda.value.classDistribution.map((c) => c.imageCount),
        itemStyle: { color: '#1677ff' },
      },
      {
        name: '标注框数',
        type: 'bar',
        data: eda.value.classDistribution.map((c) => c.bboxCount),
        itemStyle: { color: '#fa8c16' },
      },
    ],
  })
}

function renderBboxChart() {
  if (!bboxChart || !eda.value) return
  const d = eda.value.bboxPerImageDistribution
  bboxChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', name: '框/图', data: d.map((x) => x.bboxCount) },
    yAxis: { type: 'value', name: '图片数' },
    series: [
      {
        type: 'bar',
        data: d.map((x) => x.imageCount),
        itemStyle: { color: '#52c41a' },
      },
    ],
  })
}

function renderMethodChart() {
  if (!methodChart || !eda.value) return
  const d = eda.value.augmentMethodDistribution
  methodChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['38%', '65%'],
        center: ['50%', '45%'],
        data: d.map((x) => ({
          name: x.augmentMethod ? methodLabel(x.augmentMethod) : '原图',
          value: x.imageCount,
        })),
        label: { formatter: '{b}\n{c} 张' },
      },
    ],
  })
}

function renderAllCharts() {
  nextTick(() => {
    renderClassChart()
    renderBboxChart()
    renderMethodChart()
  })
}

function handleResize() {
  classChart?.resize()
  bboxChart?.resize()
  methodChart?.resize()
}

// ---------- 数据加载 ----------
async function loadVersions() {
  versions.value = await getVersions()
  if (versions.value.length && versionId.value === undefined) {
    versionId.value = versions.value[0].id
  }
}

async function loadEda() {
  if (!versionId.value) return
  edaLoading.value = true
  try {
    eda.value = await getEda(versionId.value)
    renderAllCharts()
  } finally {
    edaLoading.value = false
  }
}

async function loadImages() {
  if (!versionId.value) return
  imgLoading.value = true
  try {
    const res = await getImages({
      versionId: versionId.value,
      className: className.value,
      split: split.value || undefined,
      page: page.value,
      size: size.value,
    })
    images.value = res.list
    total.value = Number(res.total)
  } finally {
    imgLoading.value = false
  }
}

function onVersionChange() {
  page.value = 1
  className.value = undefined
  split.value = ''
  loadEda()
  loadImages()
}

function reloadImages() {
  page.value = 1
  loadImages()
}

function onPageChange(p: number) {
  page.value = p
  loadImages()
}

function onSizeChange(_p: number, s: number) {
  size.value = s
  page.value = 1
  loadImages()
}

onMounted(async () => {
  classChart = echarts.init(classChartRef.value)
  bboxChart = echarts.init(bboxChartRef.value)
  methodChart = echarts.init(methodChartRef.value)
  window.addEventListener('resize', handleResize)
  await loadVersions()
  await Promise.all([loadEda(), loadImages()])
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  classChart?.dispose()
  bboxChart?.dispose()
  methodChart?.dispose()
})
</script>

<style scoped>
.chart {
  width: 100%;
  height: 300px;
}
.version-remark {
  margin-top: 8px;
  color: #999;
  font-size: 12px;
}
.gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.gallery-item {
  width: 160px;
}
.gallery-img {
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  object-fit: cover;
}
.gallery-meta {
  margin-top: 4px;
}
.gallery-name {
  font-size: 12px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gallery-method {
  font-size: 11px;
  color: #999;
}
</style>
