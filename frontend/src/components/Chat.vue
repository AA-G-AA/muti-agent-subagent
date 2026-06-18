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
          <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="bubble" v-html="msg.renderedContent"></div>
        </div>
        <div v-if="loading" class="message assistant">
          <div class="avatar">🤖</div>
          <div class="bubble loading-dots">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          </div>
        </div>
      </div>

      <div class="input-area">
        <textarea v-model="inputMessage" placeholder="输入你的消息..."
          @keydown.enter.exact="sendMessage" :disabled="loading" rows="1"></textarea>
        <button @click="sendMessage" :disabled="loading || !inputMessage.trim()">发送</button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'

const messages = ref([])
const inputMessage = ref('')
const loading = ref(false)
const sidebarCollapsed = ref(false)
const messagesRef = ref(null)
const sessions = ref([])
const currentSessionId = ref(null)
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

      // if (data.type === 'token') {
      //   // 流式 token，追加到最后一个 assistant 气泡
      //   const last = messages.value[messages.value.length - 1]
      //   if (last && last.role === 'assistant') {
      //     last.content += data.content
      //     last.renderedContent = marked(last.content)
      //   } else {
      //     // 第一个 token，新建气泡
      //     messages.value.push({ role: 'assistant', content: data.content, renderedContent: marked(data.content) })
      //   }
      //   scrollToBottom()
      // } else 

      if (data.type === 'result') {
        // 一次性返回整个回复
        messages.value.push({ role: 'assistant', content: data.content, renderedContent: marked(data.content) })
        loading.value = false
        scrollToBottom()
      } else if (data.type === 'done') {
        // 本轮结束
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
.message { display: flex; gap: 12px; padding: 12px 20px; max-width: 800px; margin: 0 auto; width: 100%; }
.message.user { flex-direction: row-reverse; }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; background: #f0f0f0; }
.message.user .avatar { background: #10a37f; }
.bubble { padding: 10px 16px; border-radius: 12px; line-height: 1.6; font-size: 15px; max-width: 80%; word-wrap: break-word; }
.message.user .bubble { background: #10a37f; color: #fff; border-bottom-right-radius: 4px; }
.message.assistant .bubble { background: #f7f7f8; color: #333; border-bottom-left-radius: 4px; }
.bubble :deep(p) { margin: 0 0 8px; }
.bubble :deep(p:last-child) { margin-bottom: 0; }
.bubble :deep(code) { background: #e8e8e8; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
.bubble :deep(pre) { background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
.bubble :deep(pre code) { background: none; padding: 0; font-size: 13px; }
.bubble :deep(ul), .bubble :deep(ol) { padding-left: 20px; margin: 8px 0; }
.bubble :deep(a) { color: #10a37f; text-decoration: none; }
.bubble :deep(a:hover) { text-decoration: underline; }
.bubble :deep(blockquote) { border-left: 3px solid #10a37f; margin: 8px 0; padding-left: 12px; color: #666; }
.loading-dots { display: flex; gap: 6px; align-items: center; min-height: 36px; }
.dot { width: 8px; height: 8px; background: #999; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }
.input-area { display: flex; gap: 8px; padding: 16px 20px; border-top: 1px solid #e5e5e5; max-width: 800px; margin: 0 auto; width: 100%; }
.input-area textarea { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 15px; resize: none; outline: none; line-height: 1.5; max-height: 150px; font-family: inherit; }
.input-area textarea:focus { border-color: #10a37f; }
.input-area button { padding: 10px 24px; background: #10a37f; color: #fff; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; white-space: nowrap; }
.input-area button:hover:not(:disabled) { background: #0e8c6b; }
.input-area button:disabled { background: #ccc; cursor: not-allowed; }
</style>
