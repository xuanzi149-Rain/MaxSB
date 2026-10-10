import { createApp } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import Evaluation from '../../ui/src/views/application-evaluation/index.vue'
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:id', component: Evaluation }] })
router.push('/demo')
router.isReady().then(() => createApp(Evaluation).use(router).use(ElementPlus).mount('#app'))
