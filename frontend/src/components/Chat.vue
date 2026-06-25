<template>
  <div class="chat-container">
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <h2 class="logo" v-if="!sidebarCollapsed">AI 助手</h2>
        <button class="toggle-btn" @click="sidebarCollapsed = !sidebarCollapsed">☰</button>
      </div>
      <div class="new-chat-btn" v-if="!sidebarCollapsed" @click="createNewSession">＋ 新建对话</div>
      <div class="session-list" v-if="!sidebarCollapsed">
        <div v-for="session in sessions" :key="session.id" class="session-item"
          :class="{ active: session.id === currentSessionId }" @click="switchSession(session.id)">
          <span class="session-title">{{ session.title }}</span>
          <button class="delete-btn" @click.stop="deleteSession(session.id)">✕</button>
        </div>
      </div>
      <div class="sidebar-footer" v-if="!sidebarCollapsed">
        <button class="clear-btn" @click="clearAllSessions">清除所有会话</button>
      </div>
    </aside>

    <main class="chat-main">
      <div class="messages" ref="messagesRef">
        <div v-for="(msg, idx) in messages" :key="idx" class="message" :class="msg.role">
          <!-- 用户头像 -->
          <div class="avatar" :class="msg.role">
            <img v-if="msg.role === 'user'" src="@/assets/user-avatar.png" class="avatar-img" />
            <img v-else src="@/assets/bot-avatar.png" class="avatar-img" />
          </div>
          <div class="bubble-wrapper">
            <div v-if="msg.toolCalls && msg.toolCalls.length > 0" class="tool-calls-bar"
              @click="msg._toolCallsCollapsed = !msg._toolCallsCollapsed">
              <span class="tool-calls-toggle">{{ msg._toolCallsCollapsed ? '▶' : '▼' }}</span>
              <span class="tool-calls-summary">调用了 {{ msg.toolCalls.length }} 个工具</span>
            </div>
            <div v-if="msg.toolCalls && msg.toolCalls.length > 0 && !msg._toolCallsCollapsed" class="tool-calls-detail">
              <div v-for="(tc, tci) in msg.toolCalls" :key="tci" class="tool-call-item">
                <span class="tool-call-icon">🔧</span>
                <span class="tool-call-name">{{ tc.tool_name }}</span>
                <span class="tool-call-args" v-if="Object.keys(tc.args).length > 0">({{ Object.entries(tc.args).map(([k, v]) => `${k}=${v}`).join(', ') }})</span>
              </div>
            </div>
            <div class="bubble" v-html="msg.renderedContent"></div>
          </div>
        </div>
        <div v-if="loading" class="message assistant">
          <div class="avatar">
            <img src="@/assets/bot-avatar.png" class="avatar-img" />
          </div>
          <div class="bubble-wrapper">
            <div v-if="toolCalls.length > 0" class="tool-calls-bar">
              <span class="tool-calls-toggle">▼</span>
              <span class="tool-calls-summary">正在调用 {{ toolCalls.length }} 个工具...</span>
            </div>
            <div v-if="toolCalls.length > 0" class="tool-calls-detail">
              <div v-for="(tc, tci) in toolCalls" :key="tci" class="tool-call-item">
                <span class="tool-call-icon">🔧</span>
                <span class="tool-call-name">{{ tc.tool_name }}</span>
                <span class="tool-call-args" v-if="Object.keys(tc.args).length > 0">({{ Object.entries(tc.args).map(([k, v]) => `${k}=${v}`).join(', ') }})</span>
              </div>
            </div>
            <div class="bubble loading-dots">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <div v-if="pendingApproval" class="approval-bar">
          <div class="approval-items">
            <div v-for="(req, idx) in pendingRequests" :key="idx" class="approval-item">
              <div class="approval-item-info">
                <span class="approval-tool-name">🔧 {{ req.name }}</span>
                <span class="approval-args" v-if="Object.keys(req.args).length > 0">
                  {{ Object.entries(req.args).map(([k, v]) => `${k}=${v}`).join(', ') }}
                </span>
                <span class="approval-desc">{{ req.description }}</span>
              </div>
              <div class="approval-actions">
                <button v-if="req.decision !== 'approve'" class="approval-btn approve" @click="setDecision(idx, 'approve')">✅ 批准</button>
                <span v-else class="decision-badge approved">已批准</span>
                <button v-if="req.decision !== 'reject'" class="approval-btn reject" @click="setDecision(idx, 'reject')">❌ 拒绝</button>
                <span v-else class="decision-badge rejected">已拒绝</span>
              </div>
            </div>
          </div>
          <div class="approval-footer">
            <button class="submit-approval-btn" @click="submitAllDecisions" :disabled="!allDecided">
              提交审批 ({{ pendingRequests.filter(r => r.decision !== null).length }}/{{ pendingRequests.length }})
            </button>
          </div>
        </div>
        <textarea v-model="inputMessage" placeholder="输入你的消息..."
          @keydown.enter.exact="sendMessage" :disabled="loading" rows="1"></textarea>
        <button @click="sendMessage" :disabled="loading || !inputMessage.trim()">发送</button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'

