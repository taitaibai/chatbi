# ChatBI 部署与运维指南

## 目录

1. [环境要求](#环境要求)
2. [本地开发启动](#本地开发启动)
3. [Docker Compose 一键部署](#docker-compose-一键部署)
4. [环境变量说明](#环境变量说明)
5. [语义模型维护指南](#语义模型维护指南)
6. [验收测试运行](#验收测试运行)
7. [性能压测](#性能压测)
8. [常见问题](#常见问题)

---

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.11+ | 后端运行时 |
| Node.js | 18+ | 前端构建 |
| Docker | 24+ | 容器化部署 |
| Docker Compose | 2.x | 编排服务 |

---

## 本地开发启动

### 1. 克隆仓库并配置环境变量

```bash
cd chatbi
cp .env.example .env   # 如不存在则手动创建
```

最小化 `.env` 配置（详见[环境变量说明](#环境变量说明)）：

```env
MINIMAX_API_KEY=your-minimax-api-key
LLM_MODEL=MiniMax-M2.5
LLM_BASE_URL=https://api.minimaxi.com/v1
DATASOURCE_TYPE=mock
```

### 2. 启动后端

```bash
cd backend

# 创建并激活虚拟环境（首次）
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate.bat     # Windows

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器（支持热重载）
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- API 服务：`http://localhost:8000`
- Swagger 文档：`http://localhost:8000/docs`
- ReDoc 文档：`http://localhost:8000/redoc`
- 健康检查：`http://localhost:8000/health`

### 3. 启动前端

```bash
cd frontend

# 安装依赖（首次）
npm install

# 启动开发服务器
npm run dev
```

前端地址：`http://localhost:5173`

---

## Docker Compose 一键部署

```bash
# 在项目根目录
cp .env.example .env
# 编辑 .env，填入 MiniMax API Key

docker compose up --build -d
```

访问地址：
- 前端：`http://localhost:5173`
- 后端 API：`http://localhost:8000`

停止服务：

```bash
docker compose down
```

查看日志：

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

---

## 环境变量说明

在项目根目录创建 `.env` 文件，以下为完整配置说明：

### LLM 配置

| 变量名 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `OPENAI_API_KEY` | _(空)_ | 否 | OpenAI 兼容的 API Key 入口；与 `MINIMAX_API_KEY`、`LLM_API_KEY` 任选其一 |
| `MINIMAX_API_KEY` | _(空)_ | 否 | MiniMax API Key；与 `OPENAI_API_KEY`、`LLM_API_KEY` 任选其一 |
| `LLM_API_KEY` | _(空)_ | 否 | 通用 LLM API Key 别名；与 `OPENAI_API_KEY`、`MINIMAX_API_KEY` 任选其一 |
| `LLM_MODEL` | `MiniMax-M2.5` | 否 | 默认 LLM 模型；SQL 生成、NLU、结果解读均跟随该配置 |
| `LLM_BASE_URL` | `https://api.minimaxi.com/v1` | 否 | OpenAI 兼容接口地址，默认使用 MiniMax |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | 否 | 支持 Azure OpenAI 或国内兼容接口 |
| `LLM_TIMEOUT_SECONDS` | `60` | 否 | LLM 请求超时时间（秒） |
| `LLM_MAX_CONCURRENT` | `10` | 否 | 同时进行的 LLM 调用上限（Semaphore 控制） |

> *`DATASOURCE_TYPE=mock` 时，API Key 可以留空（仅影响解读服务）。

### 数据源配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DATASOURCE_TYPE` | `mock` | 数据源类型：`mock` / `clickhouse` / `mysql` |
| `SEMANTIC_MODEL_PATH` | `backend/config/semantic_model.yaml` | 语义模型 YAML 文件路径 |

### 系统配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `AUDIT_DB_PATH` | `backend/data/audit.db` | 审计日志 SQLite 数据库路径 |
| `LOG_LEVEL` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | 允许跨域访问的来源，逗号分隔 |
| `ALLOWED_TABLES` | _(见下文)_ | SQL 白名单表名，逗号分隔 |
| `COMPLEXITY_THRESHOLD` | `100000000` | 查询复杂度上限（预估扫描行数） |
| `SESSION_TTL_SECONDS` | `1800` | 会话不活跃超时时间（秒） |

### 安全配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ADMIN_TOKEN` | `change-me-in-production` | 管理接口鉴权 Token，**生产环境必须修改** |
| `RATE_LIMIT_PER_MINUTE` | `20` | 同一 user_id 每分钟最大请求数 |

### 示例 `.env` 文件

```env
# LLM
MINIMAX_API_KEY=your-minimax-api-key
LLM_MODEL=MiniMax-M2.5
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_MAX_CONCURRENT=10

# 数据源
DATASOURCE_TYPE=mock
SEMANTIC_MODEL_PATH=backend/config/semantic_model.yaml

# 系统
LOG_LEVEL=INFO
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
SESSION_TTL_SECONDS=1800

# 安全
ADMIN_TOKEN=your-strong-admin-token-here
RATE_LIMIT_PER_MINUTE=20
```

---

## 语义模型维护指南

语义模型定义在 `backend/config/semantic_model.yaml`，采用 YAML 格式。
**修改配置后无需重启服务**，调用管理接口即可热重载。

### 文件结构

```yaml
version: "1.0"
domains:
  - id: sales           # 业务域 ID（唯一）
    name: 销售域
    description: 订单、GMV、退款相关指标
    tables:
      - id: fact_orders
        name: fact_orders
        description: 订单事实表
        time_field: order_date    # 时间分区字段
        dimensions:
          - id: channel
            name: 渠道
            aliases: ["销售渠道", "购买渠道"]
            field: channel
    metrics:
      - id: gmv
        domain: sales
        name: GMV
        aliases: ["成交金额", "销售额", "交易额"]
        expression: "SUM(amount)"
        base_table: fact_orders
        filters:
          - "status = 'paid'"
        format: currency
        description: "已支付订单的总成交金额"
```

### 添加新指标

1. 在对应 `domain` 的 `metrics` 列表中添加条目：

```yaml
- id: conversion_rate
  domain: sales
  name: 转化率
  aliases: ["购买转化率", "CVR"]
  expression: "COUNT(DISTINCT CASE WHEN status='paid' THEN user_id END) * 1.0 / COUNT(DISTINCT user_id)"
  base_table: fact_orders
  format: number
  description: "下单用户中完成支付的比例"
```

2. 热重载语义模型（无需重启）：

```bash
curl -X POST http://localhost:8000/api/v1/semantic/reload \
  -H "X-Admin-Token: your-admin-token"
```

3. 验证新指标已加载：

```bash
curl http://localhost:8000/api/v1/semantic/metrics
```

### 添加新维度

在对应表的 `dimensions` 列表中添加：

```yaml
- id: province
  name: 省份
  aliases: ["省", "所在省份"]
  field: province
```

### 添加跨表指标（需 JOIN）

```yaml
- id: refund_rate
  domain: sales
  name: 退款率
  expression: "COUNT(DISTINCT r.order_id) * 1.0 / COUNT(DISTINCT o.order_id)"
  base_table: fact_orders
  joins:
    - join_type: left
      table: fact_refunds
      alias: r
      on: "o.order_id = r.order_id"
  description: "退款订单数占总订单数的比例"
```

### 语义模型热重载 API

```bash
# 热重载（需 Admin Token）
POST /api/v1/semantic/reload
Header: X-Admin-Token: <admin_token>

# 查看当前可查询指标
GET /api/v1/semantic/metrics
```

---

## 验收测试运行

```bash
# 在项目根目录
cd /path/to/chatbi

# 安装后端依赖（若未安装）
cd backend && pip install -r requirements.txt && cd ..

# 运行所有验收测试（AC-01 ~ AC-08）
python -m pytest tests/e2e/test_acceptance.py -v

# 运行单个验收标准
python -m pytest tests/e2e/test_acceptance.py::TestAC01BasicQuery -v
python -m pytest tests/e2e/test_acceptance.py::TestAC08LLMDataSecurity -v

# 运行后端所有单元测试
python -m pytest backend/tests/ -v
```

---

## 性能压测

性能压测需要先启动后端服务并配置真实的 API Key。

```bash
# 安装 Locust
pip install locust

# 运行压测（50 并发，120 秒）
locust -f tests/perf/locustfile.py \
       --host http://localhost:8000 \
       --users 50 \
       --spawn-rate 5 \
       --run-time 120s \
       --headless \
       --html tests/perf/report.html

# 或交互式 Web UI
locust -f tests/perf/locustfile.py --host http://localhost:8000
# 访问 http://localhost:8089
```

**验收指标**：50 并发下，普通查询（`/api/v1/chat [standard]`）P95 响应时间 ≤ 8000ms。

**性能调优建议**：
- 调整 `LLM_MAX_CONCURRENT`（默认 10）控制 LLM 并发数
- LLM 并发超限时请求会排队而非报错，建议根据 API Key 配额设置
- 启用 `RATE_LIMIT_PER_MINUTE` 防止单用户过载（默认每分钟 20 次）

---

## 常见问题

### Q: 启动时报 `openai_api_key is empty`？

确认 `.env` 中已设置 `MINIMAX_API_KEY`、`OPENAI_API_KEY` 或 `LLM_API_KEY` 之一，或将 `DATASOURCE_TYPE` 设为 `mock` 跳过 API Key 校验。

### Q: 前端显示 "AI 分析服务暂时不可用"？

这是 LLM 降级提示，说明 API Key 缺失或 LLM 服务不可达。请检查：
1. `MINIMAX_API_KEY` / `OPENAI_API_KEY` / `LLM_API_KEY` 是否正确
2. 网络是否可访问 `api.openai.com`（或自定义 `LLM_BASE_URL`）
3. API Key 是否有足够额度

### Q: 如何切换到真实数据库？

1. 实现 `adapters.base.DataSourceAdapter` 抽象基类
2. 在 `adapters/registry.py` 中注册新适配器
3. 设置 `DATASOURCE_TYPE=clickhouse`（或对应类型）
4. **上层代码无需任何修改**

### Q: 验收测试失败 `ModuleNotFoundError`？

确保在项目根目录运行测试，且已将 `backend/` 目录添加到 Python 路径：

```bash
cd /path/to/chatbi
PYTHONPATH=backend python -m pytest tests/e2e/test_acceptance.py -v
```

### Q: 如何查看审计日志？

```bash
# 使用 sqlite3 查看
sqlite3 backend/data/audit.db "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 20;"
```
