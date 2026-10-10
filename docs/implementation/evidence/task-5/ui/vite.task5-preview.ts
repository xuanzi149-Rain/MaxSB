import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
export default defineConfig({plugins:[vue(),{ name:'preview-route', configureServer(server) {
 server.middlewares.use((req,_res,next)=> { if (req.url?.startsWith('/admin/task5-preview.html')) req.url=req.url.replace('/admin/','/'); next() })
}}],resolve:{dedupe:['vue','pinia'],alias:{'@':fileURLToPath(new URL('./src',import.meta.url))}},envDir:'./env'})