const messages = ref([])
const inputMessage = ref('')
const loading = ref(false)
const sidebarCollapsed = ref(false)
const messagesRef = ref(null)
const sessions = ref([])
const currentSessionId = ref(null)
const toolCalls = ref([]) // 当前轮的工具调用列表 [{tool_name, args}]
const pendingApproval = ref(false) // 是否需要显示审批按钮
const pendingRequests = ref([]) // 待审批的请求列表 [{name, args, description, decision}]

const allDecided = computed(() => {
  return pendingRequests.value.length > 0 && pendingRequests.value.every(req => req.decision !== null)
})
let ws = null
let heartbeatTimer = null
let wsConnected = false

function generateId() {
  return 'session_' + Date.now() + '_' + crypto.randomUUID()
}

// 页面级 trace_id，整个页面生命周期内所有 HTTP 请求共享
const clientTraceId = 'web_' + Date.now().toString(36) + '_' + crypto.randomUUID()

function loadMessagesForSession(sessionId) {
  const saved = localStorage.getItem('chat_messages_' + sessionId)
  messages.value = saved ? JSON.parse(saved) : []
  // 渲染 markdown
  messages.value.forEach(m => {
    if (!m.renderedContent) m.renderedContent = marked(m.content)
  })
}

function saveMessages() {

  const firstUserMsg = messages.value.find(m => m.role === 'user')
  if (firstUserMsg && currentSessionId.value) {
    const session = sessions.value.find(s => s.id === currentSessionId.value)
    if (session) {
      session.title = firstUserMsg.content.slice(0, 20) + (firstUserMsg.content.length > 20 ? '...' : '')
    }
  }
}

function saveSessions() {
  localStorage.setItem('chat_sessions', JSON.stringify(sessions.value))
  localStorage.setItem('chat_current_session', currentSessionId.value || '')
}

async function loadSessions() {
  const res = await fetch('http://127.0.0.1:6002/api/sessions')
  sessions.value = await res.json()
  console.log('拉到的会话列表:', sessions.value)       
  console.log('localStorage里的id:', localStorage.getItem('chat_current_session'))  
  const current = localStorage.getItem('chat_current_session')
  if (current && sessions.value.some(s => s.id === current)) {
    await switchSession(current)
  } else if (sessions.value.length > 0) {
    await switchSession(sessions.value[0].id)
  }
}
async function createNewSession() {
  const id = generateId()
  await fetch('http://127.0.0.1:6002/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Trace-Id': clientTraceId },
    body: JSON.stringify({ thread_id: id, title: '新对话' })
  })
  sessions.value.unshift({ id, title: '新对话', createdAt: Date.now() })
  currentSessionId.value = id
  messages.value = []
  localStorage.setItem('chat_current_session', id)
}

async function switchSession(id) {
  console.log('switchSession 被调用, id:', id)
  loading.value = false
  currentSessionId.value = id
  localStorage.setItem('chat_current_session', id)
  const res = await fetch(`http://127.0.0.1:6002/api/sessions/${id}/messages`)
  const data = await res.json()
  console.log('拉到的消息:', data)
  messages.value = data.map(m => ({
    role: m.role,
    content: m.content,
    renderedContent: marked(m.content)
  }))
  scrollToBottom()
}

async function deleteSession(id) {
  await fetch(`http://127.0.0.1:6002/api/sessions/${id}`, {
    method: 'DELETE',
    headers: { 'X-Trace-Id': clientTraceId }
  })
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) {
    if (sessions.value.length > 0) {
      await switchSession(sessions.value[0].id)
    } else {
      currentSessionId.value = null
      messages.value = []
    }
  }
  saveSessions()
}

