# 任务 5/6 联调记录

日期：2026-10-11。范围是任务 6 隔离源码和独立测试库 `test_maxsb_routing_task6`；没有修改 8080 服务或 `maxkb` 业务库。任务 6 的正式质量、费用和人工验收另行判定。

## 联合工作流

在同一顶层串行工作流中开启工具恢复和模型路由：低成本模型输出不符合 JSON 契约，升级到高能力模型并保存 AI 检查点；下游 MCP 工具超时，随后以签名聊天身份通过真实 HTTP `/chat/api/tool_runs/{id}/resume` 恢复。

独立测试验证路由产生两个不同的调用 ID，合计用量为 20 输入、4 输出 token；恢复前后 AI 检查点中的路由轨迹、调用 ID 和用量完全一致，模型调用数保持 2，最终只保存一条聊天记录。恢复响应不暴露内部 `details`。这里使用受控模型和工具，证明执行、持久化及 HTTP 边界，不代表供应商答案质量。

任务 5 的真实 MCP 故障服务测试同时验证：响应丢失时同一幂等键下发生两次请求、一次实际写入；沙箱开启时回环请求被拒绝，远端写入为 0。没有为联调放宽沙箱策略。

## 本轮验证

- 隔离库运行 `application.tests_tool_recovery_transport application.tests_tool_recovery_http application.tests_model_routing_integration`：10 项通过，包含新增的真实 HTTP 联合恢复测试。
- 隔离库运行 `application.tests_evaluation_runner application.tests_evaluation_api`：15 项通过，包含延迟提交回调下 broker 故障状态测试。
- 隔离库运行 `application` 全量回归：124 项通过；数据库迁移至 `0019_nullable_chat_usage` 后自动销毁测试库。
- 修改的两个 Python 测试文件运行 Ruff：通过；`git diff --check`：通过。
- Vue `vue-tsc --build`、管理端与聊天端 Vite 生产构建均以退出码 0 完成；构建保留项目原有的 `eval` 和大 chunk 警告。

本轮新修改的差异空白检查通过；全任务 6 分支的 `git diff --check` 仍会标记已提交原始构建/失败日志中的行尾空格和末尾空行。这些日志保持原貌以保留失败证据，未作为源码静态检查通过的依据。

测试均由 `docs/implementation/scripts/run_task6_tests.py` 创建、迁移并销毁专用测试库。任务 6 先前的 8084 发布、迁移和页面截图见 `evidence/task-6-rollout/`；本轮检查时 8084 的运行进程是任务 1–5 的 closure 版本，因此不把先前截图描述为当前在线版本。

## 仍需单独完成的验收

管理端浏览器登录触发验证码，任务 5 的登录态管理确认页面尚待用户完成验证；已有真实 HTTP 鉴权与恢复测试不能替代此项。任务 6 开发集三组各 20 题的机器运行已完成，但冻结 80 题三组、人工评分和实际账单未完成，不能据此报告成本优化。任务 6 合并到默认分支不自动切换 8080 服务或启用路由策略。
