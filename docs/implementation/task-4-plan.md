# 任务 4：长对话结构化记忆实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 为工作流文本 AI 节点提供可追溯、可纠正、受预算约束的会话级事实记忆。

**Architecture:** 独立的会话状态与事件表承载事实版本，提取模型只返回候选操作。服务校验并提交操作，上下文选择器在回答前组合事实和原始消息。节点与聊天面板共享同一权限和版本边界。

**Tech Stack:** Python 3.11、Django、PostgreSQL、现有 LangChain 模型抽象、Vue 3、Element Plus。

**Spec:** [已确认设计](task-4-design.md)。2026-10-10 用户确认。计划待审阅与选择执行方式。

## Global Constraints

- 默认关闭；每个应用工作流只允许一个顶层、无工具、无多模态的文本 AI 节点开启；循环和其他工作流模式拒绝。
- 历史及记忆预算 2048 token，提取输入预算 4096 token，提取输出上限 1024 token，超时 20 秒；近期轮数沿用 dialogue_number。
- 最多 100 条有效／待确认事实，最多回查 20 轮；不静默丢弃条件，不自动回填历史。
- 当前用户消息不得因历史预算截断；提取失败本轮不注入未经核对的旧记忆；未知用量及费用不当作零。
- 清除不删除 ChatRecord 与历史回答轨迹；清除阻止旧任务写回及旧事实自动恢复。调试状态与正式数据分离。
- 更正、撤销和来源都必须持久可追溯；模型提取的引用匹配不代表语义正确。
- 沿用仓库最小改动原则，不新增供应商、不改发布配置、不扩大到普通问答管线；不自动格式化全仓库。
- 重点技能为上下文工程与记忆管理、Agent 系统设计与落地；验收证据依设计中的对应关系保存。

## Review Focus

1. 中文别名或两个实体具有相同属性：不能把不同商品的预算合并，归任务 1/3 测试。
2. 两个首次请求同时创建状态，以及清除和提取竞争：必须只有一份状态且旧代次不能复活，归任务 2 测试。
3. 断流、重答和来源消息尚未落库：保留真实原话且不能重复收费提取，归任务 2/5 测试。
4. 旧工作流通过导入、调试或 API 绕过发布 UI：服务端也拒绝不支持配置，归任务 4/5 测试。
5. 用户在回答流式输出期间纠正：不能承诺追溯修改已发出的回答，但下一请求必须读取新版本，归任务 5/6 测试。

## 文件与接口划分

新增 `apps/application/conversation_memory/`：`types.py` 定义数据契约，`policy.py` 处理纯状态转换，`store.py` 处理事务及权限，`extractor.py` 调用提取模型，`context.py` 选择消息，`service.py` 串联一次请求。业务处理不塞入已有大型节点文件。

新增 `apps/application/models/conversation_memory.py` 和迁移，模型在现有 `models/__init__.py` 导出。新增 `apps/chat/serializers/chat_memory.py`、`views/chat_memory.py`，注册到现有路由；调试视图在相同模块中独立实现并注册管理端路由。

修改 AI 节点 serializer、实现、工作流校验及完成回调，仅添加服务调用和用量汇总入口。前端新增记忆 API、共享记忆面板和详情组件，接入现有 AI 节点、共享聊天组件、执行详情卡及三种语言资源。

## 执行前检查

- [ ] 读取 using-git-worktrees 技能，检查附属工作树并选择可用隔离检出；保留已确认设计和本计划。记录起始 SHA、工作区差异和实际运行环境。
- [ ] 核验既有 `maxkb-task0` 容器、Python 3.11 与 Node 工具；此前运行路径仅为线索，不能当作当前可用事实。测试使用独立数据库，不迁移正在提供服务的数据库。
- [ ] 建立 `docs/implementation/scripts/run_task4_tests.py`：设置 apps 路径、web settings 和 Django test runner，支持传入测试标签，退出码等于失败状态；必须正常执行 teardown。数据库测试使用 TestCase/TransactionTestCase，不能沿用任务 3 全部 SimpleTestCase 的免数据库假设。

### 1. 事实契约与纯状态转换

**Files:** 新增 `conversation_memory/types.py`、`policy.py`、`tests/memory/test_policy.py`（前两者位于 apps/application）。