async function clearAllSessions() {
  // 逐个调删除接口
  for (const s of sessions.value) {
    await fetch(`http://127.0.0.1:6002/api/sessions/${s.id}`, {
      method: 'DELETE',
      headers: { 'X-Trace-Id': clientTraceId }
    })
  }
  sessions.value = []
  currentSessionId.value = null
  messages.value = []
  localStorage.removeItem('chat_current_session')
}

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return // 已经有连接了，不复连
  }
  try { ws = new WebSocket('ws://127.0.0.1:6002/ws/chat') } catch (e) { console.error(e); return }
  ws.onopen = () => {
    wsConnected = true
    heartbeatTimer = setInterval(() => {
      ws && ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: 'ping' }))
    }, 30000)
  }
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      console.log('📩 [WebSocket] 收到消息:', data)
       // 🔥 新增：清空 token
      if (data.type === 'clear_tokens') {
        console.log('🧹 清空当前流式消息')
        // 找到最后一条 assistant 消息，清空内容
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'assistant') {
          last.content = ''
          last.renderedContent = ''
        }
        return
      }
      if (data.type === 'token') {
        // 流式 token，追加到最后一个 assistant 气泡
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'assistant') {
          last.content += data.content
          last.renderedContent = marked(last.content)
        } else {
          // 第一个 token，新建气泡
          messages.value.push({ role: 'assistant', content: data.content, renderedContent: marked(data.content) })
        }
        scrollToBottom()
      } else if (data.type === 'result') {
        // 一次性返回整个回复，工具调用列表折叠到气泡上方
        const savedToolCalls = [...toolCalls.value]
        messages.value.push({
        role: 'assistant',
        content: data.content,
        renderedContent: marked(data.content),
        toolCalls: savedToolCalls,
        _toolCallsCollapsed: true
        })
        toolCalls.value = []
        pendingApproval.value = false
        loading.value = false
        scrollToBottom()
      } else if (data.type === 'tool_call') {
        // 追加到当前工具调用列表，不单独占气泡
        const args = data.args || {}
        toolCalls.value.push({ tool_name: data.tool_name, args })
        // 如果是 create_calendar_event 需要审批
        if (data.tool_name === 'create_calendar_event') {
          pendingApproval.value = true
        }
        scrollToBottom()
      } else if (data.type === 'interrupt') {
        if (toolCalls.value.length > 0) {
        // 找到最后一条 assistant 消息，把 toolCalls 挂上去
        const lastMsg = messages.value[messages.value.length - 1]
        if (lastMsg && lastMsg.role === 'assistant') {
            lastMsg.toolCalls = [...toolCalls.value]
            lastMsg._toolCallsCollapsed = true
        } else {
            // 如果没有 assistant 消息，新建一条空的
            messages.value.push({
                role: 'assistant',
                content: '',
                renderedContent: '',
                toolCalls: [...toolCalls.value],
                _toolCallsCollapsed: true
                  })
              }
          }
    
        // 收到中断信号，显示审批卡片（每个工具一个）
        pendingApproval.value = true
        loading.value = false
        const itrData = data.data || {}
        const requests = itrData.action_requests || []
        pendingRequests.value = requests.map(req => ({
          name: req.name,
          args: req.args || {},
          description: req.description || `需要审批: ${req.name}`,
          decision: null
        }))
        scrollToBottom()
      } else if (data.type === 'done') {
        // 本轮结束，清空审批状态
            // 🔥 如果 toolCalls 还有残留，保存到最后一条消息
        if (toolCalls.value.length > 0) {
            const lastMsg = messages.value[messages.value.length - 1]
            if (lastMsg && lastMsg.role === 'assistant') {
                if (!lastMsg.toolCalls || lastMsg.toolCalls.length === 0) {
                    lastMsg.toolCalls = [...toolCalls.value]
                    lastMsg._toolCallsCollapsed = true
                }
            }
            toolCalls.value = []  // 清空
        }
        pendingApproval.value = false
        pendingRequests.value = []
        loading.value = false
        loading.value = false
        // 更新标题到后端
        const firstUserMsg = messages.value.find(m => m.role === 'user')
        if (firstUserMsg && currentSessionId.value) {
          const title = firstUserMsg.content.slice(0, 20) + (firstUserMsg.content.length > 20 ? '...' : '')
          fetch(`http://127.0.0.1:6002/api/sessions/${currentSessionId.value}/title`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
          })
          // 同步更新前端显示
          const session = sessions.value.find(s => s.id === currentSessionId.value)
          if (session) session.title = title
        }
        scrollToBottom()
      } else if (data.type === 'error') {
        messages.value.push({ role: 'assistant', content: '❌ ' + data.content, renderedContent: '❌ ' + data.content })
        loading.value = false
        scrollToBottom()
      }
    } catch (e) { console.error(e) }
  }
  ws.onerror = () => { loading.value = false }
  ws.onclose = () => {
    wsConnected = false
    ws = null
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
    // 5 秒后自动重连
    setTimeout(connectWebSocket, 5000)
  }
}

