# 北邮校园指南 · BUPT Campus Compass

面向北邮学生的校园公开资料问答 Agent：先检索官方资料，再生成可核验的回答；本地模型不稳定时降级到资料摘录；知识库回答不了时，经用户确认转为受控支持请求。

> 本项目基于 [Campus RAG Assistant](https://github.com/sandeep-jay/campus-rag-assistant) 扩展，不是北邮官方产品。回答仅依据公开可核验资料；支持请求是本地受理队列，不接入学校工单系统。

## 解决什么问题

校园信息分散在教务、图书馆、科研、就业、生活等页面，通用大模型容易编造流程和网址。这个项目把“找依据、判断风险、装配上下文、生成回答、留下追踪”做成一条受约束的链路，而不是让模型自由发挥。

## 核心能力

- **官方来源 Hybrid RAG**：中文 BM25 + BGE-M3 / Chroma 双路召回，加权融合与启发式重排；只索引 `ACTIVE` 且 `https://*.bupt.edu.cn` 的资料，回答带 URL、版本、复核时间和内容哈希。
- **请求级 Runtime Harness**：一次提问一个 `run_id`，Blackboard 五阶段按序执行：领域路由 → 风险判断 → 上下文装配 → 混合检索 → 来源审查。
- **版本化上下文**：Redis 四消息窗口 + MySQL `MemorySnapshot` 增量压缩；支持事实确认、改写、撤回、清空；Redis 断连时用 SQL 重建窗口。
- **本地模型容错**：`ModelRouter` 统一 route / risk / summary / answer 四类调用；按用途三态熔断；首 token 前失败回退官方摘录，首 token 后失败保留已输出前缀并提示重试。
- **受控支持请求**：用户预览并确认后，通过 MCP 工具创建持久化异步任务；幂等键、租约、重试、人工恢复和本地回执。
- **可追溯与可复现**：`ConversationRun` 关联检索、记忆快照、模型调用和动作；Engineering Harness 固化 Git SHA、依赖、配置、数据集与语料哈希。

## 请求链路

```mermaid
flowchart LR
  U[用户] --> V[Vue 3]
  V --> A[FastAPI / SSE]
  A --> H[RuntimeHarness]
  H --> D[domain 领域路由]
  D --> R[risk 风险判断]
  R --> M[memory 上下文]
  M --> K[retrieval 混合检索]
  K --> C[review 来源审查]
  C --> L[ModelRouter / qwen2.5:7b]
  L --> S[SSE: token / done]
  S --> T[ConversationRun Trace]
  T --> P[MCP 支持请求]
```

## 技术栈

Python · FastAPI · SQLAlchemy · MySQL · Redis · Chroma · Ollama · BM25 · Hybrid RAG · MCP · Vue 3

## 快速开始

### 最小配置（SQLite + BM25，无需 Ollama）

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.\scripts\run-bupt.ps1
```

另开一个 PowerShell 窗口启动前端：

```powershell
npm.cmd --prefix frontend-vue ci
.\scripts\run-bupt.ps1 -Frontend
```

打开 <http://127.0.0.1:5173/>，注册本地账号即可提问。

### 完整配置（MySQL + Redis + Ollama）

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements.txt -r requirements-bupt.txt
docker compose -f docker-compose.bupt.yml up -d --wait
$env:SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://bupt:bupt-local-only@127.0.0.1:3306/bupt_compass?charset=utf8mb4'
$env:BUPT_REDIS_URL = 'redis://127.0.0.1:6379/0'
ollama pull bge-m3
ollama pull qwen2.5:7b
.\scripts\run-bupt.ps1 -Ollama
```

## 验收数据

2026-11-26 本地验收使用 MySQL、Redis、Ollama `qwen2.5:7b` 和 BGE-M3：

- 36 条固定检索样本：30 条可回答题 Recall@4 100%、MRR@4 1.000；6 条无证据题均返回空结果；本机纯检索 P95 90.68 ms。
- 3 组固定会话：回答输入 Token 减少 30.88%，快照恢复 3/3。
- 9 个确定性故障注入用例 9/9 通过；后端定向回归通过。

> 以上是本机固定样本的回归结果，不是线上 SLA 或通用准确率。检索集只有 8 篇资料，规模较小。

## 目录结构

```text
backend/app/services/bupt_runtime.py   # RuntimeHarness + Blackboard 五阶段
backend/app/services/bupt_memory.py    # Redis 窗口 + MySQL 版本化快照
backend/app/services/bupt_knowledge.py # BM25 + Chroma 混合检索
backend/app/services/bupt_model.py     # ModelRouter + 三态熔断
backend/app/services/bupt_actions.py   # MCP 支持请求 + 租约 worker
backend/app/api/bupt.py                # 记忆、追踪、支持请求 API
frontend-vue/src/views/CampusRunView.vue
scripts/bupt_harness.py                # 可复现验收报告
docs/BUPT_DEMO.md                      # 演示、面试讲法与复跑命令
```

## 文档

- [面试演示与复跑](docs/BUPT_DEMO.md)
- [完整项目 README](README.full.md)
- [系统架构](docs/ARCHITECTURE.md)
- [评测说明](docs/EVALUATION.md)

## 许可与声明

- 基于 Campus RAG Assistant；保留上游 `LICENSE` 与 `NOTICE`。
- 本项目用于个人学习与作品展示，不是北邮官方系统；公开资料以来源页面为准。
- 不提交真实密钥；Compose 中的数据库密码仅用于本地开发。
