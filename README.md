# ChatBI

**用自然语言提问，直接得到数据洞察。**

ChatBI 是一个基于大语言模型的数据分析对话系统。用户输入业务问题（例如"上周各渠道 GMV 对比"），系统自动完成意图解析 → SQL 生成 → 查询执行 → 可视化 → 流式文字解读，全程以 SSE 流式推送到前端，逐步呈现分析过程。

---

## 功能特点

- **自然语言查询**：输入中文业务问题，自动识别指标、维度、时间范围和过滤条件
- **多轮对话**：支持追问和上下文继承（"那按城市再拆一下？"）
- **全链路流式**：意图摘要、SQL、结果表、图表、文字解读逐段推送，无需等待全部完成
- **语义层驱动**：通过 YAML 定义业务指标和维度，与物理表解耦，可配置不修改代码
- **多 LLM 支持**：兼容任何 OpenAI SDK 兼容的服务（OpenAI、DeepSeek、MiniMax、本地 Ollama 等）
- **SQL 安全防护**：AST 级别检查，防止注入、限制表访问白名单、禁止危险操作
- **审计日志**：全量请求异步写入 SQLite，含意图、SQL、延迟、token 消耗
- **Docker 一键启动**：前后端均容器化，`docker compose up` 即可运行

## 技术栈

| 层 | 技术 |
|---|---|
| **前端** | React 18 · TypeScript · Vite · ECharts |
| **后端** | Python 3.11 · FastAPI · Pydantic v2 · asyncio |
| **LLM** | OpenAI SDK（兼容多提供商）· Jinja2 提示词模板 |
| **SQL 解析** | sqlglot |
| **存储** | SQLite（审计日志）· 内存（会话）|
| **部署** | Docker Compose · Nginx（前端） |

## 系统架构

```
用户
 │  自然语言问题
 ▼
┌─────────────────────────────────────────────────────┐
│  前端 (React + TypeScript)                           │
│                                                     │
│  ChatWindow → useSSEChat → streamChat(fetch+SSE)    │
└────────────────────────┬────────────────────────────┘
                         │  POST /api/v1/chat (SSE)
                         ▼
┌─────────────────────────────────────────────────────┐
│  后端查询管道 (FastAPI + asyncio)                    │
│                                                     │
│  ① NLU 意图解析   ←── LLM (JSON mode)              │
│  ② 语义映射       ←── semantic_model.yaml           │
│  ③ SQL 生成       ←── LLM + 确定性编译器            │
│  ④ SQL 安全检查   ←── sqlglot AST                   │
│  ⑤ 复杂度评估     ←── 规则引擎                      │
│  ⑥ 查询执行       ←── DataSourceAdapter             │
│  ⑦ 可视化推荐     ←── 规则引擎                      │
│  ⑧ 结果解读       ←── LLM (streaming)               │
│                                                     │
│  SSE 流式推送每步结果 ↑                              │
└─────────────────────────────────────────────────────┘
```

## 快速开始

**前置条件**：Docker、Docker Compose

```bash
# 1. 克隆项目
git clone https://github.com/your-username/chatbi.git
cd chatbi

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY、LLM_MODEL、LLM_BASE_URL

# 3. 启动
docker compose up -d

# 4. 访问
open http://localhost:5173
```

可以提问的示例：
- 上周各渠道 GMV 对比
- 最近 30 天新增用户趋势
- 各品类退款率排名
- 今天的 DAU 是多少

详细安装步骤见 [快速开始文档](docs/getting-started.md)。

## 目录结构

```
chatbi/
├── backend/
│   ├── adapters/          # 数据源适配器（Mock / ClickHouse / MySQL 等）
│   ├── api/v1/            # FastAPI 路由（chat、semantic）
│   ├── config/            # 配置、语义模型 YAML
│   ├── llm/               # LLM 客户端、Jinja2 提示词模板
│   ├── models/            # Pydantic 数据模型
│   ├── services/          # 核心服务（NLU、语义映射、SQL 生成、安全、Pipeline）
│   ├── session/           # 会话管理
│   ├── observability/     # 审计日志
│   └── tests/             # 单元测试（9 个模块）
├── frontend/
│   └── src/
│       ├── api/           # SSE 通信层
│       ├── components/    # React 组件
│       ├── hooks/         # useSSEChat（状态机）
│       └── types/         # TypeScript 类型定义
├── tests/
│   ├── e2e/               # 端到端验收测试
│   └── perf/              # Locust 性能测试
├── docs/                  # 项目文档
├── docker-compose.yml
└── .env.example
```

## 文档

| 文档 | 说明 |
|------|------|
| [快速开始](docs/getting-started.md) | 环境要求、安装、配置、运行 |
| [系统架构](docs/architecture.md) | 技术设计、各模块说明、数据流 |
| [配置参考](docs/configuration.md) | 所有环境变量说明 |
| [API 文档](docs/api-reference.md) | 接口规范、SSE 事件格式 |

## 接入真实数据源

当前默认使用内置 Mock 数据（4 个业务域）。接入真实数据库只需：

1. 实现 `DataSourceAdapter` 接口（`backend/adapters/base.py`）
2. 修改 `semantic_model.yaml` 配置真实表名和字段
3. 更新 `.env` 中的 `DATASOURCE_TYPE` 和 `ALLOWED_TABLES`

## 切换 LLM 提供商

修改 `.env` 三行即可，代码无需改动：

```bash
# OpenAI
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o
LLM_BASE_URL=          # 留空使用默认端点

# DeepSeek
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1

# 本地 Ollama
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:14b
LLM_BASE_URL=http://localhost:11434/v1
```
