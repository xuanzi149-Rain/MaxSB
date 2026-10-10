import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import '@/styles/index.scss'
import 'element-plus/dist/index.css'
import { i18n } from '@/locales'
import Recovery from '@/components/ai-chat/component/tool-recovery/index.vue'
import { request } from '@/request/chat'
i18n.global.locale.value = 'zh-CN'
const state: any = { id: 'fixture-run-001', record_id: 'record-001', status: 'failed', version: 2, resumes: 0, can_resume: true,
 steps: [{ node_id: '读取资料', status: 'succeeded', attempts: [{ id: 1, generation: 1, status: 'succeeded', started_at: '10:00:00', ended_at: '10:00:01' }] },
 { node_id: '查询库存', status: 'failed', error_type: 'timeout', attempts: [{ id: 2, generation: 1, status: 'failed', error_type: 'timeout', started_at: '10:00:01', ended_at: '10:00:11' }] }] }
request.defaults.adapter = async config => {
 console.info('fixture-request', config.method)
 if (config.method === 'post') {
  await new Promise(resolve => setTimeout(resolve, 500))
  state.status = 'succeeded'; state.can_resume = false; state.resumes = 1; state.version = 4
  state.steps[1].status = 'succeeded'; state.steps[1].error_type = ''
  state.steps[1].attempts.push({ id: 3, generation: 2, status: 'succeeded', started_at: '10:01:00', ended_at: '10:01:01' })
  state.answer_text = '库存查询已恢复，前一步资料读取没有重复执行。'
 }
 return { data: { code: 200, data: config.method === 'post' ? structuredClone(state) : [structuredClone(state)] }, status: 200, statusText: 'OK', headers: {}, config }
}
const answer = ref('本条回答在工具超时后中断。')
createApp({ render: () => h('main', { style: 'max-width:800px;margin:24px auto;padding:12px;font-family:system-ui' }, [h('h2', '工具恢复 · 受控组件验证'), h('p', '虚构数据；后端鉴权及真实MCP传输另有独立测试。'), h('article', {style: 'padding:16px;background:#f3f5f8;margin:16px 0'}, answer.value), h(Recovery, {chatId:'fixture', onRecovered:(run:any)=> { answer.value=run.answer_text }})]) }).use(createPinia()).use(i18n).use(ElementPlus).mount('#app')
