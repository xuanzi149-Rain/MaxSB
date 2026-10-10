# 任务 5 工具恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans 或 superpowers:subagent-driven-development 逐任务执行；以下复选框记录实际进度。

**Goal:** 在正式串行工作流的 MCP 节点实现安全重试、持久检查点和受权限保护的失败处恢复。

**Architecture:** 新增独立 tool_recovery 服务，负责配置、状态、调用与恢复，工作流仅接入生命周期钩子。沿用 Django 事务、聊天身份和 MCP backend；默认关闭，不更改旧流程行为。

**Tech Stack:** Python 3.11、Django、PostgreSQL、现有 MCP SDK、Vue 3 / Element Plus。

**Spec:** [已确认设计](task-5-design.md)。当前实现基线 `b93c706ae`；任务 4 已实现。

## Global Constraints

- 正式聊天、顶层串行、开始/MCP/无工具文本 AI 节点；分支、循环、异常分支、子流程、暂停、多模态及调试持久恢复在首次工具调用前拒绝。关闭配置不应用这些限制。
- 单次超时默认 10 秒、范围 1–120；最多重试默认 2、范围 0–5；退避 0.5/1/2/4/8 秒；人工恢复最多 3 次。
- 默认副作用模式 unknown；只有只读或工具侧保证幂等的写入允许自动重试。未知写入不自动继续。
- 稳定幂等键绑定原运行和节点，恢复不得替换输入；版本、工具定义、授权须重新核验。
- 外部调用不持有数据库锁；状态提交必须验证认领代次；租约过期不代表远端执行取消。
- 不保存认证头、连接密钥或任意 pickle；普通轨迹只展示允许字段。未知计量不填零。
- 不迁移正在提供服务的数据库，不自动发布或修改已有应用，不全仓自动格式化。

## Review Focus

1. 远端写入已完成、本地成功检查点落库失败：保留未知或用原键核对，不能重做无保护写入（任务 2/3）。
2. 租约到期后旧执行器仍存活：旧代次不得提交或启动下游，远端幂等仍由工具保证（任务 2/4）。
3. AI 节点已更新任务 4 记忆但工具失败：恢复成功 AI 检查点，不再次提取或回答（任务 4）。
4. 工具删除、停用、权限撤销或定义变化：恢复时重新检查，禁止借快照继续（任务 5）。
5. 浏览器断流和重复点击：相同 request_id 不再次执行，已显示内容不能重复追加（任务 5/6）。

## 文件与接口

新增 `apps/application/tool_recovery/`：types.py 为契约，policy.py 为错误分类/重试规则，config.py 为工作流校验，store.py 为事务状态，executor.py 为 MCP 尝试，runtime.py 为工作流恢复。

新增 `apps/application/models/tool_recovery.py`，在 models/__init__.py 导出，迁移使用当前 0016 后的下一个未占用编号。新增 `apps/chat/serializers/tool_recovery.py`、`apps/chat/views/tool_recovery.py`，分别处理请求校验和权限 API。

界面接入 `ui/src/workflow/nodes/start-node/index.vue`、`mcp-node/index.vue`、共享聊天组件及 `execution-detail-card/index.vue`，细节抽到独立组件，不重排已有大型文件。

## 0. 执行环境与证据

- [ ] 使用 using-git-worktrees 技能检查现有附属工作树、分支和在用状态，选择隔离检出并带入本设计/计划，不覆盖其他工作。
- [ ] 核验 Python、Node、容器和测试数据库环境；记录基线 SHA 和工作区状态到 `docs/implementation/evidence/task-5/`。读取实际 CI，保留上游任务。
- [ ] 新增 `docs/implementation/scripts/run_task5_tests.py`，沿用任务 4 测试库隔离方式但固定独立库名 `test_maxsb_tools_task5`；验证失败退出码及 teardown，不复用服务库连接。

## 1. 配置、错误和状态契约

**Files:** 新增 tool_recovery/{types,policy,config}.py、`tests/tool_recovery/test_policy.py`、`test_config.py`；修改 `apps/application/flow/common.py`、MCP serializer 和开始节点 serializer。

**Interfaces:** `RecoveryPolicy`、`Identity`、`Claim`、`AttemptOutcome` 数据契约；`classify_error(error) -> str`、`can_retry(policy, error_type, attempt_number) -> bool`、`validate_recovery_workflow(workflow) -> None`。状态与副作用模式严格使用设计中的枚举。

- [ ] 写测试断言首次+2次重试共3次、认证/参数/isError不重试、未知异常保守终止、无保护写入超时未知、配置边界和关闭策略兼容。
- [ ] 运行 `PYTHONPATH=apps python3 -m unittest discover -s tests/tool_recovery -v`，确认失败来自缺失行为。
- [ ] 实现严格字段/数值校验和串行图检查，导入/发布/运行共用同一校验器；AI 开启工具或多模态时拒绝，记忆开关本身不拒绝。
- [ ] 重跑通过，保存红绿证据，提交本任务文件。

