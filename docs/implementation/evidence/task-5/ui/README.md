# 组件浏览器验证

截图来自实际 ToolRecovery Vue 组件，API 为明确标注的虚构 Axios adapter。真实 HTTP/权限和实际 MCP 传输由 application-tests.txt 中的 LiveServer/Transport 测试验证。这不是完整登录态端到端测试。

复现：将 task5-preview.ts 放到 ui/src/，task5-preview.html 和 vite.task5-preview.ts 放到 ui/，在 ui/ 运行 `vite --config vite.task5-preview.ts --host 127.0.0.1 --port 5177`，打开 `/task5-preview.html`。结束后移除这三个临时入口。

已观察：失败步骤和成功前缀显示；恢复请求期间按钮禁用；成功后原回答被替换，成功前缀未产生新 attempt；恢复按钮消失。已保存默认桌面宽度和390px移动宽度截图。

未在浏览器验证：真实账号登录、管理确认提交、断网后的自动刷新和完整SSE断流。请求重发/并发/隐藏详情由后端测试分别验证，不混称为浏览器端到端覆盖。