**Interfaces:** `Fact`、`Operation`、`MemorySnapshot`、`ChangeSet` 为 dataclass；状态统一使用 confirmed/pending/superseded/revoked。`apply_operations(snapshot: MemorySnapshot, operations: list[Operation]) -> ChangeSet` 不读数据库、不调用模型。ChangeSet 含新快照、实际变更和拒绝原因。

- [ ] 写测试：`test_replace_budget_retains_both_sources` 断言旧 3000 为 superseded、新 4000 为 confirmed；`test_ambiguous_conflict_requires_confirmation` 断言有效上下文不能将任一值当成确定条件；`test_revoke_excludes_condition` 断言撤销防水后无有效防水要求；`test_same_attribute_different_entities` 断言两个商品不合并；`test_capacity_does_not_drop_existing_facts` 断言第 101 条被拒并保留原 100 条。
- [ ] 运行 `PYTHONPATH=apps python3 -m unittest discover -s tests/memory -v`，确认失败来自待实现行为。
- [ ] 实现契约和状态转换；事实键分开记录实体与属性，值最多 2048 字符、引用最多 2048 字符、实体／属性各最多 128 字符。已撤销／替代的完整历史保存在事件中，不无限增长有效快照。
- [ ] 重跑同一命令，全部通过后提交此任务涉及文件。

### 2. 持久化、来源与并发

**Files:** 新增 `models/conversation_memory.py`、`conversation_memory/store.py`、`apps/application/tests_memory_store.py`、`0016_conversation_memory.py`；修改 models 导出。若实施时迁移编号已被占用，按实际依赖生成下一编号。

**Interfaces:** `MemoryStore.read(identity, chat_id) -> MemorySnapshot`；`begin_turn(identity, chat_id, record_id, question) -> TurnTicket`；`commit_turn(ticket, changes) -> MemorySnapshot`；`correct(identity, chat_id, fact_id, operation, expected_version, request_id) -> MemorySnapshot`；`clear(identity, chat_id, expected_version, request_id) -> MemorySnapshot`。types.py 定义 `Identity`（application_id/chat_user_id/chat_user_type）和 `TurnTicket`（请求、版本、代次、来源、处理状态）。

- [ ] 写数据库测试：两个首次创建请求仅产生一个状态；同 ticket 提交两次只产生一次变更；旧版本更新返回冲突；清除后旧 ticket 提交被拒；同一 request_id 清除重试不再递增代次；来源未落 ChatRecord 仍返回原话快照；其他会话 UUID 不可读；修改原话的重答被拒。
- [ ] 用 `PYTHONPATH=apps python docs/implementation/scripts/run_task4_tests.py application.tests_memory_store` 运行，先见预期失败。
- [ ] 实现两表、唯一约束和短事务。模型调用留在事务外；begin_turn 原子认领本轮，处理中重复请求返回冲突，不启动第二次调用。事件保存 received/completed/failed 状态；中断未完成的认领有 60 秒租约，租约过期重试只走保守回答并记录状态，不自动重复收费提取。
- [ ] 正式库只保存正式会话；实现独立调试存储适配器，使用现有调试缓存边界并标明临时性。清除保留不含原话及事实值的审计和幂等信息，递增代次并更新回查起点。
- [ ] 在独立测试库验证迁移应用／回退／再次应用，运行并发测试与 `makemigrations --check --dry-run`，全部通过后提交。

### 3. 受约束提取和上下文选择

**Files:** 新增 `conversation_memory/extractor.py`、`context.py`、`tests/memory/test_extractor.py`、`test_context.py`。

**Interfaces:** `extract_operations(model, question, snapshot, evidence, limits) -> ExtractionResult`；`select_context(question, snapshot, recent_turns, count_tokens, budget) -> ContextSelection`。types.py 定义 `ExtractionResult`（操作、状态、调用计量）及 `ContextSelection`（消息、事实 ID、来源、排除原因、计数方式）。

- [ ] 用 fake model 写测试：非法 JSON、伪造引用、别名歧义和模型输出中的额外字段均不能写事实；两款商品明确次序可关联“第二款”，多个候选则 pending；历史答案本身不能新增用户事实；超时只调用一次。
- [ ] 写预算测试：预算 2048 下整轮／整条选择，本轮更正优先；超长当前问题完整保留；早期来源按 ID 可回查但不越会话；清除起点以前证据不读取；tokenizer 失败明确标估计值。
- [ ] 运行纯测试确认失败，然后实现严格结构校验、原话匹配、提取提示和有界历史读取。所有数据库读取经任务 2 的权限边界。提取参数固定输出上限 1024、超时 20 秒，禁用自动重试；无法配置受控超时的供应商返回 unsupported，不以后台遗留线程假装超时取消。
- [ ] 按设计顺序选择事实和原始轮次；记忆块使用普通对话数据角色，系统指引只包含固定规则。模型“已确认”只表示用户明确陈述，未经可信规则判定的修改转 pending。
- [ ] 重跑纯测试，断言实际调用输入也遵守 4096 提取预算；全部通过后提交。

