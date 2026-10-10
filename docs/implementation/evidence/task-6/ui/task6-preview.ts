import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElForm } from 'element-plus'
import 'element-plus/dist/index.css'
import '@/styles/index.scss'
import { i18n } from '@/locales'
import Config from '@/workflow/nodes/ai-chat-node/ModelRoutingConfig.vue'
import Details from '@/components/execution-detail-card/component/ModelRoutingDetails.vue'
import ModelSelect from '@/components/model-select/index.vue'
import useModelStore from '@/stores/modules/model'
i18n.global.locale.value = 'zh-CN'
const pinia = createPinia()
useModelStore(pinia).asyncGetProvider = async () => ({ data: [] })
const config = ref<any>({ enabled: false })
const trace = { reason: '单一抽取；首次结果未通过JSON校验', status: 'succeeded', upgrade_reason: 'invalid_json', attempts: [
 { role: 'low', model_name: 'qwen3.7-plus', status: 'failed', error: 'invalid_json', usage: {input_tokens: 120, output_tokens: 32}, elapsed_seconds: .4, priced_cost: '0.000496', actual_cost: null, currency: 'CNY', price_version: 'fixture-v1', price_basis: 'reference_price' },
 { role: 'high', model_name: 'deepseek-v4-flash', status: 'succeeded', usage: {input_tokens: null, output_tokens: null}, elapsed_seconds: 1.2 }
] }
const options = { fixture: [{id:'low', name:'MaxSB1 · qwen3.7-plus', status:'SUCCESS'}, {id:'high',name:'MaxSB2 · deepseek-v4-flash',status:'SUCCESS'}] }
createApp({render:()=>h('main',{style:'max-width:980px;margin:24px auto;padding:16px;font-family:system-ui'},[
 h('h2','模型路由 · 受控组件验证'),h('p','虚构用量与结果。测试默认关闭、配置选择、升级轨迹和未知费用显示。'),
 h(ElForm,{labelPosition:'top',style:'padding:16px;border:1px solid #ddd;border-radius:10px'},[h(Config,{modelValue:config.value,'onUpdate:modelValue':(v:any)=>config.value=v, options,nodeModel:{}})]),
 h('p',config.value.enabled ? '路由已开启（仅本页夹具）':'路由已关闭'),h(Details,{data:trace})
])}).use(pinia).use(i18n).use(ElementPlus).component('ModelSelect',ModelSelect).mount('#app')
