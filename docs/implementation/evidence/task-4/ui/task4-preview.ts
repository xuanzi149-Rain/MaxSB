import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import '@/styles/index.scss'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { i18n } from '@/locales'
import Memory from '@/components/ai-chat/component/conversation-memory/index.vue'
import { request } from '@/request/chat'
i18n.global.locale.value = 'zh-CN'
Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })
let conflictOnce = true
const state: any = { version: 1, generation: 0, facts: [{ id: 'budget', entity: '旅行', attribute: '预算', value: '3000元', status: 'confirmed', source: 'turn1', quote: '我的旅行预算为3000元', updated_at: '2026-10-10 13:30' }], sources: [{ id: 'turn1', record_id: '第1轮', question: '我的旅行预算为3000元' }] }
request.defaults.adapter = async (config) => {
  const data = config.data ? JSON.parse(config.data) : {}
  if (config.method === 'patch') {
    if (conflictOnce) { conflictOnce = false; state.version++; throw { response: { status: 409 } } }
    if (data.operation === 'revoke') state.facts = []
    else state.facts[0] = { ...state.facts[0], value: data.value, status: 'confirmed' }
    state.version++
  }
  if (config.method === 'delete') { state.facts = []; state.version++; state.generation++ }
  return { data: { code: 200, data: structuredClone(state) }, status: 200, statusText: 'OK', headers: {}, config }
}
createApp({ render: () => h('main', { style: 'max-width:800px;margin:64px auto;font-family:system-ui' }, [h('h1', '会话记忆'), h('p', '受控界面验证：查看来源、纠正预算、清除记忆。数据为测试样例。'), h(Memory, { chatId: 'fixture', debug: false, applicationId: 'fixture' })]) }).use(createPinia()).use(i18n).use(ElementPlus, {locale: zhCn}).mount('#app')
