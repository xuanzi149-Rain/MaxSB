# 任务 6 模型路由实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 AI 节点实现默认关闭的双模型路由、一次受控升级和可核查的双次计量。

**Architecture:** 新增独立 model_routing 模块负责配置、规则、输出校验、执行与计量，AI 节点仅接入调用边界。复用模型管理、工作流版本、节点详情和任务 1 评测；不新增供应商接口或数据库表。

**Tech Stack:** Python 3.11、Django、LangChain、PostgreSQL 测试库、Vue 3 / Element Plus。

**Spec:** [用户已确认设计](task-6-design.md)。勘察基线 `d2087fa5a`。

## Global Constraints

- 默认关闭；只支持应用工作流顶层纯文本 AI 节点。节点绑定工具/MCP/应用/技能、多模态、结构化记忆、循环和非应用工作流在调用前拒绝。
- 复杂/未知任务选高能力模型；明确简单抽取/分类且配置结构化契约才选低成本模型。低成本最多升级一次，无第三次调用。
- 需要校验的答案完整通过后才输出；两次调用使用相同冻结消息，失败草稿不加入上下文。
- 保留失败尝试，未知用量/费用为 null，不混币种求和，不用估算或预算预留冒充实际账单。
- 原 8080、业务数据库及 8084 已部署实例不变；真实付费调用前落实两模型、价格来源和预算。
- 最小化差异，不全仓自动修复 lint；不读取冻结题答案调参，不扩大任务 2/3/5 的验收结论。

## Review Focus

1. 文档内含“简单分类”或混合意图：不得误导低成本选模（任务 1）。
2. 模型返回重复 JSON 键、NaN、空引用集合：严格契约不能被宽松解析绕过（任务 1）。
3. 供应商隐含重试、流中异常或用户取消：不能出现未计量第三次调用或失败片段泄漏（任务 2）。
4. 复制/导入后模型 ID 改变或授权撤销：不能沿用旧模型依赖绕过授权（任务 3）。
5. 恢复成功 AI 检查点和重复回调：调用数与费用不能重复计算（任务 3/4）。

## 0. 隔离执行与证据

- [ ] 按 using-git-worktrees 技能检查附属工作树及当前修改，复用合适的隔离检出或创建 `codex/task6-model-routing` 分支工作树；带入已确认设计和本计划，不覆盖其他工作。
- [ ] 读取当前 CI 和子目录约定，记录实际 SHA、Python/Node 版本与基线状态到 `docs/implementation/evidence/task-6/environment.md`。
- [ ] 新建 `docs/implementation/scripts/run_task6_tests.py`，沿用任务 5 runner 的测试库隔离/pgvector 扩展方式，固定测试库 `test_maxsb_routing_task6`。执行前确认没有同名在用库，服务库不运行迁移。

## 1. 路由配置、确定性规则与输出契约

**Files:** 新增 `apps/application/model_routing/{__init__,types,config,policy,validation}.py`；新增 `tests/model_routing/test_config.py`、`test_policy.py`、`test_validation.py`。

**Interfaces:** `parse_policy(value: dict) -> RoutingPolicy`；`select_route(question: str, policy: RoutingPolicy, *, has_history: bool, has_tool_results: bool) -> RouteDecision`；`validate_output(text: str, contract: OutputContract, evidence_ids: frozenset[str]) -> list[str]`。RouteDecision 包含 role、rule_id、rule_version、reason。错误使用稳定代码，不含原始提示词。

- [ ] 写失败测试：缺失配置为关闭；开启须有不同的 low/high UUID 与独立 params；未知字段、bool 冒充数字、越界配置拒绝。固定超时默认 60 秒/范围 1–120 秒，缓冲上限 1 MiB UTF-8（含内容与推理）；契约必需字段最多 64 个、名称最长 128 字符。
- [ ] 写规则测试：明确抽取/分类有契约选 low；无契约、未知、比较、多条件、历史依赖、工具结果、混合意图选 high；文档正文不作为规则输入。
- [ ] 写契约测试：严格 JSON 对象、拒绝重复键/非有限数/markdown 包裹，必需字段缺失失败；可选 citation_field 的值必须为字符串数组，每项属于 evidence_ids。空白名单允许空数组、拒绝任意伪造 ID；不额外声称验证事实正确性。
- [ ] 运行 `PYTHONPATH=apps python3 -m unittest discover -s tests/model_routing -v` 确认缺失行为失败；实现上述接口，重跑通过并保存红绿证据，提交该单元。