async function sendMessage() {
  const text = inputMessage.value.trim()
  if (!text || loading.value) return
  if (!currentSessionId.value) await createNewSession()
  messages.value.push({ role: 'user', content: text, renderedContent: marked(text) })
  inputMessage.value = ''; loading.value = true; saveMessages(); scrollToBottom()
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ message: text, thread_id: currentSessionId.value }))
  } else {
    messages.value.push({ role: 'assistant', content: '❌ 未连接到服务器', renderedContent: '❌ 未连接到服务器' })
    loading.value = false; saveMessages(); scrollToBottom()
  }
}

function setDecision(idx, decision) {
  pendingRequests.value[idx].decision = decision
}

function submitAllDecisions() {
  if (!allDecided.value) return

  const decisions = pendingRequests.value.map(req => ({
    type: req.decision
  }))

  pendingApproval.value = false
  loading.value = true

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'decision',
      decisions: decisions,
      action_count: pendingRequests.value.length,
      thread_id: currentSessionId.value
    }))
  }

  pendingRequests.value = []
}

function scrollToBottom() { nextTick(() => { messagesRef.value && (messagesRef.value.scrollTop = messagesRef.value.scrollHeight) }) }

onMounted(async () => {
  await loadSessions()
  console.log('loadSessions 完成后 currentSessionId:', currentSessionId.value) 
  if (!currentSessionId.value) await createNewSession()
  connectWebSocket()
  scrollToBottom()
})

onUnmounted(() => {
  if (ws) { ws.close(); ws = null }
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
})
</script>

