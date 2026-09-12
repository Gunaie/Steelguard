<template>
  <div>
    <a-card :bordered="false">
      <template #title>
        <a-space>
          <span>质检批次</span>
          <a-tag color="blue">YOLO 跑批</a-tag>
          <a-tag color="purple" v-if="detectingCount">检测中 {{ detectingCount }}</a-tag>
        </a-space>
      </template>
      <template #extra>
        <a-space wrap>
          <a-radio-group v-model:value="statusFilter" button-style="solid" size="small"
                          @change="reload(1)">
            <a-radio-button value="">全部</a-radio-button>
            <a-radio-button value="pending">待处理</a-radio-button>
            <a-radio-button value="detecting">检测中</a-radio-button>
            <a-radio-button value="done">已完成</a-radio-button>
            <a-radio-button value="failed">失败</a-radio-button>
          </a-radio-group>
          <a-button size="small" @click="reload()">
            <template #icon><reload-outlined /></template>
            刷新
          </a-button>
          <a-button size="small" type="primary" @click="openDatasetModal">
            <template #icon><database-outlined /></template>
            数据集抽样建批
          </a-button>
          <a-button size="small" type="primary" ghost @click="openUploadModal">
            <template #icon><upload-outlined /></template>
            现场上传建批
          </a-button>
        </a-space>
      </template>

      <a-table
        :columns="columns"
        :data-source="rows"
        :pagination="false"
        :loading="loading"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'batch'">
            <div style="font-weight: 600">{{ record.name }}</div>
            <div style="color: #999; font-size: 12px">{{ record.batchNo }}</div>
          </template>
          <template v-else-if="column.key === 'source'">
            <a-tag :color="sourceMeta(record.source).color">{{ sourceMeta(record.source).label }}</a-tag>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-badge v-if="record.status === 'detecting'" status="processing"
                     :text="`检测中 ${record.processedCount}/${record.imageCount}`" />
            <a-tag v-else :color="statusMeta(record.status).color">
              {{ statusMeta(record.status).label }}
            </a-tag>
            <a-progress v-if="record.status === 'detecting'"
                        :percent="Math.round((record.processedCount / Math.max(1, record.imageCount)) * 100)"
                        size="small" :show-info="false" style="margin-top: 2px" />
          </template>
          <template v-else-if="column.key === 'images'">{{ record.imageCount }}</template>
          <template v-else-if="column.key === 'defects'">
            <a-space :size="4">
              <span>{{ record.defectImageCount }} 图</span>
              <span style="color: #999">/ {{ record.defectCount }} 框</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'caseCount'">
            <a-tooltip title="已入 Milvus 向量库的缺陷案例">
              <span>{{ record.caseCount }}</span>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'severity'">
            <a-tag v-if="record.severity" :color="severityMeta(record.severity).color">
              {{ severityMeta(record.severity).label }}
            </a-tag>
            <span v-else style="color: #ccc">-</span>
          </template>
          <template v-else-if="column.key === 'reported'">
            <a-tag v-if="record.reported === 1" color="purple">AI 报告</a-tag>
            <span v-else style="color: #ccc">未生成</span>
          </template>
          <template v-else-if="column.key === 'createTime'">
            {{ formatTime(record.createTime) }}
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space :size="4">
              <a-button v-if="canRun(record)" type="link" size="small"
                        @click="handleRun(record)">
                {{ record.status === 'failed' ? '重跑' : '开始跑批' }}
              </a-button>
              <a-button type="link" size="small"
                        :disabled="record.status === 'pending' || record.status === 'detecting'"
                        @click="goReport(record.id)">
                {{ record.reported === 1 ? '查看报告' : '批次详情' }}
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>

      <div style="margin-top: 16px; text-align: right">
        <a-pagination
          v-model:current="page"
          v-model:page-size="size"
          :total="total"
          :page-size-options="['10', '20', '50']"
          show-size-changer
          @change="reload()"
          @show-size-change="onSizeChange"
        />
      </div>
    </a-card>

    <!-- 数据集抽样建批 -->
    <a-modal v-model:open="datasetModalOpen" title="数据集抽样建批" :confirm-loading="creating"
             @ok="submitDataset" ok-text="创建批次" cancel-text="取消">
      <a-form layout="vertical" style="margin-top: 12px">
        <a-form-item label="批次名称" required>
          <a-input v-model:value="datasetForm.name" placeholder="例如: 9月上旬随机抽检" />
        </a-form-item>
        <a-form-item label="抽样数量(1~1800)">
          <a-input-number v-model:value="datasetForm.sampleCount" :min="1" :max="1800"
                          style="width: 100%" />
        </a-form-item>
        <a-form-item label="限定缺陷类别(不选 = 全类别随机)">
          <a-select v-model:value="datasetForm.classNames" mode="multiple" allow-clear
                    placeholder="全部六类" :options="classSelectOptions" />
        </a-form-item>
        <a-form-item label="随机种子(同种子可复现同一批图)">
          <a-input-number v-model:value="datasetForm.seed" :min="1" :max="2147483647"
                          style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 现场上传建批 -->
    <a-modal v-model:open="uploadModalOpen" title="现场上传建批(单批最多 50 张)"
             :confirm-loading="creating" @ok="submitUpload" ok-text="创建批次" cancel-text="取消">
      <a-form layout="vertical" style="margin-top: 12px">
        <a-form-item label="批次名称" required>
          <a-input v-model:value="uploadForm.name" placeholder="例如: 3号产线现场抽检" />
        </a-form-item>
        <a-form-item required>
          <a-upload
            v-model:file-list="uploadForm.fileList"
            list-type="picture-card"
            accept="image/jpeg,image/png,image/webp"
            :before-upload="beforeUpload"
            :max-count="50"
            multiple
          >
            <div>
              <plus-outlined />
              <div style="margin-top: 8px">选择图片</div>
            </div>
          </a-upload>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  DatabaseOutlined,
  UploadOutlined,
  ReloadOutlined,
  PlusOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import {
  pageBatches,
  createDatasetBatch,
  uploadBatch,
  runBatch,
  type BatchVO,
} from '@/api/inspection'
import { CLASS_OPTIONS, sourceMeta, statusMeta, severityMeta } from '@/utils/steel'