## 2. 持久化、并发与检查点

**Files:** 新增 models/tool_recovery.py、迁移、tool_recovery/store.py、`apps/application/tests_tool_recovery_store.py`。

**Interfaces:** `RecoveryStore.create(identity, chat_id, record_id, snapshot)`、`claim(identity, run_id, request_id, expected_version) -> Claim`、`begin_attempt(claim, node_id, inputs)`、`finish_attempt(claim, attempt_id, outcome)`、`checkpoint(claim, node_id, output, variables)`、`heartbeat(claim)`。Claim 含运行ID、代次、租约期限。

- [ ] 先写事务测试：相同请求返回原认领，不同并发请求409；旧代次写入/推进拒绝；步骤和尝试唯一约束；回滚不能出现成功步骤；跨会话与逻辑删除不可见。
- [ ] 运行 `python docs/implementation/scripts/run_task5_tests.py application.tests_tool_recovery_store` 记录失败。
- [ ] 实现运行/步骤/尝试模型与短事务；认领租约60秒、每15秒心跳，远端调用前检查代次；恢复窗口24小时且不得超过工具声明的幂等保留期。JSON快照每步上限1MiB、整次运行10MiB，超限在调用前拒绝。
- [ ] 保留敏感业务输入仅供内部恢复，GET输出单独白名单；工具连接凭据单独解析，不放通用快照。进程消失按工具模式处理，不把 running 自动改成 failed 后无条件重跑。
- [ ] 跑并发事务、迁移往返和一致性检查；已有 migration drift 单独记录，全部目标测试通过后提交。

## 3. MCP 执行与故障注入

**Files:** 新增 tool_recovery/executor.py、`apps/application/tests_tool_recovery_executor.py`、`tests/tool_recovery/fault_server.py`；修改 MCP BaseMcpNode 和 sandbox_mcp.py 的最小必要入口。

**Interfaces:** `execute_mcp(claim, node_id, policy, backend, server, tool, arguments) -> AttemptOutcome`。消耗任务1策略和任务2状态；backend继续使用现有 session。

- [ ] 写受控异步故障服务：只读超时、暂时失败、MCP isError、写入成功响应丢失、慢响应；记录原键和实际写入次数。
- [ ] 先测失败：重试上限、真实等待超时、未知写入不重试、同键写入仅一次、成功后数据库失败不继续；工具Schema没有幂等字段拒绝幂等模式。
- [ ] 实现每次调用的超时、有限退避、严格错误分类、稳定键注入、每次尝试开始/结束记录。取消本地等待不声称远端停止。
- [ ] 运行 `python docs/implementation/scripts/run_task5_tests.py application.tests_tool_recovery_executor`，覆盖实际 MCP transport 与 sandbox 开关两条路径；通过后提交。

## 4. 工作流恢复集成

**Files:** 新增 tool_recovery/runtime.py、`apps/application/tests_tool_recovery_runtime.py`；修改 workflow_manage.py、i_step_node.py 和 chat/serializers/chat.py。

**Interfaces:** `RecoveryRuntime.start(identity, workflow, params)`、`before_node(node)`、`after_node(node, result)`、`resume(claim, workflow, params)`；共享 task2 Claim。将串行调度生命周期接入现有引擎，关闭策略不构造运行记录。

- [ ] 写实际引擎测试：工具A成功/B失败→恢复只调用B；成功AI节点恢复不再次回答或更新记忆；部分流式AI答案不算完成；缓存丢失后仍从数据库恢复。
- [ ] 执行 runtime 测试标签见失败；实现完整输出/变量/节点上下文检查点以及版本指纹。成功检查点必须在推进下游前保存，未知状态阻断。
- [ ] 恢复载入冻结业务输入和成功步骤，仅从失败MCP继续；新请求不得借 re_chat/start_node_id 绕过保护，原运行被新聊天分支替代时拒绝继续。
- [ ] 重跑流式/非流式、任务4记忆集成、旧路径兼容以及过期旧执行器不启动下游的行为测试，通过后提交。

## 5. 权限 API 与人工结果确认

**Files:** 新增 chat/{serializers,views}/tool_recovery.py、`apps/application/tests_tool_recovery_api.py`；修改 chat/urls.py 和 application/urls.py。

**Interfaces:** GET聊天运行详情；POST resume提交UUID request_id和expected_version。管理端 `POST .../tool_runs/{run_id}/resolution` 提交同样版本/请求标识、结论、证据和必要输出，复用应用管理权限装饰器。