### 4. 工作流配置与兼容性校验

**Files:** 修改 `apps/application/flow/step_node/ai_chat_step_node/i_chat_node.py`、`apps/application/flow/common.py`；新增 `conversation_memory/config.py`、`apps/application/tests_memory_config.py`。

**Interfaces:** `parse_memory_policy(data: dict) -> MemoryPolicy`；`validate_memory_workflow(workflow) -> None`。节点 `memory_policy` 含 enabled、context_token_budget、extraction_input_token_budget、extraction_output_token_limit、extraction_timeout_seconds，缺失等于关闭。

- [ ] 测试关闭与缺失配置兼容；两个启用节点、循环、工具、多模态、其他模式及引用旧 memory 变量均拒绝；导入／调试／直接执行同样触发校验。
- [ ] 运行 `run_task4_tests.py application.tests_memory_config` 见失败，再实现 serializer 与公共验证入口；运行时再检查实际解析后的工具和多模态输入。
- [ ] 参数校验：三项 token 参数分别限制 128–32768、256–32768、128–4096；超时 1–60 秒。检查已解析模型容量，默认值严格沿用设计。失败返回字段级错误。
- [ ] 重跑目标测试及既有 application.tests_context/application.tests_retrieval，全部通过后提交。

### 5. AI 节点集成与完整计量

**Files:** 新增 `conversation_memory/service.py`、`apps/application/tests_memory_runtime.py`；修改 `ai_chat_step_node/impl/base_chat_node.py`、`apps/application/flow/i_step_node.py`，必要时在 `apps/chat/serializers/chat.py` 增加请求前验证。

**Interfaces:** `prepare_memory_context(identity, chat_id, record_id, question, model, policy, recent_turns) -> MemoryPreparation`；types.py 的 MemoryPreparation 含 ContextSelection、ExtractionResult 和本轮状态。任务 3 历史处理后调用此入口，回答前重新核对版本。

- [ ] 用真实节点和 fake model 测试：关闭无额外调用、原消息逐字一致；开启后实际回答输入含 4000 而不把 3000 作为现行条件；提取失败不注入旧记忆；清除竞争不复活；断流后原话可查；同轮重答只重复回答调用；回答中途更正于下一请求生效。
- [ ] 写计量断言：提取输入 10＋回答输入 20 汇总 30，输出同理；任何一项未知则总量未知；分项和总量不被重复求和；流式／非流式一致。
- [ ] 运行 `run_task4_tests.py application.tests_memory_runtime` 确认失败，再最小化接入服务、分项计量和详情。不把估算当实际 provider usage；脱敏错误只保存类型及受控描述。
- [ ] 运行节点测试和完整工作流测试，覆盖当前轮尚未落库、模型回答失败及任务 3 去重顺序；全部通过后提交。

### 6. 受保护 API 与聊天面板

**Files:** 新增 `apps/chat/serializers/chat_memory.py`、`apps/chat/views/chat_memory.py`、`apps/application/tests_memory_api.py`；修改 `apps/chat/urls.py`、`apps/application/urls.py`。新增 `ui/src/api/chat/chat-memory.ts`、`ui/src/components/ai-chat/component/conversation-memory/index.vue`、`ui/src/components/execution-detail-card/component/ConversationMemoryDetails.vue`；修改共享聊天组件、执行详情卡、AI 节点 index.vue 和 index.ts、现有中／英／繁语言文件。

**Interfaces:** GET 返回 version/generation/facts/sources/temporary；PATCH 接收 operation/value/expected_version/request_id；DELETE 接收 expected_version/request_id。正式 API 路径按设计；调试 API 位于现有工作流编辑认证边界，使用调试 cache ID，不接受正式 Chat 替代它。