const router = useRouter()

const columns = [
  { key: 'batch', title: '批次', ellipsis: true },
  { key: 'source', title: '来源', width: 110 },
  { key: 'status', title: '状态', width: 150 },
  { key: 'images', title: '图片', width: 70 },
  { key: 'defects', title: '缺陷(图/框)', width: 120 },
  { key: 'caseCount', title: '案例', width: 70 },
  { key: 'severity', title: '严重度', width: 90 },
  { key: 'reported', title: '报告', width: 90 },
  { key: 'createTime', title: '创建时间', width: 170 },
  { key: 'actions', title: '操作', width: 170 },
]

const classSelectOptions = CLASS_OPTIONS.map((c) => ({
  value: c.value,
  label: `${c.label} ${c.value}`,
}))

const rows = ref<BatchVO[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const statusFilter = ref('')
const loading = ref(false)

const detectingCount = computed(
  () => rows.value.filter((r) => r.status === 'detecting').length,
)

let pollTimer: ReturnType<typeof setInterval> | null = null

function canRun(r: BatchVO) {
  return r.status === 'pending' || r.status === 'failed'
}

function formatTime(t?: string) {
  return t ? t.replace('T', ' ').slice(0, 19) : '-'
}

async function loadList(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const res = await pageBatches({
      page: page.value,
      size: size.value,
      status: statusFilter.value || undefined,
    })
    rows.value = res.list
    total.value = Number(res.total)
  } finally {
    loading.value = false
  }
  syncPolling()
}

/** reload 同时重置到第一页(筛选变化时); 不传参保留当前页 */
function reload(toPage?: number) {
  if (toPage) page.value = toPage
  loadList()
}

function onSizeChange(_p: number, s: number) {
  size.value = s
  page.value = 1
  loadList()
}

/** 当前页存在检测中批次时 5s 轮询, 全部结束后停止 */
function syncPolling() {
  if (detectingCount.value > 0 && !pollTimer) {
    pollTimer = setInterval(() => loadList(false), 5000)
  } else if (detectingCount.value === 0 && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function handleRun(r: BatchVO) {
  try {
    await runBatch(r.id)
    message.success(`批次「${r.name}」已开始跑批`)
    loadList()
  } catch {
    /* 拦截器已提示 */
  }
}

function goReport(id: number) {
  router.push(`/inspection/batches/${id}/report`)
}

// ---------- 建批弹窗 ----------
const datasetModalOpen = ref(false)
const uploadModalOpen = ref(false)
const creating = ref(false)

const datasetForm = ref({
  name: '',
  sampleCount: 20,
  classNames: [] as string[],
  seed: 42,
})

const uploadForm = ref({
  name: '',
  fileList: [] as UploadFile[],
})

function openDatasetModal() {
  datasetForm.value = { name: '', sampleCount: 20, classNames: [], seed: 42 }
  datasetModalOpen.value = true
}

function openUploadModal() {
  uploadForm.value = { name: '', fileList: [] }
  uploadModalOpen.value = true
}

/** 阻止 a-upload 自动上传, 文件仅暂存于 fileList */
function beforeUpload(file: UploadFile) {
  if (file.size && file.size > 10 * 1024 * 1024) {
    message.error(`${file.name} 超过 10MB`)
    return false
  }
  return false
}

async function submitDataset() {
  if (!datasetForm.value.name.trim()) {
    message.warning('请填写批次名称')
    return
  }
  creating.value = true
  try {
    await createDatasetBatch({
      name: datasetForm.value.name.trim(),
      sampleCount: datasetForm.value.sampleCount,
      classNames: datasetForm.value.classNames,
      seed: datasetForm.value.seed,
    })
    message.success('批次已创建(待处理), 可点击「开始跑批」')
    datasetModalOpen.value = false
    statusFilter.value = ''
    reload(1)
  } catch {
    /* 拦截器已提示 */
  } finally {
    creating.value = false
  }
}

async function submitUpload() {
  if (!uploadForm.value.name.trim()) {
    message.warning('请填写批次名称')
    return
  }
  const files = uploadForm.value.fileList
    .map((f) => f.originFileObj as File | undefined)
    .filter((f): f is File => !!f)
  if (!files.length) {
    message.warning('请至少选择 1 张图片')
    return
  }
  creating.value = true
  try {
    await uploadBatch(uploadForm.value.name.trim(), files)
    message.success('上传批次已创建(待处理)')
    uploadModalOpen.value = false
    statusFilter.value = ''
    reload(1)
  } catch {
    /* 拦截器已提示 */
  } finally {
    creating.value = false
  }
}

onMounted(() => loadList())

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
