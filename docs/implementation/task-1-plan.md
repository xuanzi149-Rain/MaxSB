# 任务 1 实施计划：Agent 评测与效果迭代

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 建议在当前会话顺序实施；执行方式待用户审阅确认。

**Goal:** 建立能解释原版 Agent 成功与失败、并支持后续同题对照的评测基线。

**Architecture:** 在现有 application 应用内新增隔离的评测模块，用 Celery 调用既有聊天引擎，逐题持久化结果。先实现与模型无关的题集、指标和判分，再接运行引擎及报告页。

**Tech Stack:** Python 3.11、Django、PostgreSQL、Celery、Vue 3、TypeScript；纯函数测试使用标准库 unittest，数据库与权限测试使用 Django TestCase。

**Spec:** [任务 1 设计](task-1-design.md)，验收范围以 [任务总览](../IMPLEMENTATION_TASKS.md) 为准。

## Global Constraints

- 基线是固定上游 SHA `4aad53c4316f956ecef69e1dc5d3ab3a1e80080b` 加任务 0 兼容性补丁；不得称为完全未修改原版。
- 保留当前 AGENTS.md、model.py 与 docs 的既有改动；实现前准备隔离工作区并带入必要基线文件，不自动提交无关改动。
- 开发集 20 题，冻结集 80 题；两次开发集和一次冻结集真实运行，冻结集不用于调参。
- 缺失用量和费用为 null；估算费用与实际费用分开；人工复核不由模型自评分替代。
- 不实现检索去重、动态检索、会话记忆、工具恢复或模型路由策略。
- 所有快照、异常、报告与导出不得暴露密钥或敏感工具参数。

## Review Focus

1. SSE 在中文 UTF-8 字符中间分块、多个帧合并、缺少结束帧：不得拼坏答案或误判成功，由步骤 2 测试。
2. 已检索但未引用、引用 ID 存在但不支持主张：召回与引用准确率分开，由步骤 1、2、5 测试。
3. 模型失败却已有消耗、同一批混合币种、零个成功题：不得低估每成功任务费用，由步骤 2 测试。
4. Celery 重复投递、worker 中断、执行中配置变更：不得重复收费或把不同配置合并成一个基线，由步骤 3 测试。
5. 题集题目增删或重排、未复核、运行间证据映射变化：按 case_id 比较，标记不可比与复核覆盖率，由步骤 4、5 测试。

## 1. 题集与评测协议

**Files:** 新增 `apps/application/evaluation/{__init__,dataset}.py`、`tests/evaluation/test_dataset.py`；新增 `docs/implementation/evaluation/{protocol.md,corpus.json,dev-v1.json,frozen-v1.json,manifest.json}`。

**Interfaces:** `validate_dataset(dataset: dict, corpus: dict) -> None`（不合法抛 ValueError）；`dataset_digest(dataset: dict) -> str`（规范 JSON 的 SHA256）。

- [ ] 写失败测试：重复 case_id、未知 evidence_id、空 turns、缺失事实/判分规则被拒绝；20/80 数量正确；冻结 manifest 哈希变化被检测。
- [ ] 运行 `PYTHONPATH=apps python3.11 -m unittest discover -s tests/evaluation -p 'test_dataset.py' -v`，确认测试因缺少实现失败。
- [ ] 实现 schema 校验和哈希；逐题写事实、证据与错误判定，资料记录来源及哈希。外部事实核对原始资料，自编资料标明合成夹具。
- [ ] 固定场景配额：开发集为直答 3、多证据 3、重复 2、无资料 2、长对话 3、工具成功 2、工具超时 1、冲突 2、路由适用题 2；冻结集分别为 12、12、8、8、12、8、4、8、8。
- [ ] 协议区分答案错误、证据缺失、引用不支持、工具失败、上下文丢失、基础设施错误；每题保存主原因与可选次原因，不把“未知”自动判为模型失败。
- [ ] 审核事实和评分规则后生成冻结哈希；在冻结前不声称 80 题已封存。复跑测试通过后仅提交本步骤文件。