- [ ] 先写API测试：跨应用/用户/客户端拒绝、逻辑删除/分享身份拒绝、并发409、相同请求幂等；工具停用/撤权/定义变化拒绝；不得提交自选输入或节点。
- [ ] 实现归属校验先于内容解析，恢复前重新解析当前授权工具与发布版本。未知结果确认持久化操作者和证据；普通聊天身份不可调用管理确认。
- [ ] “已执行”输出须满足存储的工具契约；“未执行”须填写终止和无副作用核对证据；不确认继续保持未知。所有确认走版本控制，审计不能被后续请求覆盖。
- [ ] 运行 API 测试标签并通过真实HTTP鉴权测试，通过后提交。

## 6. 配置、轨迹与恢复 UI

**Files:** 新增 `ui/src/api/chat/tool-recovery.ts`、`ui/src/components/execution-detail-card/component/ToolRecoveryDetails.vue`；修改开始/MCP节点、执行详情、`ui/src/components/ai-chat/index.vue`；更新 zh-CN/en-US/zh-Hant 文案。

**Interfaces:** UI消费任务5的状态、允许操作、版本、尝试和脱敏结果；错误原因由服务端枚举映射，不解析堆栈猜测。

- [ ] 配置默认关闭，超时/重试边界与服务端一致，写入幂等契约须显式填写；未知结果禁用普通恢复。
- [ ] 增加逐步骤/尝试轨迹及恢复来源；继续按钮沿用同一请求UUID处理网络重发，409刷新状态。历史输出按运行/步骤ID合并，不能重复追加SSE答案。
- [ ] 管理端显示未知结果确认表单和审计，只有现有管理权限入口可见；服务端仍独立鉴权。
- [ ] 浏览器真实HTTP验证失败→恢复、重复点击、断流、版本变化和未知写入，保存桌面/移动证据。运行局部只读 ESLint、`npm run type-check`、管理/chat构建，通过后提交。

## 7. 故障报告与交付

**Files:** 新增 `docs/implementation/scripts/run_task5_faults.py`、`tests/tool_recovery/test_report.py`、`docs/implementation/task-5.md`、evidence/task-5；更新 skill-application.md。

- [ ] 报告测试先失败：所有失败保留在分母，未知费用保持null，重复输出目录拒绝覆盖，实际写入计数不能以调用次数替代。
- [ ] 执行故障矩阵（成功、只读超时恢复、暂时失败、永久错误、幂等写入响应丢失、无保护未知、并发恢复、版本变化、进程中断），记录源码/配置/输入指纹及每次尝试。
- [ ] 报告完成率、重复副作用、两种恢复耗时、额外模型调用/token/费用。可用受控模型验证恢复不重跑AI；真实供应商额外调用须核验当前预算授权，不以fake结果冒充真实模型效果。
- [ ] 最终运行纯测试、application目标集及任务2/3/4相关回归、迁移检查、改动Python检查、只读全量ESLint、类型检查和两端构建。基线失败必须保留并解释。
- [ ] 按 requesting-code-review 技能进行最终审阅，修复后仅重复相关验证；用 verification-before-completion 核对实际证据，记录剩余限制再交付。

## 自审与执行交接

已将确认设计中的范围、未知结果、幂等、版本、认领、快照、权限、界面、计量和故障验收映射到具体任务；Review Focus五项分别有测试归属。当前未执行上述测试、未编写产品代码。

推荐在本会话顺序执行，由同一实现者维护调度和事务契约，最后独立审阅；也可逐任务使用子代理实现与审阅。计划待用户审阅并选择执行方式。

## 实施记录（2026-10-10）

用户已选择本会话顺序实施、最终独立审查。已按任务0–7落实策略、状态、执行器、调度、API、UI与报告；接口以最终源码为准（API直接复用现有request客户端，无独立tool-recovery.ts）。上方复合检查框保留原始验收清单，不以勾选掩盖尚未覆盖的联调组合；实际逐项证据、命令与限制统一记录在task-5.md。

独立审查发现并修复：最终写回缺少代次隔离、完成状态早于记录落库、恢复缓存丢失历史、答案重复显示、写后检查点失败误分类、公开轨迹泄漏、崩溃补写未失效缓存、节点之间退出无法继续。最终复审未发现阻断问题。另通过真实HTTP发现并修复恢复线程数据库连接清理。

验收调整：沙箱开启时必须保留回环地址禁用，验证其拒绝且无副作用；允许的远端服务内响应丢失仍待部署联调。浏览器使用明确标注的组件fixture，真实鉴权/恢复另由LiveServer测试覆盖，未冒充完整登录用户操作。真实供应商模型/付费工具未调用。
