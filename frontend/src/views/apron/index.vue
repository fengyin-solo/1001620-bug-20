<template>
  <section class="page" data-module="apron">
    <header class="page-head">
      <div>
        <h2>机坪巡查管理</h2>
        <p class="page-desc">维护巡查单，围绕巡查单号、巡查区域、巡查人员、巡查日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡查单</button>
        <button class="btn" type="button" @click="exportRows">导出机坪巡查清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
      <p class="stat-hint">统计数字与下方列表、按巡查区域汇总同源，随筛选条件一起变化。</p>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="Boolean(actionLock[String(row.id)])"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无机坪巡查数据，可先登记巡查单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条机坪巡查记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="summary-block">
      <h3>按巡查区域汇总</h3>
      <p class="summary-note">
        与上方列表使用相同筛选条件：合计 {{ areaStats.total }} 条、待处理 {{ areaStats.pending }} 条、
        异常 {{ areaStats.abnormal }} 条，每条巡查单只计入一个区域，不重复统计。
      </p>
      <table class="data-table">
        <thead>
          <tr><th>巡查区域</th><th>巡查单数</th><th>待处理</th><th>异常量</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in areaRows" :key="item['巡查区域']">
            <td>{{ item['巡查区域'] }}</td>
            <td>{{ item['巡查单数'] }}</td>
            <td>{{ item['待处理'] }}</td>
            <td>{{ item['异常量'] }}</td>
          </tr>
          <tr v-if="!areaRows.length">
            <td colspan="4" class="empty-state">当前筛选条件下暂无巡查记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="formDialog.open" class="modal-mask" @click.self="closeDialog">
      <form class="modal-panel" @submit.prevent="submitDialog">
        <h3>{{ formDialog.title }}</h3>
        <p v-if="formDialog.mode === 'create'" class="modal-tip">巡查单号、巡查区域、巡查人员为必填项。</p>
        <p v-else class="modal-tip">登记巡查项目、发现问题数等明细；提交结果后不能再作废。</p>
        <label v-for="field in formDialog.fields" :key="field" class="modal-field">
          <span>{{ field }}<em v-if="formDialog.mode === 'create' && requiredFields.includes(field)">*</em></span>
          <input v-model="formDialog.values[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="formDialog.error" class="error-text">{{ formDialog.error }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="submit" :disabled="formDialog.saving">
            {{ formDialog.saving ? '提交中…' : '确定' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type AreaGroup = { '巡查区域': string; '巡查单数': number; '待处理': number; '异常量': number }
type DialogMode = 'create' | 'submit'

const ENDPOINT = '/api/apron'
const columns = ["巡查单号", "巡查区域", "巡查人员", "巡查日期", "巡查项目", "发现问题数", "巡查时长", "巡查状态"]
const requiredFields = ["巡查单号", "巡查区域", "巡查人员"]
const detailFields = ["巡查日期", "巡查项目", "发现问题数", "巡查时长"]
const filterFields = requiredFields

const rows = ref<Row[]>([])
const areaRows = ref<AreaGroup[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const actionLock = reactive<Record<string, boolean>>({})

const areaStats = computed(() => ({
  total: areaRows.value.reduce((sum, item) => sum + item['巡查单数'], 0),
  pending: areaRows.value.reduce((sum, item) => sum + item['待处理'], 0),
  abnormal: areaRows.value.reduce((sum, item) => sum + item['异常量'], 0),
}))

// 统计卡片直接取区域汇总的合计：列表、汇总、看板由后端同一份筛选口径产出。
const stats = computed(() => [
  { label: '巡查单总数', value: areaStats.value.total },
  { label: '待处理', value: areaStats.value.pending },
  { label: '已作废（异常）', value: areaStats.value.abnormal },
])

const formDialog = reactive<{
  open: boolean
  mode: DialogMode
  title: string
  fields: string[]
  values: Record<string, string>
  targetId: number | null
  error: string
  saving: boolean
}>({
  open: false,
  mode: 'create',
  title: '',
  fields: [],
  values: {},
  targetId: null,
  error: '',
  saving: false,
})

function displayValue(row: Row, column: string): string | number | null {
  if (column === '巡查状态') return String(row.status ?? '—')
  const value = row[column]
  return value === undefined || value === null || value === '' ? '—' : (value as string | number)
}

function allowedActions(row: Row): string[] {
  const status = String(row.status)
  if (status === '待派发') return ['派发巡查']
  if (status === '巡查中') return ['提交结果', '作废巡查']
  return []
}

function queryString(withSize = false): string {
  const params: Record<string, string> = {}
  for (const field of filterFields) {
    const value = filters.value[field]?.trim()
    if (value) params[field] = value
  }
  if (withSize) params.size = '20'
  return new URLSearchParams(params).toString()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  formDialog.open = true
  formDialog.mode = 'create'
  formDialog.title = '登记巡查单'
  formDialog.fields = [...requiredFields, ...detailFields]
  formDialog.values = Object.fromEntries(formDialog.fields.map((field) => [field, '']))
  formDialog.targetId = null
  formDialog.error = ''
}

function openSubmit(row: Row) {
  formDialog.open = true
  formDialog.mode = 'submit'
  formDialog.title = `提交结果（巡查单 ${String(row['巡查单号'])}）`
  formDialog.fields = detailFields
  formDialog.values = Object.fromEntries(
    detailFields.map((field) => [field, row[field] === undefined ? '' : String(row[field])]),
  )
  formDialog.targetId = Number(row.id)
  formDialog.error = ''
}

function closeDialog() {
  if (formDialog.saving) return
  formDialog.open = false
}

async function submitDialog() {
  formDialog.error = ''
  if (formDialog.mode === 'create') {
    const emptyRequired = requiredFields.filter((field) => !formDialog.values[field]?.trim())
    if (emptyRequired.length) {
      formDialog.error = `请填写必填项：${emptyRequired.join('、')}`
      return
    }
  }
  formDialog.saving = true
  try {
    const url = formDialog.mode === 'create'
      ? ENDPOINT
      : `${ENDPOINT}/${formDialog.targetId}/actions`
    const body: Record<string, unknown> = { values: { ...formDialog.values } }
    if (formDialog.mode === 'submit') {
      ;(body.values as Record<string, string>).action = '提交结果'
    }
    const result = await postAction(url, body)
    if (result.ok) {
      formDialog.open = false
      await reload()
    } else {
      formDialog.error = result.message
    }
  } catch (error) {
    formDialog.error = error instanceof Error ? error.message : '提交失败，请稍后重试'
  } finally {
    formDialog.saving = false
  }
}

async function postAction(url: string, body: unknown): Promise<{ ok: boolean; message: string }> {
  const response = await request(url, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload || payload.ok === false) {
    return { ok: false, message: payload?.message ?? payload?.detail ?? '操作未生效，请稍后重试' }
  }
  return { ok: true, message: payload.message ?? '操作成功' }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  if (action === '提交结果') {
    openSubmit(row)
    return
  }
  const lockKey = String(row.id)
  if (actionLock[lockKey]) return
  if (action === '作废巡查') {
    const confirmed = window.confirm(`确认作废巡查单 ${String(row['巡查单号'])}？作废后不能提交结果，且只能作废一次。`)
    if (!confirmed) return
  }
  actionLock[lockKey] = true
  try {
    const result = await postAction(`${ENDPOINT}/${row.id}/actions`, { values: { action } })
    if (result.ok) {
      await reload()
    } else {
      errorMessage.value = result.message
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '机坪巡查操作失败'
  } finally {
    actionLock[lockKey] = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = queryString(true)
  const summaryQuery = queryString(false)
  try {
    const [pageRes, areaRes] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/areas?${summaryQuery}`),
    ])
    if (!pageRes.ok || !areaRes.ok) {
      throw new Error('巡查单列表读取失败')
    }
    const [pagePayload, areaPayload] = await Promise.all([pageRes.json(), areaRes.json()])
    rows.value = pagePayload.items ?? []
    total.value = pagePayload.total ?? rows.value.length
    areaRows.value = areaPayload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '机坪巡查列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.stat-hint { flex-basis: 100%; color: var(--muted); font-size: 12px; margin: 2px 0 0; }
.summary-block { margin-top: 20px; }
.summary-block h3 { font-size: 15px; margin: 0 0 4px; }
.summary-note { color: var(--muted); font-size: 12px; margin: 0 0 8px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-panel {
  width: 420px;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal-panel h3 { margin: 0 0 6px; font-size: 16px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.modal-field { display: block; margin-bottom: 10px; }
.modal-field span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.modal-field em { color: #b42318; font-style: normal; margin-left: 2px; }
.modal-field input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.link:disabled { color: #94a3b8; cursor: not-allowed; }
</style>