<style scoped>
.chat-container { display: flex; height: 100vh; background: #f5f5f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.sidebar { width: 260px; background: #202123; color: #fff; display: flex; flex-direction: column; transition: width 0.3s ease; overflow: hidden; flex-shrink: 0; }
.sidebar.collapsed { width: 50px; }
.sidebar-header { display: flex; align-items: center; justify-content: space-between; padding: 14px; border-bottom: 1px solid #ffffff1a; }
.logo { font-size: 16px; margin: 0; white-space: nowrap; }
.toggle-btn { background: none; border: none; color: #fff; font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 4px; }
.toggle-btn:hover { background: #ffffff1a; }
.new-chat-btn { margin: 10px; padding: 10px; border-radius: 6px; cursor: pointer; text-align: center; border: 1px solid #ffffff33; font-size: 14px; }
.new-chat-btn:hover { background: #ffffff1a; }
.session-list { flex: 1; overflow-y: auto; padding: 4px; }
.session-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 6px; cursor: pointer; margin-bottom: 2px; }
.session-item:hover { background: #ffffff1a; }
.session-item.active { background: #ffffff26; }
.session-title { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
.delete-btn { background: none; border: none; color: #ffffff66; cursor: pointer; font-size: 12px; padding: 2px 6px; border-radius: 4px; opacity: 0; }
.session-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { color: #ff4444; background: #ffffff1a; }
.sidebar-footer { padding: 10px; border-top: 1px solid #ffffff1a; }
.clear-btn { width: 100%; padding: 8px; background: none; border: 1px solid #ff444466; color: #ff6666; border-radius: 6px; cursor: pointer; font-size: 13px; }
.clear-btn:hover { background: #ff444422; }
.chat-main { flex: 1; display: flex; flex-direction: column; background: #fff; }
.messages { flex: 1; overflow-y: auto; padding: 20px 0; }
.message { display: flex; gap: 12px; padding: 8px 5px; max-width: 1000px; margin: 0 auto; width: 100%; }
.message.user { flex-direction: row-reverse; }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; background: #f0f0f0; }
.message.user .avatar { background: #10a37f; }
.bubble { padding: 10px 16px; border-radius: 12px; line-height: 1.6; font-size: 15px; word-wrap: break-word; }
.message.user .bubble { background: #158dceaf; color: #fff; border-bottom-right-radius: 4px;  }
.message.assistant .bubble { background: #f7f7f8; color: #333; border-bottom-left-radius: 4px; max-width: 85%; }
.bubble :deep(p) { margin: 0 0 8px; }
.bubble :deep(p:last-child) { margin-bottom: 0; }
.bubble :deep(code) { background: #e8e8e8; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
.bubble :deep(pre) { background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
.bubble :deep(pre code) { background: none; padding: 0; font-size: 13px; }
.bubble :deep(ul), .bubble :deep(ol) { padding-left: 20px; margin: 8px 0; }
.bubble :deep(a) { color: green; text-decoration: none; }
.bubble :deep(a[href^="mailto:"]) { 
  color: #0066cc;  /* 邮箱专门蓝色 */
}
.bubble :deep(a:hover) { text-decoration: underline; }
.bubble :deep(blockquote) { border-left: 3px solid inherit; margin: 8px 0; padding-left: 12px; color: #666; }
.loading-dots { display: flex; gap: 6px; align-items: center; min-height: 36px; }
.dot { width: 8px; height: 8px; background: #999; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }

/* 工具调用栏 */
.bubble-wrapper { }
.tool-calls-bar {
  font-size: 12px; color: #888; cursor: pointer; user-select: none;
  padding: 2px 0; margin-bottom: 2px; display: flex; align-items: center; gap: 4px;
}
.tool-calls-bar:hover { color: #666; }
.tool-calls-toggle { font-size: 10px; }
.tool-calls-summary { }
.tool-calls-detail {
  font-size: 12px; color: #888; margin-bottom: 4px;
  display: flex; flex-direction: column; gap: 2px;
}
.tool-call-item { display: flex; align-items: center; gap: 4px; }
.tool-call-icon { font-size: 12px; }
.tool-call-name { font-weight: 500; color: #666; }
.tool-call-args { color: #aaa; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; }
.input-area { display: flex; gap: 8px; padding: 16px 20px; border-top: 1px solid #e5e5e5; max-width: 800px; margin: 0 auto; width: 100%; flex-wrap: wrap; }
.input-area textarea { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 15px; resize: none; outline: none; line-height: 1.5; max-height: 150px; font-family: inherit; min-width: 0; }
.input-area textarea:focus { border-color: #10a37f; }
.input-area button { padding: 10px 24px; background: #10a37f; color: #fff; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; white-space: nowrap; }
.input-area button:hover:not(:disabled) { background: #0e8c6b; }
.input-area button:disabled { background: #ccc; cursor: not-allowed; }
.approval-bar {
  width: 100%; display: flex; flex-direction: column; gap: 6px;
  padding: 10px 12px; background: #fff8e1; border-radius: 8px; border: 1px solid #ffe082;
  font-size: 14px;
}
.approval-items { display: flex; flex-direction: column; gap: 6px; }
.approval-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; background: #fff; border-radius: 6px; border: 1px solid #fff3cd;
  flex-wrap: wrap;
}
.approval-item-info { 
  display: flex; 
  flex-direction: column; 
  align-items: flex-start; 
  gap: 4px; 
  flex: 1; 
  min-width: 0; 
}

.approval-tool-name { 
  font-weight: 600; 
  color: #333; 
  font-size: 13px; 
}

.approval-args { 
  color: #888; 
  font-size: 12px; 
  word-break: break-all; 
}

.approval-desc { 
  color: #f57f17; 
  font-size: 12px; 
  word-break: break-all; 
}
.approval-actions { display: flex; gap: 4px; flex-shrink: 0; }
.approval-btn { padding: 4px 12px; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.approval-btn.approve { background: #e8f5e9; color: #2e7d32; }
.approval-btn.approve:hover { background: #c8e6c9; }
.approval-btn.reject { background: #ffebee; color: #c62828; }
.approval-btn.reject:hover { background: #ffcdd2; }
.approval-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.decision-badge { font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 4px; }
.decision-badge.approved { background: #e8f5e9; color: #2e7d32; }
.decision-badge.rejected { background: #ffebee; color: #c62828; }
.approval-footer { display: flex; justify-content: flex-end; }
.submit-approval-btn { padding: 6px 20px; background: #f57f17; color: #fff; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
.submit-approval-btn:hover:not(:disabled) { background: #e65100; }
.submit-approval-btn:disabled { background: #ccc; cursor: not-allowed; }
.avatar-img {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
}
</style>
