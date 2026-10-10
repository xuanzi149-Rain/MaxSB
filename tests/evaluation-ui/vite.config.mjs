import { defineConfig } from '../../ui/node_modules/vite/dist/node/index.js'
import vue from '../../ui/node_modules/@vitejs/plugin-vue/dist/index.mjs'
import { fileURLToPath } from 'node:url'
import { realpathSync } from 'node:fs'
const here = fileURLToPath(new URL('.', import.meta.url))
export default defineConfig({ root: here, plugins: [vue()], resolve: { alias: [
  { find: '@/api/application/evaluation', replacement: here + (process.env.TASK1_UI_REAL ? 'api-real.ts' : 'api.ts') },
  { find: '@/utils/permission/data', replacement: here + 'permission.ts' },
  { find: '@/utils/permission', replacement: here + 'permission.ts' },
  { find: 'vue', replacement: fileURLToPath(new URL('../../ui/node_modules/vue/dist/vue.runtime.esm-bundler.js', import.meta.url)) },
  { find: 'vue-router', replacement: fileURLToPath(new URL('../../ui/node_modules/vue-router/dist/vue-router.mjs', import.meta.url)) },
  { find: 'element-plus', replacement: fileURLToPath(new URL('../../ui/node_modules/element-plus', import.meta.url)) },
] }, server: { host: '127.0.0.1', port: 18089, strictPort: true, fs: { allow: [fileURLToPath(new URL('../../', import.meta.url)), realpathSync(fileURLToPath(new URL('../../ui/node_modules', import.meta.url)))] } } })
