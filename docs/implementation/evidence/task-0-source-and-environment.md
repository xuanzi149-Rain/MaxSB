# 任务 0：源码与环境检查（2026-10-09）

## 当前结果

状态：任务 0 验收完成，含明确记录的本地向量模型兼容性补丁；源码、构建、服务启动、两个真实模型调用、知识问答及工作流工具执行均已验证。最新结果见 `task-0-functional-checks.md`。

检查开始时，工作目录只有本项目文档，不是 Git 仓库。本机常用目录没有 MaxKB 副本。随后在沙箱外通过本机代理取得完整 Git 检出，并复制至工作目录，保留原任务文档；原来的本地 README 保存在 `docs/PROJECT_OVERVIEW.md`，根目录 README 为上游版本。

- 上游远端：`https://github.com/1Panel-dev/MaxKB.git`
- 初始分支：`v2`；当前本地修复分支：`task0-local-model-baseline`
- 固定提交：`4aad53c4316f956ecef69e1dc5d3ab3a1e80080b`
- 提交时间：`2026-10-08T17:49:34+08:00`
- 检出日期：`2026-10-09`
- 当前变更：本地任务文档目录 `docs/` 与最小向量模型服务设置补丁；前端依赖与构建产物被上游 `.gitignore` 排除。

## 已执行的获取检查

| 检查 | 结果 |
| --- | --- |
| `git ls-remote https://github.com/1Panel-dev/MaxKB.git refs/heads/v2` | 失败：配置的 `127.0.0.1:7890` 代理端口无法连接 |
| 移除代理环境变量后执行同一命令 | 失败：无法解析 `github.com` |
| 本机常用目录查找 MaxKB 副本 | 未找到 |
| 在沙箱外执行相同的 `git ls-remote` | 成功，返回固定提交 SHA |
| 在沙箱外通过本机代理执行 `git clone --depth 1 --branch v2` | 成功 |

原因定位：本机 FlClash 已监听 `127.0.0.1:7890`，但沙箱内 Git 不能连接该回环地址；沙箱外 Git 可以通过同一代理访问 GitHub。直连 DNS 在沙箱内也不可用。

## 环境预检

- Docker Desktop 已启动，`docker info` 在沙箱外返回服务端版本 `27.3.1`。
- 系统 `python3` 为 Python 3.14；已发现 `python3.11` 与 `uv`。上游 `pyproject.toml` 要求 Python `~=3.11.0`。
- 系统 PATH 未提供 `node`/`npm`。前端检查使用 Codex 提供的 Node 24.19.0 与 pnpm 11.25.0；安装时启用扁平依赖布局以兼容上游按 npm 解析的间接依赖。该安装未生成锁文件，不能视为可复现依赖锁定。
- 已阅读根目录 `AGENTS.md`；它确认后端入口为 `main.py`，前端位于 `ui/`，依赖由 `uv` 管理。
- 已检查 `.github/workflows/`，并记录上游边界于 `task-0-upstream-boundary.md`；目前未更改上游工作流。
- 活动代理变为 Clash Verge 的 `127.0.0.1:7897`，而继承的环境变量仍指向 `7890`。沙箱外临时覆盖代理地址后，已拉取上游 Docker 基础镜像与 `node:24-alpine`。
- `python3.11 -m compileall -q apps main.py`：退出码 0，语法检查通过。
- `uvx ruff@0.15.12 check apps main.py`：退出码 1，上游原版存在 668 项告警；未自动修复，未把它们归为本项目新增问题。
- `vue-tsc --build`：退出码 0；管理端 `vite build`：退出码 0；聊天端 `vite build --mode chat`：退出码 0。首次管理端构建因 Node 默认约 2 GB 堆内存不足而退出 134；按上游 Dockerfile 指定的 4096 MB 上限重试通过。构建报告了上游 `eval` 和大包体积警告。
- 从固定 Git 提交的源码与本地前端构建产物，按上游 `installer/Dockerfile` 构建 `maxkb-baseline:4aad53c`：退出码 0。构建上下文位于 `/private/tmp/maxkb-task0-build-context`，排除了本机 `node_modules` 和本项目任务文档，未修改上游源码。Dockerfile 报两条基础镜像默认密码的静态警告。
- 启动容器 `maxkb-task0`，仅将 8080 端口绑定到 `127.0.0.1`，数据卷在 `/private/tmp/maxkb-task0-data`。日志显示 PostgreSQL 与 Redis 启动、数据库迁移完成、Celery、Gunicorn Web 和本地模型服务启动。`pg_isready -h 127.0.0.1` 返回接受连接；用容器自带 `/opt/py3/bin/python` 执行 `apps/manage.py check` 退出码 0；`curl --noproxy '*' http://127.0.0.1:8080/admin/` 返回 HTTP 200。
- 首次使用上游默认管理员凭据登录本地实例后，界面立即弹出“修改密码”对话框。按浏览器交互要求，密码设置由用户本人完成；未输入新密码，也未将凭据写入仓库。管理首页显示 1 个向量模型、0 个大语言模型、0 个知识库和 0 个工具。
- 后续已使用用户配置的 `qwen3.7-plus` 完成真实知识问答与引用验证；详情及尚未通过的工作流验收见 `task-0-functional-checks.md`。

## 当前检查点

用户已配置两个问答模型。知识问答、第二模型调用及工作流工具节点轨迹均已验证，详见功能验收记录。当前保留本地分支及未提交变更，尚未开始任务 1。