## 2. 有界执行、一次升级与流式隔离

**Files:** 新增 `apps/application/model_routing/executor.py`、`usage.py`、`tests/model_routing/test_executor.py`、`test_usage.py`；修改 `apps/application/flow/step_node/ai_chat_step_node/impl/base_chat_node.py`。

**Interfaces:** `execute_routed(messages, policy, decision, *, model_factory, evidence_ids, cancelled, trace) -> Iterator`，输出通过验证的 LangChain 消息块；trace 在调用开始前创建并原位更新，异常也可读取。`summarize_attempts(attempts: list[dict]) -> dict` 汇总已知分项并传播未知。每次 attempt 包含 UUID、模型角色/ID、起止时间、状态、错误码、用量来源。

- [ ] 先写受控模型测试：low 合法只调用一次；格式/字段/引用失败后 high 成功调用两次且消息完全一致；high 再失败明确抛错；配置/认证/权限错误不升级；受识别超时/传输错误可升级；未知异常保守失败。
- [ ] 测试流式：low 先输出坏片段再失败时客户端收不到坏片段；缓冲超限、无终止流、取消均有界结束；取消后不调用 high；直接 high 开放回答流中失败不追加第二个答案。
- [ ] 运行任务 1 的纯测试命令见红；实现迭代器、校验后释放和消息冻结。检查现有供应商重试配置，路由调用关闭内部重试；不能保证重试/取消/超时边界的适配器明确拒绝路由，不用后台线程继续请求伪装超时终止。
- [ ] 实现增量 usage 聚合与供应商末帧统计适配，不把累计 usage 再相加；异常中已知用量保留。测试任一尝试用量缺失时总量 null，分项仍可见。
- [ ] 跑纯测试通过，再写 `apps/application/tests_model_routing_runtime.py` 真实节点测试，接入独立输出 writer，避免旧 token 估算覆盖路由实际值。关闭开关时调用原 writer；运行 task6 runner 对应标签，通过后提交。

## 3. 工作流校验、模型依赖、证据与恢复

**Files:** 修改 `apps/application/flow/step_node/ai_chat_step_node/i_chat_node.py`、`flow/common.py`、`serializers/application.py`、`tool_recovery/runtime.py`（只在必要时）；新增 `apps/application/model_routing/integration.py`、`apps/application/tests_model_routing_integration.py`。

**Interfaces:** `validate_routing_workflow(workflow) -> None`；`routing_model_ids(node_data: dict) -> list[str]`；`resolve_evidence(node, policy) -> tuple[str, frozenset[str]]`。证据绑定采用显式检索节点引用，统一构造含真实证据 ID 的文本块并放入当前消息，不能只凭正文 substring 推定绑定有效。

- [ ] 写失败测试覆盖保存/发布/运行非法组合、跨工作空间/禁用/删除/无权限模型；节点本身工具调用拒绝，但上游工具文本综合走 high。
- [ ] 写测试验证两个模型均进入依赖，导入/复制映射后都更新；开启路由不要求旧默认模型有效，关闭时旧模型检查不变。核查导入/导出实际辅助函数，沿原调用链做局部修改并记录新增触达文件。
- [ ] 测试引用绑定来自真实检索结果且对应当前模型输入；坏引用、错误节点类型或缺失绑定在调用前拒绝。任务 2 去重后只使用实际保留证据。
- [ ] 运行 `python docs/implementation/scripts/run_task6_tests.py application.tests_model_routing_integration` 见红；实现校验及依赖映射，重跑通过。
- [ ] 增加任务 5 恢复集成断言：AI 经 low→high 后完成、下游 MCP 失败、恢复后模型调用仍为 2，任务 ID/attempt ID/用量不变；异常路径保存失败 trace，普通轨迹脱敏。通过后提交。

## 4. 分模型计量、价格与三组评测

**Files:** 修改 `apps/application/evaluation/{usage,child,snapshot,sanitize,metrics,compare,budget}.py`；新增 `apps/application/evaluation/routing.py`、`tests/model_routing/test_evaluation.py`；扩展 `apps/application/tests_evaluation_usage.py`；新增 `docs/implementation/evaluation/task6-protocol.json`。

**Interfaces:** `price_attempt(attempt: dict, price: dict) -> dict` 使用 Decimal 生成 priced_cost，账单值独立保留为 actual_cost；`compare_routing(groups: dict, protocol: dict) -> dict` 返回按题型指标、数据覆盖率、质量门槛及成本结论。旧评测结果缺字段兼容。