## 2. 流式聚合、计量与评分

**Files:** 新增 `apps/application/evaluation/{stream,metrics,scoring,sanitize}.py`；新增 `tests/evaluation/test_{stream,metrics,scoring,sanitize}.py`。

**Interfaces:** `aggregate_stream(chunks: Iterable[bytes | str]) -> dict`；`score_case(case: dict, result: dict) -> dict`；`summarize(results: list[dict]) -> dict`；`sanitize_result(result: dict) -> dict`。返回 JSON 可序列化对象，未知数值为 None。

- [ ] 写失败测试：UTF-8 分块、CRLF、合并帧、累计 usage 不重复加和、缺结束帧、错误帧、只有上游默认零时计量未知；真实无模型调用为零。
- [ ] 写失败测试：召回 1/2 为 0.5；无必需证据为不适用；未人工复核不能生成最终正确率；20 个耗时 1—20 的 P95 为 19。
- [ ] 写失败测试：成功花费 2、失败花费 1，每成功任务费用为 3；任一费用缺失、混币或成功数为零时为 None；输入/输出 token 分别显示计量覆盖率。
- [ ] 写失败测试：嵌套凭据、异常中的认证信息及非白名单工具参数不进入结果；检索到的 evidence_id 不自动成为有效引用。
- [ ] 运行 `PYTHONPATH=apps python3.11 -m unittest discover -s tests/evaluation -v` 确认失败，然后实现上述接口并复跑通过；记录并提交此步骤。

## 3. 持久化与批量运行

**Files:** 新增 `apps/application/models/evaluation.py`、`apps/application/migrations/0016_evaluation.py`、`apps/application/evaluation/{service,adapter,snapshot}.py`、`apps/application/tasks.py`、`apps/application/tests_evaluation_runner.py`；修改 `apps/application/models/__init__.py`。

**Interfaces:** `create_run(workspace_id: str, application_id: str, user_id: str, dataset: dict) -> EvaluationRun`；`execute_run(run_id: str) -> None`；`execute_case(case: dict, snapshot: dict) -> dict`。模型为 EvaluationRun 和 EvaluationCaseResult，后者唯一键为 (run_id, case_id)。

- [ ] 写数据库失败测试：全批成功、单题异常后继续、两次创建生成不同 run_id、重复投递不重复调用 adapter、多轮题共享题内会话而跨题隔离。
- [ ] 写失败测试：执行前/题间依赖哈希改变标记 configuration_drift；worker 中断标记 interrupted；消息投递失败留下可解释状态；事务回滚不投递任务。
- [ ] 在独立测试数据库执行 `python apps/manage.py test application.tests_evaluation_runner --noinput` 确认失败，不对现有业务数据库执行破坏性测试。
- [ ] 实现迁移、事务提交后投递与原子领取。通过现有 ChatSerializers 引擎执行，评测适配器取得完整流及最终缓存/记录；不得只消费流而遗漏节点详情。
- [ ] 固定应用配置并核验外部依赖；受控工具仅用只读夹具。设置明确单题超时，超时不自动重放。逐题保存答案、证据、用量来源、轨迹、错误与时间。
- [ ] 测试通过，执行 `python apps/manage.py makemigrations --check --dry-run` 和 `python apps/manage.py check`，确认迁移与模型一致后提交此步骤。

## 4. 管理 API 与对照逻辑

**Files:** 新增 `apps/application/{views,serializers}/evaluation.py`、`apps/application/evaluation/compare.py`、`apps/application/tests_evaluation_api.py`；修改 `apps/application/urls.py`。

**Interfaces:** 管理端前缀 `workspace/{workspace_id}/application/{application_id}/evaluation`；POST/GET `/runs`；GET `/runs/{run_id}`；GET `/runs/{run_id}/cases/{case_id}`；PUT `/runs/{run_id}/cases/{case_id}/review`；GET `/compare?left={run_id}&right={run_id}`。`compare_runs(left: dict, right: dict) -> dict` 按 case_id 联结结果。

