<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const senderId = ref('')
const draftMessage = ref('')
const messages = ref([])
const messagesContainer = ref(null)
const isSending = ref(false)
const isLoadingSidebar = ref(false)
const errorMessage = ref('')
const sidebarError = ref('')
const sessionStatus = ref(null)
const sessions = ref([])
const selectedSessionId = ref('')
const activeTab = ref('account')
const objects = ref({ accounts: [], loans: [], cards: [], transactions: [] })
const products = ref({ loan: [], wealth: [] })
const tabs = { account: '账户', transaction: '交易', loan: '贷款', loan_product: '贷款产品', wealth_product: '理财产品' }
const flowNames = {
  account_balance: '账户余额查询', transaction_query: '交易流水查询', loan_status: '贷款状态查询',
  repayment_query: '还款计划查询', complaint_ticket: '投诉提交', ticket_status_query: '工单状态查询',
}
const viewingCurrentSession = computed(() => {
  const currentSessionId = sessionStatus.value?.session?.session_id
  // 尚未创建会话时允许首次咨询；选中历史会话后则进入只读状态。
  return !currentSessionId || selectedSessionId.value === currentSessionId
})

// 两个后端仍通过原 Vite 代理访问；统一处理非 JSON 错误，避免显示解析异常。
async function request(url, options) {
  const response = await fetch(url, options)
  let data
  try { data = await response.json() } catch { throw new Error('服务返回异常，请确认中台与客服服务已启动。') }
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}），请检查查询条件。`)
  }
  return data
}

const currentItems = computed(() => {
  if (activeTab.value === 'account') return objects.value.accounts.map(item => ({
    type: 'account', id: item.account_no, title: `账户 ${item.account_no}`,
    summary: `${item.currency_code} · ${item.account_status}`, attributes: { account_no: item.account_no },
  }))
  if (activeTab.value === 'loan') return objects.value.loans.map(item => ({
    type: 'loan', id: item.loan_no, title: `贷款 ${item.loan_no}`,
    summary: `状态：${item.contract_status}`, attributes: { loan_no: item.loan_no },
  }))
  if (activeTab.value === 'transaction') return objects.value.transactions.map(item => ({
    type: 'transaction', id: item.transaction_no, title: `交易 ${item.transaction_no}`,
    summary: `${item.transaction_status} · ${item.transaction_amount} ${item.currency_code}`,
    attributes: { transaction_no: item.transaction_no, account_no: item.account_no },
  }))
  const kind = activeTab.value === 'loan_product' ? 'loan' : 'wealth'
  return products.value[kind].map(item => ({
    type: activeTab.value, id: item.product_code, title: item.product_name,
    summary: `风险：${item.risk_level_name} · ${item.product_status}`, attributes: { product_code: item.product_code },
  }))
})

function appendMessage(role, message) {
  messages.value.push({ id: crypto.randomUUID(), role, ...message })
}

function formatSessionTime(timestamp) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
}

async function fetchSidebarData() {
  const customer = senderId.value.trim()
  if (!customer) return
  isLoadingSidebar.value = true
  sidebarError.value = ''
  objects.value = { accounts: [], loans: [], cards: [], transactions: [] }
  try {
    const data = await request(`/business/finance/customers/${encodeURIComponent(customer)}/objects`)
    if (senderId.value.trim() === customer) objects.value = data.data
  } catch (error) {
    if (senderId.value.trim() === customer) sidebarError.value = error.message
  } finally {
    if (senderId.value.trim() === customer) isLoadingSidebar.value = false
  }
}

async function fetchSessionStatus() {
  const customer = senderId.value.trim()
  if (!customer) return
  try {
    const data = await request(`/api/chat/status?sender_id=${encodeURIComponent(customer)}`)
    if (senderId.value.trim() === customer) {
      sessionStatus.value = data
      selectedSessionId.value = data.session?.session_id || ''
    }
  } catch (error) {
    if (senderId.value.trim() === customer) errorMessage.value = error.message
  }
}

async function fetchSessions(selectCurrent = true) {
  const customer = senderId.value.trim()
  if (!customer) return
  try {
    const data = await request(`/api/chat/sessions?sender_id=${encodeURIComponent(customer)}`)
    if (senderId.value.trim() !== customer) return
    sessions.value = data.sessions
    if (selectCurrent && sessionStatus.value?.session?.session_id) {
      selectedSessionId.value = sessionStatus.value.session.session_id
    }
  } catch (error) {
    if (senderId.value.trim() === customer) errorMessage.value = error.message
  }
}

async function startNewSession() {
  const customer = senderId.value.trim()
  if (!customer || isSending.value) return
  try {
    await request('/api/chat/sessions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender_id: customer }),
    })
    messages.value = []
    errorMessage.value = ''
    await fetchSessionStatus()
    await fetchSessions()
  } catch (error) { errorMessage.value = error.message }
}

async function fetchChatHistory() {
  const customer = senderId.value.trim()
  if (!customer) return
  try {
    const status = await request(`/api/chat/status?sender_id=${encodeURIComponent(customer)}`)
    const sessionId = status.session?.session_id
    selectedSessionId.value = sessionId || ''
    if (!sessionId) {
      if (senderId.value.trim() === customer) messages.value = []
      return
    }
    const data = await request(`/api/chat/history?sender_id=${encodeURIComponent(customer)}&session_id=${encodeURIComponent(sessionId)}`)
    if (senderId.value.trim() === customer) messages.value = data.messages.map(message => ({ id: crypto.randomUUID(), ...message }))
  } catch (error) {
    if (senderId.value.trim() === customer) errorMessage.value = error.message
  }
}

async function selectSession(sessionId) {
  const customer = senderId.value.trim()
  if (!customer || !sessionId || isSending.value) return
  try {
    const data = await request(`/api/chat/history?sender_id=${encodeURIComponent(customer)}&session_id=${encodeURIComponent(sessionId)}`)
    if (senderId.value.trim() === customer) {
      selectedSessionId.value = sessionId
      messages.value = data.messages.map(message => ({ id: crypto.randomUUID(), ...message }))
    }
  } catch (error) { errorMessage.value = error.message }
}

async function sendPayload(payload) {
  if (isSending.value || !senderId.value.trim() || !viewingCurrentSession.value) return
  const customer = senderId.value.trim()
  errorMessage.value = ''
  isSending.value = true
  appendMessage('user', payload)
  try {
    const data = await request('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender_id: customer, ...payload }),
    })
    if (senderId.value.trim() === customer) for (const message of data.messages) appendMessage('bot', message)
    await fetchSessionStatus()
    await fetchSessions(false)
  } catch (error) { errorMessage.value = error.message }
  finally { isSending.value = false }
}

async function sendTextMessage() {
  const text = draftMessage.value.trim()
  if (!text || isSending.value) return
  draftMessage.value = ''
  await sendPayload({ text })
}

async function sendObject(item) {
  // 保留原 object 协议；不把余额等展示数据当成可信查询结果发给模型。
  await sendPayload({ object: { type: item.type, id: item.id, title: item.title, attributes: item.attributes } })
}

watch(() => messages.value.length, async () => {
  await nextTick()
  if (messagesContainer.value) messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
})
watch(senderId, async () => {
  messages.value = []
  errorMessage.value = ''
  objects.value = { accounts: [], loans: [], cards: [], transactions: [] }
  sessionStatus.value = null
  sessions.value = []
  selectedSessionId.value = ''
  await Promise.all([fetchSidebarData(), fetchSessionStatus()])
  await fetchSessions()
  await fetchChatHistory()
})

onMounted(async () => {
  try {
    // 使用真实样例客户编号，避免沿用电商演示用户导致查不到金融数据。
    const [customer, loans, wealth] = await Promise.all([
      request('/business/finance/demo-customer'),
      request('/business/finance/products?kind=loan'),
      request('/business/finance/products?kind=wealth'),
    ])
    products.value = { loan: loans.data.products, wealth: wealth.data.products }
    senderId.value = customer.data.customer_no
  } catch (error) { sidebarError.value = error.message }
})
</script>

<template>
  <div class="app-shell">
    <div class="workspace">
      <div class="chat-card">
        <header class="chat-header">
          <div><h1>融知 FinAssist · 金融客服</h1><p v-if="sessionStatus?.resume_hint" class="resume-hint">{{ sessionStatus.resume_hint }}</p></div>
          <div class="header-actions">
            <select v-model="selectedSessionId" class="session-select" aria-label="历史会话" :disabled="isSending || !sessions.length" @change="selectSession(selectedSessionId)">
              <option v-for="session in sessions" :key="session.session_id" :value="session.session_id">
                {{ session.preview || '空会话' }} · {{ session.message_count }}条 · {{ formatSessionTime(session.last_activity_at) }}
              </option>
            </select>
            <button class="secondary-button" :disabled="isSending || !senderId" @click="startNewSession">新建会话</button>
          </div>
        </header>
        <section class="controls">
          <label class="field">
            <span>样例客户编号</span>
            <div class="field-row">
              <input v-model.lazy="senderId" :disabled="isSending" aria-label="样例客户编号" placeholder="自动加载样例客户" />
              <button class="secondary-button" :disabled="isLoadingSidebar || !senderId" @click="fetchSidebarData">
                {{ isLoadingSidebar ? '加载中…' : '刷新金融对象' }}
              </button>
            </div>
          </label>
        </section>
        <section v-if="sessionStatus" class="session-status" aria-live="polite">
          <span>{{ viewingCurrentSession ? '当前会话' : '历史会话（只读）' }}：{{ selectedSessionId ? selectedSessionId.slice(0, 8) : '未开始' }}</span>
          <span v-if="sessionStatus.active_task">进行中：{{ flowNames[sessionStatus.active_task.flow_id] || sessionStatus.active_task.flow_id }}（{{ sessionStatus.active_task.step_id }}）</span>
          <span v-if="sessionStatus.paused_tasks.length">已暂停 {{ sessionStatus.paused_tasks.length }} 项</span>
        </section>
        <section ref="messagesContainer" class="messages">
          <div v-if="!messages.length" class="empty-state">
            可以问“查一下账户余额”“查看最近交易流水”或“有哪些理财产品”。点击右侧账户、贷款卡片即可选中对象。
          </div>
          <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
            <div class="meta">{{ message.role === 'user' ? '你' : '融知客服' }}</div>
            <div class="bubble">
              <div v-if="message.object" class="object-card">
                <div class="object-card-badge">{{ tabs[message.object.type] || '业务对象' }}</div>
                <div class="object-card-title">{{ message.object.title }}</div>
                <div class="object-card-meta">{{ message.object.id }}</div>
              </div>
              <p v-else>{{ message.text }}</p>
            </div>
          </article>
        </section>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <form class="composer" @submit.prevent="sendTextMessage">
          <input v-model="draftMessage" aria-label="金融咨询内容" :placeholder="viewingCurrentSession ? '请输入金融咨询内容…' : '历史会话为只读，请切回当前会话继续咨询'" :disabled="isSending || !senderId || !viewingCurrentSession" />
          <button type="submit" :disabled="isSending || !senderId || !viewingCurrentSession || !draftMessage.trim()">{{ isSending ? '查询中…' : '发送' }}</button>
        </form>
      </div>
      <aside class="sidebar">
        <div class="sidebar-header"><h2>金融业务对象</h2><p>合成样例数据</p></div>
        <div class="tabs" style="flex-wrap: wrap">
          <button v-for="(label, type) in tabs" :key="type" class="tab-button" :class="{ active: activeTab === type }" @click="activeTab = type">{{ label }}</button>
        </div>
        <p v-if="sidebarError" class="sidebar-error" role="alert">{{ sidebarError }}</p>
        <div class="sidebar-list">
          <div v-if="!currentItems.length" class="sidebar-empty">{{ isLoadingSidebar ? '正在加载…' : '暂无此类对象' }}</div>
          <article v-for="item in currentItems" :key="item.id" class="sidebar-card">
            <div class="card-title">{{ item.title }}</div>
            <div class="card-meta">{{ item.summary }}</div>
            <button class="secondary-button full-width" :disabled="isSending || !senderId" @click="sendObject(item)">选择此{{ tabs[item.type] }}</button>
          </article>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: linear-gradient(180deg, #eef4ff 0%, #e6edf8 100%);
  color: #142033;
}

:global(button),
:global(input) {
  font: inherit;
}

#app {
  min-height: 100vh;
}

.app-shell {
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(28, 100, 242, 0.12), transparent 30%),
    radial-gradient(circle at bottom right, rgba(14, 165, 140, 0.12), transparent 28%),
    linear-gradient(180deg, #edf3fb 0%, #e7eef8 100%);
}

.workspace {
  width: min(1760px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 20px;
}

.chat-card,
.sidebar {
  min-height: calc(100vh - 48px);
  height: calc(100vh - 48px);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
}

.chat-card {
  display: flex;
  flex-direction: column;
}

.chat-header,
.sidebar-header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.chat-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.session-select {
  max-width: 340px;
  min-height: 42px;
  padding: 8px 12px;
  border: 1px solid rgba(148, 163, 184, 0.4);
  border-radius: 12px;
  background: #fff;
  color: #142033;
}

.chat-header h1,
.sidebar-header h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.sidebar-header h2 {
  font-size: 22px;
}

.chat-header p,
.sidebar-header p {
  margin: 10px 0 0;
  color: #52627a;
}

.resume-hint {
  color: #0f766e !important;
  font-size: 13px;
}

.session-status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 9px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  color: #607189;
  font-size: 13px;
}

.controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field span {
  color: #4f5f77;
  font-size: 14px;
}

.field-row {
  display: flex;
  gap: 12px;
}

.field input,
.composer input {
  width: 100%;
  min-width: 0;
  min-height: 46px;
  padding: 11px 14px;
  border: 1px solid rgba(148, 163, 184, 0.4);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.86);
  color: #142033;
  font-size: 15px;
  line-height: 1.4;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-state,
.sidebar-empty {
  margin: auto;
  max-width: 420px;
  color: #61718a;
  text-align: center;
  line-height: 1.7;
}

.message {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(78%, 720px);
}

.message.user {
  align-self: flex-end;
}

.message.bot {
  align-self: flex-start;
}

.message.divider {
  align-self: stretch;
  max-width: none;
}

.history-divider {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #7a8aa3;
  font-size: 13px;
}

.history-divider::before,
.history-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: rgba(148, 163, 184, 0.36);
}

.history-divider span {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.meta {
  font-size: 13px;
  color: #71829a;
}

.bubble {
  padding: 15px 17px;
  border-radius: 20px;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.message.user .bubble {
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  border-color: transparent;
  color: #eff6ff;
  box-shadow: 0 12px 30px rgba(37, 99, 235, 0.22);
}

.message.bot .bubble {
  background: rgba(255, 255, 255, 0.94);
  color: #1b2a40;
}

.bubble p {
  margin: 0;
  font-size: 15px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.object-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 240px;
}

.object-card-badge {
  width: fit-content;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(20, 32, 51, 0.08);
  color: #27415f;
  font-size: 12px;
  line-height: 1;
}

.message.user .object-card-badge {
  background: rgba(255, 255, 255, 0.18);
  color: #eff6ff;
}

.object-card-title {
  font-size: 16px;
  line-height: 1.5;
  font-weight: 600;
}

.object-card-meta {
  font-size: 14px;
  color: inherit;
  opacity: 0.86;
}

.object-card-price {
  font-size: 15px;
  font-weight: 600;
}

.composer button,
.secondary-button,
.tab-button {
  min-height: 40px;
  padding: 9px 14px;
  border: 1px solid rgba(148, 163, 184, 0.36);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  color: #1b2a40;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.2;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}

.composer button:hover,
.secondary-button:hover,
.tab-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}

.composer button:disabled,
.secondary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.error-message,
.sidebar-error {
  margin: 0;
  padding: 0 24px 14px;
  color: #c2410c;
}

.composer {
  flex-shrink: 0;
  display: flex;
  align-items: stretch;
  gap: 12px;
  padding: 16px 24px 24px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.72);
}

.composer button {
  min-width: 96px;
  padding-inline: 18px;
  background: linear-gradient(135deg, #0f766e, #0ea5a3);
  border-color: transparent;
  color: #f0fdfa;
  box-shadow: 0 14px 28px rgba(13, 148, 136, 0.2);
}

.sidebar {
  display: flex;
  flex-direction: column;
}

.tabs {
  display: flex;
  gap: 8px;
  padding: 16px 24px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.tab-button {
  min-width: 80px;
}

.tab-button.active {
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  border-color: transparent;
  color: #eff6ff;
}

.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sidebar-card {
  padding: 16px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.76);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-top {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: flex-start;
}

.card-title {
  font-size: 15px;
  line-height: 1.5;
  color: #18283f;
  font-weight: 600;
}

.card-amount {
  flex-shrink: 0;
  color: #10233f;
  font-weight: 700;
}

.card-meta {
  font-size: 14px;
  color: #607189;
}

.full-width {
  width: 100%;
}

.sidebar .secondary-button.full-width {
  min-height: 40px;
}

@media (max-width: 1180px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .chat-header {
    flex-direction: column;
  }

  .header-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .session-select {
    max-width: 100%;
  }

  .sidebar {
    min-height: auto;
    height: auto;
  }
}

@media (max-width: 720px) {
  .app-shell {
    padding: 0;
  }

  .workspace {
    gap: 0;
  }

  .chat-card,
  .sidebar {
    min-height: auto;
    height: auto;
    border-radius: 0;
    border-left: none;
    border-right: none;
  }

  .chat-card {
    min-height: 100vh;
  }

  .message {
    max-width: 100%;
  }

  .composer,
  .field-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
