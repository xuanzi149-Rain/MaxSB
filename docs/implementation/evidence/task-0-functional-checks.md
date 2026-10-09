# 任务 0 功能验收记录（2026-10-09）

固定上游：`4aad53c4316f956ecef69e1dc5d3ab3a1e80080b`。
本地分支：`task0-local-model-baseline`。任务 0 功能验收完成；运行基线包含下述本地向量模型兼容性补丁。

## 已通过

- 用户完成管理员密码设置，并配置阿里云百炼模型 `MaxSB1`，模型标识 `qwen3.7-plus`。未读取或记录 API 密钥。
- 知识库：`任务0公开资料基线`，ID `01a11e7e-9cc4-7ec1-bc77-11ddeceb301c`。
- 测试资料见 `../fixtures/maxkb-public-baseline.txt`。修复后以 `maxkb-public-baseline-retry.txt` 导入，380 字符、1 个分段，向量化成功。
- 命中测试问题：`MaxKB 的后端和前端分别使用什么技术？`，命中测试资料，相似度 `0.730`。
- 问答应用：`任务0知识问答基线`，ID `01a11ef7-f1bc-7f13-9941-f3eb008be48a`，已绑定 MaxSB1 和测试知识库，未发布。
- 网页调试问题：`MaxKB 的后端、前端和向量数据库分别使用什么技术？`
- 实际回答：后端 Python 和 Django；前端 Vue；向量数据库 PostgreSQL 和 pgvector。引用 1 个分段，来源为测试文档。界面报告 641 tokens、9.10 秒；这是界面用量记录，未核对供应商账单，不能据此推算实际费用。
- 首次调试在配置保存完成前发送，返回模型未配置、0 tokens；保存并核对数据库模型绑定后重试成功。
- 只读工具：`task0_public_project_info`，ID `01a11efc-5f9c-7800-aeba-017b87a630a1`。网页工具调试运行成功，返回公开技术栈及 `read_only: true`；代码没有网络、文件、凭据访问。

## 本地向量模型原版故障和最小修复

原始镜像 `maxkb-baseline:4aad53c` 保留未修改源码。最初资料向量化失败：本地模型的最小 Django app 集合加载 `common.auth.authenticate` 时，间接导入未注册的 User 模型。移除该无实际认证逻辑的匿名认证类后，DRF 默认匿名用户又触发 auth 模型导入。

修复文件：`apps/maxkb/settings/base/model.py`：

```python
'DEFAULT_AUTHENTICATION_CLASSES': [],
'UNAUTHENTICATED_USER': None,
```

此设置只作用于 `SERVER_NAME=local_model` 的最小服务；Web 管理服务认证配置未修改。原类仅返回 `(None, None)`，并无凭据验证逻辑。

验证：原版 `SERVER_NAME=local_model manage.py check` 退出 1；修复后退出 0。直接请求本地 `11636` 的 `embed_documents`，HTTP 200、业务 code 200，并返回真实向量；随后网页重新导入文档向量化成功，命中测试和真实 RAG 问答通过。因此本记录属于“固定上游 + 启动兼容性补丁”，不能标为完全未修改原版的功能成功。

原始失败文档保留作为对照。当前容器已复制修复文件；仅重启容器可保留，重新创建原版镜像容器则不包含补丁。复现补丁镜像：

```sh
docker build -f docs/implementation/fixtures/Dockerfile.task0 -t maxkb-task0:local-model-fix .
```

## 第二模型与工作流验收（补充）

- 第二模型：`MaxSB2 / deepseek-v4-flash`，ID `01a11f05-0114-7e73-859e-5cc08ccb3e70`。通过上游 `models_provider.tools.get_model` 获取实例并真实调用，输入“请仅回复：任务0第二模型调用成功”，实际回复“任务0第二模型调用成功”。供应商适配器返回 input_tokens=40、output_tokens=44、total_tokens=84，其中 reasoning=37；进程退出码 0。
- 工作流：`任务0只读工具工作流`，ID `01a11efd-55aa-74c1-a219-8228e03b6e87`。链路为开始 → 自定义只读工具，使用与已创建工具相同的代码。
- 网页输入“请运行只读工具并返回公开技术栈。”，返回 Python/Django、Vue、PostgreSQL/pgvector 和 `read_only: True`。总耗时 0.16 秒，0 tokens（该流程未调用 LLM）。
- 网页执行详情确认两个节点成功：开始 0.02 秒，只读公开资料工具 0.14 秒；工具输入为 `{}`，输出为预期技术栈对象。截图：`task-0-workflow.png`。
- 上轮曲线错误源于助手准备的测试夹具：`app-edge` 的 `pointsList` 只有两个点，而上游贝塞尔曲线 `getPath` 必须读取四个点。已修正夹具脚本和该测试工作流中的四点连线；未因此修改上游前端代码。修复后网页调试与节点输出通过。
- 夹具准备脚本见 `../scripts/prepare_task0_workflow.py`，仅作用于本次专用空白工作流，拒绝覆盖已配置连线。工具库中的独立工具仍为禁用；验收工作流使用相同代码的自定义工具节点。两个测试应用均未发布，可在管理界面调试。

## 最终检查及限制

- `git diff --check`、Python 3.11 修复文件及夹具语法检查：退出码 0。
- 本地模型 `SERVER_NAME=local_model manage.py check`：退出码 0；Web `manage.py check` 最终核对同样退出 0，无系统检查问题。
- 可复现补丁镜像 `maxkb-task0:local-model-fix` 已构建成功，镜像 SHA `955d4c3fea14ca71248dda9ca4d3fbc36eeb6441fee3d677018978730eae8cb3`。
- 前端类型检查、管理端与聊天端构建已在本任务前序检查通过，之后没有修改前端源码；不重复无关构建。上游 Ruff 的 668 项告警保留，不宣称整个上游 lint 清零。
- 原版无补丁的向量化失败记录保留；后续评测应统一使用此明确标注的修复基线，不能把兼容性补丁隐藏为上游原始行为。
- 本地持久化数据目录仍为 `/private/tmp/maxkb-task0-data`，其中包含用户配置，勿提交。该位置适合当前验收；长期使用需迁移至持久目录。未推送 GitHub，未开始任务 1。
