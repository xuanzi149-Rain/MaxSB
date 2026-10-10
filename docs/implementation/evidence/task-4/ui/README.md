# UI 组件验证

真实 ConversationMemory 组件、项目样式和现有 Axios client；适配器返回虚构状态，没有连接生产 API。

已验证：打开/查看原话与轮次；纠正 3000→4000；第一次 PATCH 返回 409，提示冲突且保留草稿；再次编辑初值为 4000，重试成功；清除确认与空状态。测试页将 crypto.randomUUID 设为 undefined，修改仍成功。桌面及 390×844 截图无溢出。

- desktop.png：纠正成功及来源展开。
- mobile.png：移动宽度布局。
- conflict.png：冲突提示。

重现夹具：将 task4-preview.ts 放到 ui/src/，其余两个文件放到 ui/；用仓库 Node/Vite 运行 `vite --config vite.task4-preview.ts --host 127.0.0.1 --port 5176`，打开 `/task4-preview.html`。仅用于本地组件测试，测试后删除这三个临时入口；不能打包为产品页面。

此验证不证明真实登录/HTTP、调试权限、嵌入宿主完整端到端通过；后端 API 与权限另有数据库测试。