- [ ] 写失败测试：调用 ID 去重、失败调用保留、两模型价格不同仍正确合计；输入/输出/cache 定价不完整或有效期不符为未知，币种不同不可求和；预算预留不能写成 actual_cost。
- [ ] 写评测测试：三个组使用同一题集及契约才可比较；缺人工复核/费用不能判定省钱；所有失败保留在成功率和总费用分母；按题型和整体门槛均满足才允许成本优化结论。
- [ ] 跑纯测试和 `application.tests_evaluation_usage` 见红；实现按调用 ID 绑定模型的计量，节点 trace 与回调只合并、不二次相加。扩展脱敏白名单只放行明确字段，模型标识来自配置/回调匹配而非模型输出。
- [ ] 写协议配置：固定低成本、始终高能力、路由三组；总体和各题型正确率差至少 0，必需证据/引用新增回归数为 0，完整费用覆盖率为 1 且每成功任务费用严格下降。预先记录 SHA/数据集/模型版本/价格版本/评分规则及协议摘要。
- [ ] 将旧单模型预算规则保持兼容；新增显式 endpoint/model/价格/输出上限白名单，最多两次调用分别预留且不得突破总预算。增加 async HTTP 和 stream 路径预算拦截测试，未知端点 fail closed。
- [ ] 重跑通过并提交；实际模型、价格、预算尚未落实时协议标记未就绪，不发起付费评测。

## 5. 节点配置、执行详情和对照界面

**Files:** 修改 `ui/src/workflow/nodes/ai-chat-node/index.vue`、`ui/src/views/application-evaluation/index.vue`、`ui/src/api/application/evaluation.ts`；新增 `ui/src/workflow/nodes/ai-chat-node/ModelRoutingConfig.vue`、`ui/src/components/execution-detail-card/component/ModelRoutingDetails.vue`；接入现有 execution-detail-card 并更新 zh-CN/en-US/zh-Hant 对应文案。

- [ ] 实现默认关闭、两模型选择及各自参数、JSON 契约/引用绑定；开启时显示替代原模型选择，非法组合给出具体原因；说明校验期间会等待完整答案。
- [ ] 展示规则原因、升级原因、逐次调用、未知用量/费用来源；展示三组按题型指标及不可比较原因，账单费用与按价核算费用区分。
- [ ] 用真实本地接口验证配置保存/重新打开、非法组合拒绝、low 成功、升级成功、双失败和关闭回归；受控模型夹具明确标注，桌面/窄屏截图保存到 evidence/task-6/ui。
- [ ] 在 ui 目录运行 `npx --no-install eslint <本次改动的文件列表>`、`npm run type-check`、`npm run build`、`npm run build-chat`；记录退出码及已有警告，通过后提交。

## 6. 回归、真实评测与交付

**Files:** 新增 `docs/implementation/scripts/run_task6_comparison.py`、`docs/implementation/task-6.md`、`docs/implementation/evidence/task-6/`；更新 `docs/implementation/skill-application.md`、`docs/IMPLEMENTATION_TASKS.md` 的实际状态。

- [ ] 对照脚本只接受已就绪协议，输出目录已存在时拒绝覆盖，三个组每次均生成新 run_id；编写失败测试后实现，保存完整逐次记录及配置摘要。
- [ ] 跑任务 1–5 纯测试目录、`python docs/implementation/scripts/run_task6_tests.py application`，执行改动 Python 的 ruff 和 `git diff --check`；前端沿任务 5 验证结果，仅新修改后重跑相关检查。
- [ ] 核实模型/价格/预算授权后运行真实开发集；保存失败和调整历史。锁定协议后再运行冻结三组对照、收集人工评分，缺前置条件时明确记为未完成，不使用夹具冒充供应商质量结果。
- [ ] 按 requesting-code-review 完成最终独立审查，修复问题后运行相关验证；按 verification-before-completion 核对证据。报告功能、质量、费用和部署四项独立状态，保留前置任务未验收项。
- [ ] 提交已验证代码及文档；是否发布到 8084、合并或生产部署沿后续明确指令执行。

## 自审与执行交接

已检查设计覆盖、接口命名、五类风险的测试归属及计划范围；设计中的模型权限、证据来源、流式输出、失败计量、恢复、费用来源和三组对照均有任务承接。上述步骤均未执行，不代表测试通过。

推荐本会话顺序实施，最后独立审查，因为执行、计量和恢复共享同一调用轨迹，顺序修改能减少接口协调。另一选择是逐任务由子代理实现和审查。计划待用户审阅并选择执行方式。
