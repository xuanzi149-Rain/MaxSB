# 任务5合并与本机测试部署

2026-10-10，用户明确授权“进行部署合并”。在任务4既有隔离测试环境升级任务5，不扩大到生产。

## 合并及版本

- 合并目标：`task0-local-model-baseline`，从`b93c706ae`快进到`b005600b8`（功能提交`32adf656d`）。
- 合并前重新运行97项application测试通过；实际发布归档源码再次运行97项通过。
- 主目录原未跟踪设计/计划草稿与已提交版本相同或为前缀，原件保存到`/private/tmp/task5-merge-drafts-20261010/`，未覆盖丢弃。
- 两端使用上一轮已验证的生产构建，实际部署入口HTML及JS逐一HTTP 200，哈希在`evidence/task-5-rollout/release.json`。

## 运行位置

- 入口：`http://127.0.0.1:8084/admin/`及`/chat/`，仅本机回环。
- 容器：`maxkb-task0`；新版本源码`/tmp/maxsb-task5-staging`，静态资源`apps/static/{admin,chat}`；旧版本`/tmp/maxsb-task4-staging`保留。
- 沿用独立数据库`maxsb_task4_staging`、进程内隔离缓存和内存任务队列。原8080服务源码和`maxkb`业务数据库没有部署任务5。
- 原8084服务在本轮开始前已停止；现由`/tmp/task5-stage-control.py serve`监听容器内18084，沿用本机8084转发进程。
- 现有应用未自动启用恢复；部署探针先启用验证，再关闭恢复并停用访问令牌。现有任务4应用的记忆配置保持原状。
- 沙箱仍为1；未扩大网络白名单或绕过回环禁用。

## 数据与验收

1. 迁移前导出`/opt/maxkb/rollback/task5-staging/pre-0017.dump`，目录0700、文件0600；真实恢复到新临时库逐表核对后删除临时库。
2. 在隔离库应用`0017_tool_recovery`，迁移前后原应用、6个会话、12条聊天记录、4份记忆、14条事件的完整行哈希一致。冒烟后再次核对旧数据一致。
3. 实际8084 API：真实匿名鉴权、两节点串行执行成功、运行和步骤持久化、公开响应不含内部details；重启进程后原身份仍可读取成功运行。
4. 关闭恢复后重新开始聊天，不产生ToolRun；两端页面和入口JS均200。最终探针令牌停用，临时模型协议服务停止。
5. 原业务数据库没有任务5表和0017迁移。恢复后的8080原服务HTTP 200。

探针使用本机确定性OpenAI协议服务，仅证明真实应用执行与恢复状态落库，不调用真实供应商，不代表模型质量评测。MCP响应丢失/重试、并发和旧代次隔离沿用本轮97项测试中的真实传输/数据库证据；未把部署探针称作完整工具故障演练。初始探针仅含开始节点，被现有发布验证正确拒绝；修正为合法文本AI工作流后通过。

## 故障与资源限制

本轮并行验证期间容器发生一次OOM退出，Docker标记`OOMKilled=true`。已重启恢复原8080服务，保留数据库和发布文件；改为顺序执行、在运维进程运行前停测试服务后，所有验收通过。完成工作流冒烟时内存约2.35/3.83GiB。这是共享Docker内存受限的本机测试部署，不保证高并发容量；不要同时运行多份完整Django回归、构建和部署验证进程。

未配置Docker重启后的自动拉起、生产TLS、长期监控；8084仍为开发测试服务，不作为生产发布声明。内存压力可能影响同容器的8080服务，需正式环境资源规划后再扩大使用。

## 操作与回退

- 启动：`docker exec -d -w /tmp/maxsb-task5-staging maxkb-task0 sh -c 'exec /opt/py3/bin/python -u /tmp/task5-stage-control.py serve > /tmp/task5-stage-server.log 2>&1'`。
- 状态：容器内`/opt/py3/bin/python /tmp/task5-stage-control.py status`；日志`/tmp/task5-stage-server.log`，PID`/tmp/task5-stage-server.pid`。停服务前须确认PID命令行确为该脚本，避免PID重用误伤。
- 本机转发：仓库`docs/implementation/scripts/proxy_task4_acceptance.py`仍转发8084到18084；已存在监听时不要重复启动。
- 代码回退：停新测试服务，再从旧目录运行`/tmp/task4-stage-control.py serve`；旧代码忽略新增表。先关闭功能即可停用，不需要删除恢复记录。
- 数据库回退会删除新记录，不做常规开关手段；备份仅用于明确授权的恢复。备份映射宿主机`/private/tmp/maxkb-task0-data/rollback/task5-staging/`，不提交Git。
- 运维脚本见`evidence/task-5-rollout/ops/`，仅针对本机固定测试环境；访问令牌、签名密钥和数据库备份均不入库。
