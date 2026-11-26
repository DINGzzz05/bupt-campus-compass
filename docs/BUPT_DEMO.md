# 北邮校园指南面试演示

## 三分钟演示

1. 启动 [北邮完整配置](../README.md)，注册本地账号，提问「图书馆电子资源怎么在校外访问？」。展开引用并核对官网链接和复核日期。[北邮图书馆校外访问指南](https://libportal.bupt.edu.cn/a/fuwu/shangwangfuwu/)
2. 追问「那入口呢？」，点击回答下方的「请求追踪」。可以看到领域路由、风险判断、上下文装配、检索和安全审查的顺序，也能看到候选资料、模型调用状态和输入 Token。
3. 在「会话记忆」确认业务背景，随后改写、撤回。连续聊几轮使旧消息滑出窗口，再看追踪中关联的快照 ID。清空记忆后原始历史仍可回看，后续推理从清空后的消息开始装配。
4. 打开「支持请求」，填写情况并预览。点击确认后会出现队列状态和本地回执。回执对应本项目的受理记录。
5. 发送「火星有几颗卫星？」观察无证据时的处理。首 token 前后故障和租约超时的边界可用确定性故障用例演示。

## 面试讲法

> 我在现有 FastAPI 和 Vue 项目基础上做了北邮公开资料助手。一次请求由 Runtime Harness 驱动，五个专职阶段按顺序领取 Blackboard 任务，各自提交路由、风险、上下文、检索结果和审查产物。短期上下文使用 Redis 四消息滑窗，较早消息由 Qwen2.5 压缩成 brief 并按覆盖消息与修订版本存到 MySQL。检索将 BM25 与 Chroma 排名加权融合，再用关键词和领域提示重排。生成之前先验证官方来源。查询、模型调用和用户确认后的支持任务都能通过本轮 run ID 关联起来。

## 工程细节

| 主题 | 可现场核查 |
| --- | --- |
| Blackboard | 每个阶段只能在预定顺序领取任务，只有当前持有者能发布一次产物。 |
| Memory | 按会话和修订版本保存快照，Redis 缓存包含消息 ID 和版本。用户可确认、改写、撤回和清空记忆。Redis 不可用会用 SQL 重建短期窗口。 |
| Hybrid RAG | 中文 BM25、BGE-M3 向量、Chroma 持久索引、加权倒数排名融合、关键词与领域重排。官方 URL、版本、正文 SHA-256、复核日期与状态由语料维护，仅索引 ACTIVE 资料。修改 [知识库语料](../backend/app/services/bupt_knowledge.json) 后重启 API，索引随语料内容和向量模型配置变化。 |
| ModelRouter | 用同一本地模型分别处理领域、风险、摘要和回答，各阶段独立熔断，包含关闭、打开和单探针半开状态。模型首 token 前失败可回退到证据摘录，已发送首 token 后保留前缀并附中断状态。 |
| MCP 支持动作 | 用户预览后签发短期确认，确认后调用已注册的 MCP 工具。任务以会话和确认键去重，后台 worker 用租约领取，超时或失败重试，达到上限后等待人工重试。 |
| Trace | ConversationRun 关联检索、模型尝试、快照和支持动作，追踪端点只允许会话所有者读取。 |

## 复跑

使用 PowerShell，从仓库根目录执行。BM25 配置可省略第一行。HTTP 验证针对当前运行的后端，完整配置可再加上 `--require-ollama`。

```powershell
$env:BUPT_OLLAMA_ENABLED = 'true'
.venv/Scripts/python -m scripts.eval_bupt
.venv/Scripts/python -m scripts.bupt_e2e --require-redis
.venv/Scripts/python -m scripts.bupt_harness --http-base http://127.0.0.1:8000 --require-redis
curl.exe -fL -o .bupt-local/qwen2.5-tokenizer.json https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/resolve/main/tokenizer.json
.venv/Scripts/python -m scripts.eval_bupt_memory --tokenizer .bupt-local/qwen2.5-tokenizer.json --live-summary
.venv/Scripts/python -m scripts.bupt_harness --http-base http://127.0.0.1:8000 --require-redis --require-ollama --memory-tokenizer .bupt-local/qwen2.5-tokenizer.json --live-summary
```

Tokenizer 文件可从 Qwen 官方模型仓库下载。省略 `--tokenizer` 会输出以 `cl100k_base` 估算的结果。压缩对比使用相同系统指令、问题和证据，比较 3 组固定会话的完整历史和压缩上下文。检索报告用 30 条可回答题计算 Recall@4、MRR@4，并单列 6 条无证据题与本机检索 P95。Engineering Harness 在 `.bupt-local/reports/` 写入 Git SHA、工作区指纹、配置、依赖、语料集指纹和故障用例结果。[Qwen2.5 官方模型仓库](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)

MCP 工具也可由标准客户端通过 stdio 访问。用与 API 相同的数据库配置和签名密钥启动下列命令。调用 `create_support_request` 时，传入授权用户的短期签名 `confirmation` 和明确确认参数 `confirmed: true`。API 后台 worker 会处理已持久化的任务。[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

```powershell
.venv/Scripts/python -m backend.app.services.bupt_actions
```

## 简历描述

**北邮校园指南｜校园支持与个人发展 Agent**

- 基于 FastAPI、Vue 和 SQLAlchemy 实现校园公开资料助手，以请求级 Runtime Harness 编排 Blackboard 上的领域路由、风险判断、记忆装配、检索和来源审查。
- 使用 Redis 滑动窗口和 MySQL 版本化快照管理上下文，以 Qwen2.5 压缩旧消息，支持事实确认、改写、撤回和清空。
- 实现中文 BM25 与 BGE-M3 / Chroma 双路召回、加权排名融合和领域重排，返回含 URL、版本、复核时间及哈希的官方引用。通过独立熔断与 SSE 回退策略处理本地模型故障。
- 封装显式确认的 MCP 支持请求，配合幂等键、租约、退避重试和人工恢复处理持久任务，并通过运行记录关联记忆、检索、模型与动作，支持本地 HTTP 回归和 9 个故障注入用例。

2026-11-26 本地验收使用 MySQL、Redis、Ollama Qwen2.5:7b 和 BGE-M3。36 条检索样本中，30 条可回答题的 Recall@4 和 MRR@4 均为 1.000，6 条无证据题均返回空结果，纯检索 P95 为 90.68 ms。3 组固定会话的快照全部成功恢复，用 Qwen2.5 tokenizer 比较完整历史与压缩上下文，回答输入 Token 减少 30.88%。真实 HTTP 端到端验证、41 项后端定向测试和 9 个故障注入用例全部通过。
