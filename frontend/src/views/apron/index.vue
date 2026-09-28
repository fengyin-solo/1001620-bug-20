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
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>巡查状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <template v-if="allowedActions(row.status).length">
              <button
                v-for="action in allowedActions(row.status)"
                :key="action"
                class="link"
                type="button"
                :disabled="busyId === String(row.id)"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">已结单</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无机坪巡查数据，可先登记巡查单</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">按巡查区域汇总（与当前筛选结果同源，每单只计一次）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>巡查区域</th>
          <th>巡查单数（合计）</th>
          <th>待处理</th>
          <th>已提交</th>
          <th>已作废</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="area in areaStats" :key="area.area">
          <td>{{ area.area }}</td>
          <td>{{ area.total }}</td>
          <td>{{ area.pending }}</td>
          <td>{{ area.submitted }}</td>
          <td>{{ area.voided }}</td>
        </tr>
        <tr v-if="!areaStats.length">
          <td colspan="5" class="empty-state">当前筛选条件下没有巡查区域汇总数据</td>
        </tr>
      </tbody>
      <tfoot v-if="areaStats.length">
        <tr>
          <td>合计（应等于列表 {{ total }} 条）</td>
          <td>{{ areaTotal }}</td>
          <td>{{ statPayload?.pending ?? 0 }}</td>
          <td>{{ statPayload?.submitted ?? 0 }}</td>
          <td>{{ statPayload?.voided ?? 0 }}</td>
        </tr>
      </tfoot>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条机坪巡查记录，其中待处理 {{ statPayload?.pending ?? 0 }} 条</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="formOpen" class="modal-mask" @click.self="closeForm">
      <form class="modal-card" @submit.prevent="submitForm">
        <h3 class="section-title">{{ formMode === 'create' ? '登记巡查单' : `提交结果：${formValues['巡查单号']}` }}</h3>
        <p v-if="formMode === 'create'" class="form-hint">巡查单号、巡查区域、巡查人员为必填项。</p>
        <p v-else class="form-hint">填写本次巡查结果；留空的字段保留原登记明细。提交后不可再作废。</p>
        <label v-for="field in formFields" :key="field" class="filter-item form-field">
          <span>{{ field }}<em v-if="requiredFormFields.has(field)">*</em></span>
          <input
            v-model="formValues[field]"
            type="text"
            :placeholder="`请输入${field}`"
          />
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="form-actions">
          <button class="btn ghost" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="submit" :disabled="formSaving">
            {{ formSaving ? '提交中…' : (formMode === 'create' ? '确认登记' : '确认提交结果') }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatsPayload = {
  total: number
  pending: number
  submitted: number
  voided: number
  areas: { area: string; total: number; pending: number; submitted: number; voided: number }[]
}

const ENDPOINT = '/api/apron'
const columns = ["巡查单号", "巡查区域", "巡查人员", "巡查日期", "巡查项目", "发现问题数", "巡查时长", "巡查状态"]
const statuses = ["待派发", "巡查中", "已提交", "已作废"]
// 动作与后端状态机保持一致：已提交、已作废为终态，不显示任何动作
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "待派发": ["派发巡查", "作废巡查"],
  "巡查中": ["提交结果", "作废巡查"],
  "已提交": [],
  "已作废": [],
}
const filterFields = ["巡查单号", "巡查区域", "巡查人员"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ 巡查单号: '', 巡查区域: '', 巡查人员: '', status: '' })
const statPayload = ref<StatsPayload | null>(null)
const busyId = ref<string | null>(null)

const stats = computed(() => [
  { label: "待处理巡查（待派发/巡查中）", value: statPayload.value?.pending ?? 0 },
  { label: "已提交巡查单", value: statPayload.value?.submitted ?? 0 },
  { label: "已作废巡查单", value: statPayload.value?.voided ?? 0 },
])
const areaStats = computed(() => statPayload.value?.areas ?? [])
const areaTotal = computed(() => areaStats.value.reduce((sum, item) => sum + item.total, 0))

function allowedActions(status: string | number | null): string[] {
  return ACTIONS_BY_STATUS[String(status ?? '')] ?? []
}