- [ ] 写 API 测试：401、同应用不同用户、不同客户端类型、逻辑删除、分享链接不能读写；伪造身份字段无效；纠正成功后 GET 有新版本；过期版本 409；清除后事实和旧内容事件为空，ChatRecord 仍存在。
- [ ] 运行 `run_task4_tests.py application.tests_memory_api` 见失败，再实现权限过滤与视图，重跑通过。
- [ ] 实现面板的查看来源、纠正、确认、撤销和清除；409 刷新且不覆盖新状态，临时调试与清除范围有明确说明。节点开关默认关闭，详情展示实际选取内容与提取计量。
- [ ] 通过浏览器对桌面／移动／嵌入三种界面验证真实 API；运行 `npm run type-check`、局部 ESLint、管理端与 chat 模式构建。保留截图及失败清单，全部通过后提交。

### 7. 多轮对照与交付检查

**Files:** 新增 `docs/implementation/scripts/run_task4_comparison.py`、`tests/memory/test_report.py`、`docs/implementation/evidence/task-4/`、`docs/implementation/task-4.md`；更新 `docs/implementation/skill-application.md`。

**Interfaces:** 对照脚本接受 dataset-dir、split、output、budget-file；输出目录必须不存在。复用任务 1 的题目及计量约定，提前校验既有评测模块是否存在，不静默改用不一致格式。

- [ ] 报告测试断言：失败题保留、两次调用计量求和、未知不能转零、重复运行不能覆盖、源码／模型／数据集哈希齐全。先失败再实现脚本与统计。
- [ ] 建开发题和单独封存的验收题，覆盖超过 5 轮后回忆、更正、撤销、第二款、冲突、清除；冻结后不用于调参。对照关闭策略与开启策略的完整实际节点／API 链路。
- [ ] 核验原共享预算文件和当前授权上下文，使用预算保护调用，绝不复制凭据进报告。无可用条件时保存阻碍，不能把 fake model 结果当真实验收。
- [ ] 汇总正确率、遗漏／错误继承、全部调用 token、费用和耗时；人工评分单独标记复核人，未人工复核不宣称质量通过。任务 3 未完成的验收项继续列为限制。
- [ ] 最终运行纯测试、application 数据库／集成测试、迁移一致性、改动 Python Ruff、Vue 类型检查、两端构建及只读全量 ESLint。已有失败须对照起始 SHA；不运行全仓自动修复。
- [ ] 运行端到端“发送条件→长对话→纠正→查看来源→清除→下一轮”流程并保存证据；更新任务记录，再进行全分支独立审阅，修复问题后重复相应验证，提交交付记录。

## 自审与执行交接

已按设计核对数据、提取、状态、清除、预算、鉴权、调试、兼容性、计量及评测，各项均有对应任务；新增边界测试在 Review Focus 中映射。文中测试通过均为预期验收条件，当前尚未运行功能测试或实现代码。

建议在本会话顺序执行：这些任务共享事实契约、事务版本和模型输入接口，逐步集成更便于验证。另一选择是逐任务子代理实现并独立审阅，增加上下文与审阅成本。执行方式由用户审阅计划后选择。


## 实际执行状态（2026-10-10）

上述复合检查项保留原计划，不将部分覆盖的项目整项勾选。最终证据以 [task-4.md](task-4.md) 为准。

| 阶段 | 实际完成 | 保留边界 |
| --- | --- | --- |
| 1 状态语义 | 事实策略、来源、更正、冲突、撤销与容量测试 | 同义词不会自动合并 |
| 2 存储 | 正式/临时态、统一行锁、真实交错事务、幂等、清除标记、迁移往返 | 调试缓存到期允许丢失 |
| 3 提取和预算 | 严格 JSON/来源校验、明确序号回查、整条预算、失败保守退回 | 有界客户端适配器限 OpenAI 兼容 root_client |
| 4 配置 | 默认关闭、顶层单节点、工具/多模态/循环/旧 memory 模板拒绝 | 未新增供应商统一总上下文容量接口，沿用其错误处理 |
| 5 节点/计量 | 已处理节点历史与原始证据分离，流/非流实际用量；未知保留 None | 上游 ChatRecord 整数汇总仍可能显示 0，报告读取 memory.total_usage |
| 6 API/UI | 身份/版本过滤、修改来源、纠正/确认/撤销/清除、冲突草稿保留；两端构建 | 浏览器使用真实组件+受控适配器；未宣称生产登录/嵌入端到端完成 |
| 7 实测/审阅 | 开发集、封存首次验收、失败留存、修复后同集回归；独立代码审查 | 同集回归不再独立；正式人工质量复核待完成，实账费用未知 |
