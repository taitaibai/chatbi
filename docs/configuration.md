# 配置参考

所有配置通过项目根目录的 `.env` 文件设置，Docker Compose 启动时自动加载。

修改 `.env` 后需执行 `docker compose up -d` 重建容器（`docker compose restart` 不会重新读取 env 文件）。

---

## LLM 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_API_KEY` | —（必填） | LLM 服务的 API Key。也可通过 `OPENAI_API_KEY` 设置（兼容旧版） |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称，根据所选服务商填写 |
| `LLM_BASE_URL` | —（留空） | API 端点 URL。留空则使用 OpenAI 默认端点 |
| `LLM_TIMEOUT_SECONDS` | `60` | LLM 请求超时时间（秒） |
| `LLM_MAX_CONCURRENT` | `10` | 并发 LLM 调用上限（asyncio.Semaphore） |

### 常用 LLM 配置示例

**OpenAI**
```bash
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=
```

**DeepSeek**
```bash
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
```

**MiniMax**
```bash
LLM_API_KEY=your-minimax-key
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimaxi.com/v1
```

**本地 Ollama**
```bash
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:14b
LLM_BASE_URL=http://host.docker.internal:11434/v1
```

> 推理模型（如 DeepSeek-R1、MiniMax-M2.7）输出的 `<think>` 标签会被自动剥离，无需额外配置。

---

## 数据源配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DATASOURCE_TYPE` | `mock` | 数据源类型。当前支持 `mock`，可扩展 `clickhouse`、`mysql` 等 |
| `SEMANTIC_MODEL_PATH` | `config/semantic_model.yaml` | 语义模型配置文件路径（相对于 backend 目录） |

---

## 安全配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ALLOWED_TABLES` | （内置列表） | SQL 白名单表名，逗号分隔。支持 `schema.table` 格式，如 `dw.fact_orders`。**必须与 semantic_model.yaml 中的物理表名一致** |
| `ADMIN_TOKEN` | `change-me-in-production` | 语义模型热重载接口的认证 Token。生产环境**必须修改** |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS 允许来源，逗号分隔 |

### ALLOWED_TABLES 说明

必须包含 `semantic_model.yaml` 中所有 `tables[*].name` 字段的值：

```bash
# 默认语义模型对应的白名单（含 schema 前缀）
ALLOWED_TABLES=dw.fact_orders,dw.fact_refunds,dw.fact_user_daily,dw.dim_users,dw.fact_product_sales,dw.dim_products,dw.fact_page_views,dw.fact_channel_traffic
```

---

## 速率限制

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `RATE_LIMIT_PER_MINUTE` | `20` | 同一 `user_id` 每分钟最大请求次数。超限返回 HTTP 429 |

---

## 会话配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SESSION_TTL_SECONDS` | `1800` | 会话不活跃超时时间（秒），超时后上下文清除 |

---

## 复杂度控制

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `COMPLEXITY_THRESHOLD` | `100000000` | 预估最大扫描行数（1 亿）。超过此值的查询会被拦截 |

---

## 审计日志

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AUDIT_DB_PATH` | `data/audit.db` | SQLite 审计日志文件路径（相对于 backend 目录）。Docker 部署时挂载在 `chatbi_data` volume |

---

## 日志

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LOG_LEVEL` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## 完整 `.env.example`

```bash
# ── LLM ─────────────────────────────────────────────────────────────────
# 支持任何 OpenAI SDK 兼容服务，切换供应商只需改这三行
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=                       # 留空使用 OpenAI 默认端点

LLM_TIMEOUT_SECONDS=60
LLM_MAX_CONCURRENT=10

# ── 数据源 ───────────────────────────────────────────────────────────────
DATASOURCE_TYPE=mock
SEMANTIC_MODEL_PATH=config/semantic_model.yaml

# ── 安全 ─────────────────────────────────────────────────────────────────
ALLOWED_TABLES=dw.fact_orders,dw.fact_refunds,dw.fact_user_daily,dw.dim_users,dw.fact_product_sales,dw.dim_products,dw.fact_page_views,dw.fact_channel_traffic
ADMIN_TOKEN=change-me-in-production
ALLOWED_ORIGINS=http://localhost:5173

# ── 限流 ─────────────────────────────────────────────────────────────────
RATE_LIMIT_PER_MINUTE=20

# ── 会话 ─────────────────────────────────────────────────────────────────
SESSION_TTL_SECONDS=1800

# ── 复杂度 ───────────────────────────────────────────────────────────────
COMPLEXITY_THRESHOLD=100000000

# ── 日志 ─────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO

# ── 审计 ─────────────────────────────────────────────────────────────────
AUDIT_DB_PATH=data/audit.db
```
