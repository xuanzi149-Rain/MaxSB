# 任务 0：上游已有功能与增量边界

基线：MaxKB `v2`，提交 `4aad53c4316f956ecef69e1dc5d3ab3a1e80080b`。以下是源码检查结果，不代表功能运行验收。

| 领域 | 上游已有实现位置 | 后续增量边界 |
| --- | --- | --- |
| RAG 检索 | `apps/knowledge/vector/pg_vector.py` 提供向量检索及命中测试；`apps/application/flow/step_node/search_knowledge_node/` 已有知识检索节点、`top_n` 与相似度配置 | 任务 2 增加可关闭的证据去重与预算控制；任务 3 增加检索前的动态参数决策。不得把原有检索算作新贡献。 |
| 聊天上下文 | `apps/application/flow/step_node/ai_chat_step_node/impl/base_chat_node.py` 已按 `dialogue_number` 选取历史轮次，记录 token；`apps/chat/views/chat_record.py` 提供历史记录接口 | 任务 4 只增加可追溯的结构化事实记忆与管理入口。 |
| 工具与工作流 | `apps/application/flow/workflow_manage.py` 运行工作流；`apps/application/flow/step_node/tool_node/` 执行工具节点，另有 MCP 节点 | 任务 5 应选定一个节点类型补充受限重试、恢复状态和副作用保护，先核对实际异常语义。 |
| 多模型 | `apps/models_provider/` 已有供应商抽象与模型管理 API；AI 聊天节点已有模型配置和 token 记录 | 任务 6 只增加可解释路由、校验失败升级与两次调用成本汇总。 |
| 评测 | `apps/knowledge/vector/pg_vector.py` 有 `hit_test`，但它是检索命中测试；仓库内尚未确认存在任务 1 要求的批量问答、逐题判分与版本对照报告 | 任务 1 复用现有聊天接口和节点详情，新增完整批量评测能力。 |

`AGENTS.md` 指明后端入口为 `main.py`，Python 3.11、Django 5.2、PostgreSQL/pgvector、Redis、Celery；前端为 `ui/` 下 Vue 3。`.github/workflows/` 现有构建发布、代码审查、翻译、拼写检查与同步流程，尚未发现覆盖 Python 测试及前端类型检查的通用 CI。后续只补必要检查，不替换发布流程。