function activeQuery(): URLSearchParams {
  const params = new URLSearchParams()
  const keyword = filters.value['巡查单号']?.trim()
  const area = filters.value['巡查区域']?.trim()
  const inspector = filters.value['巡查人员']?.trim()
  const status = filters.value.status?.trim()
  if (keyword) params.set('keyword', keyword)
  if (area) params.set('area', area)
  if (inspector) params.set('inspector', inspector)
  if (status) params.set('status', status)
  return params
}

function resetFilters() {
  filters.value = { 巡查单号: '', 巡查区域: '', 巡查人员: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export?${activeQuery().toString()}`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  busyId.value = String(row.id)
  try {
    if (action === '提交结果') {
      openSubmit(row)
      return
    }
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    // 后端对重复作废等冲突按 200 + ok=false 返回说明，必须读取 body，不能只看 HTTP 状态
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.detail ?? payload?.message ?? '机坪巡查动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '机坪巡查操作失败'
  } finally {
    busyId.value = null
  }
}

// ---- 登记 / 提交结果表单 ----
const FORM_FIELDS_CREATE = ["巡查单号", "巡查区域", "巡查人员", "巡查日期", "巡查项目", "发现问题数", "巡查时长"]
const FORM_FIELDS_SUBMIT = ["巡查项目", "发现问题数", "巡查时长", "巡查日期"]
const REQUIRED_CREATE = new Set(["巡查单号", "巡查区域", "巡查人员"])

const formOpen = ref(false)
const formMode = ref<'create' | 'submit'>('create')
const formSaving = ref(false)
const formError = ref('')
const formTargetId = ref<number | null>(null)
const formValues = reactive<Record<string, string>>({})

const formFields = computed(() => formMode.value === 'create' ? FORM_FIELDS_CREATE : FORM_FIELDS_SUBMIT)
const requiredFormFields = computed(() => formMode.value === 'create' ? REQUIRED_CREATE : new Set<string>())

function openCreate() {
  formMode.value = 'create'
  formTargetId.value = null
  formError.value = ''
  for (const field of FORM_FIELDS_CREATE) formValues[field] = ''
  formOpen.value = true
}

function openSubmit(row: Row) {
  formMode.value = 'submit'
  formTargetId.value = Number(row.id)
  formError.value = ''
  for (const field of FORM_FIELDS_SUBMIT) formValues[field] = ''
  formValues['巡查单号'] = String(row['巡查单号'] ?? '')
  formOpen.value = true
}

function closeForm() {
  formOpen.value = false
  busyId.value = null
}

async function submitForm() {
  formError.value = ''
  if (formMode.value === 'create') {
    const missing = FORM_FIELDS_CREATE
      .filter(field => REQUIRED_CREATE.has(field))
      .filter(field => !formValues[field]?.trim())
    if (missing.length) {
      formError.value = `缺少必填字段：${missing.join('、')}，巡查单号不可为空`
      return
    }
  }
  formSaving.value = true
  try {
    const url = formMode.value === 'create'
      ? ENDPOINT
      : `${ENDPOINT}/${formTargetId.value}/actions`
    const body = formMode.value === 'create'
      ? { values: { ...formValues } }
      : { values: { action: '提交结果', ...formValues } }
    const response = await request(url, { method: 'POST', body: JSON.stringify(body) })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.detail ?? payload?.message ?? '保存未生效，请稍后重试')
    }
    formOpen.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    formSaving.value = false
    busyId.value = null
  }
}

async function reload() {
  errorMessage.value = ''
  const query = activeQuery().toString()
  try {
    const [listResp, statsResp] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats?${query}`),
    ])
    if (!listResp.ok) {
      throw new Error('巡查单列表读取失败')
    }
    if (!statsResp.ok) {
      throw new Error('巡查汇总读取失败')
    }
    const payload = await listResp.json()
    const statsData: StatsPayload = await statsResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    statPayload.value = statsData
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '机坪巡查列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title { margin: 16px 0 8px; font-size: 15px; }
.muted-text { color: var(--muted); font-size: 12px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  width: 520px;
  max-width: calc(100vw - 32px);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
}
.modal-card .section-title,
.modal-card .form-hint,
.modal-card .form-actions,
.modal-card .error-text {
  grid-column: 1 / -1;
}
.form-hint { margin: 0; color: var(--muted); font-size: 12px; }
.form-field em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-field input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