- [ ] 写失败测试：未登录、只读用户创建/评分、跨 workspace/application 查询、比较另一侧越权均拒绝；未结束运行拒绝比较。
- [ ] 写失败测试：case 顺序改变不影响配对，增删题显示 unmatched，数据集哈希或环境配置不一致显示 comparability reasons；评分记录服务器当前用户和时间，保留修改历史。
- [ ] 运行 `python apps/manage.py test application.tests_evaluation_api --noinput` 确认失败，再实现沿用 TokenAuth/has_permissions 的接口以及独立归属检查。
- [ ] 运行 runner 与 API 测试全部通过，核查响应脱敏与分页，提交此步骤。

## 5. 面向分析的报告页

**Files:** 新增 `ui/src/api/application/evaluation.ts`、`ui/src/views/application-evaluation/index.vue`；修改 `ui/src/router/modules/application-detail.ts` 和 `ui/src/locales/lang/{zh-CN,en-US,zh-Hant}/index.ts`。

**Interfaces:** 页面只消费步骤 4 的 API；展示运行元数据、指标覆盖率、逐题差异、人工复核与失败轨迹。

- [ ] 先用 API 固定夹具定义浏览器验收：已完成/运行中、部分失败、所有计量未知、待复核、不可比、只读权限六类状态。
- [ ] 实现运行选择与创建、状态进度、两个运行对照、按场景/失败原因筛选和题目详情；“规则通过”与“人工判为正确”使用不同标签。
- [ ] 人工评分要求正确性、引用支持判断及失败原因；由后端记录真实复核人，不能默认使用 AI 身份代填。
- [ ] 执行 `npm run type-check`、`npm run build`；仅对改动文件运行不带 --fix 的 ESLint。若本机没有 npm，使用任务 0 已验证的运行时并记录实际等价命令。
- [ ] 浏览器验证上述六种状态，保存不含敏感信息的截图；提交此步骤。

## 6. 真实基线与迭代报告

**Files:** 新增 `docs/implementation/scripts/run_task1_baseline.py`、`docs/implementation/evidence/task-1-evaluation.md`；逐题脱敏原始结果保存到 `docs/implementation/evidence/task-1/`。

**Interfaces:** 脚本指定 dataset_version、应用配置和输出目录，通过同一个评测服务创建运行；失败不得覆盖已有文件或重放冻结集。运行结果含真实 run_id、UTC 时间、源码/差异哈希和模型身份。

- [ ] 完成无费用集成检查后，核对已配置模型、运行预算和服务状态；不输出模型凭据。
- [ ] 固定知识库快照、提示词、模型参数和受控工具映射，运行两次 20 题开发集。报告答案变化、判分变化、证据变化及耗时波动；两次运行不足以证明统计显著性。
- [ ] 在运行冻结集前封存 80 题及规则哈希；只创建一次原版冻结集基线。基础设施中断保存失败证据，不静默补跑并冒充首次结果。
- [ ] 输出人工复核清单；尚未复核时交付待复核报告，不宣称最终正确率。无账单数据则实际费用未知，费用估算单列且带来源。
- [ ] 按题型和失败原因提出任务 2—6 的可验证假设，例如“重复证据提高输入 token”；不得提前宣称优化有效。
- [ ] 最终运行全部新增行为测试、相关回归、前端检查和 `git diff --check`；证据表逐项记录命令/退出码/限制，核对任务 1 全部验收项后提交本步骤。

## 审阅与执行

建议由当前会话顺序实施，各步骤完成后检查对应证据。这样能让题集、判分与运行适配器保持同一口径；当前不启动子代理。

计划自检：覆盖原任务的题集、批量服务、API、报告、两次开发集与一次冻结集；五项 Review Focus 均有测试归属。待人工决策仅为实施计划审阅及执行方式；真实费用预算和人工评分在相应执行阶段落实，不用其阻碍本地实现。
