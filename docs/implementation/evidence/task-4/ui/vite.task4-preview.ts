import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
export default defineConfig({plugins:[vue()],resolve:{dedupe:['vue','pinia'],alias:{'@':fileURLToPath(new URL('./src',import.meta.url))}},envDir:'./env'})
