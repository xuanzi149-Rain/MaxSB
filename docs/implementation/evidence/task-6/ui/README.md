# 任务6组件验证

使用真实 ModelRoutingConfig、ModelSelect、ModelRoutingDetails 组件，模型清单与执行数据是明确标注的夹具。已操作默认关闭到开启、两模型选择、自定义 answer 字段和展开升级详情；未知用量/费用显示 —。桌面1280×900、窄屏390×844截图；窄屏表格在内部横向滚动，文档宽度384小于viewport390。截图为浏览器原始输出。

复现：把本目录 task6-preview.ts 放到 ui/src/，HTML和vite配置放到ui/，在ui/运行 vite --config vite.task6-preview.ts --host 127.0.0.1 --port 5179。验证后移除三个临时入口。未部署生产，不将组件夹具当作真实HTTP保存验收。
