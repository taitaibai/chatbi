# API 文档

后端基础 URL：`http://localhost:8000`

交互式 API 文档（Swagger UI）：`http://localhost:8000/docs`

---

## POST /api/v1/chat

核心对话接口。接受自然语言问题，返回 `text/event-stream` 格式的 SSE 流，按分析进度逐步推送各阶段结果。

### 请求

**Content-Type**: `application/json`

```json
{
  "query": "上周各渠道 GMV 对比",
  "session_id": "session-a1b2c3d4",
  "user_id": "user-x1y2z3",
  "options": {
    "show_intent": true,
    "show_sql": true
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 用户自然语言问题 |
| `session_id` | string | 是 | 会话 ID，用于多轮对话上下文。同一对话保持一致 |
| `user_id` | string | 是 | 用户标识，用于速率限制和审计日志（存储哈希值） |
| `options.show_intent` | boolean | 否 | 是否推送意图解析结果（默认 `true`） |
| `options.show_sql` | boolean | 否 | 是否推送生成的 SQL（默认 `true`） |

### 响应

**Content-Type**: `text/event-stream`

响应为标准 SSE 格式，每个事件由 `event:` 和 `data:` 两行组成，以空行分隔：

```
event: <event_type>
data: <json_payload>

```

#### 事件类型

**`intent_summary`** — 意图解析结果（当 `show_intent=true` 时）

```json
{
  "metrics": ["GMV"],
  "dimensions": ["渠道"],
  "time_range": {
    "type": "last_week",
    "start": "2025-03-31",
    "end": "2025-04-06"
  },
  "filters": [],
  "clarification_needed": false,
  "clarification_question": null,
  "clarification_options": []
}
```

**`sql`** — 生成的 SQL 语句（当 `show_sql=true` 时）

```json
{
  "sql": "SELECT channel, SUM(amount) AS gmv\nFROM dw.fact_orders\nWHERE status = 'paid' AND order_date BETWEEN '2025-03-31' AND '2025-04-06'\nGROUP BY channel"
}
```

**`table_data`** — 查询结果数据

```json
{
  "columns": [
    { "name": "channel", "type": "string" },
    { "name": "gmv", "type": "number", "format": "currency" }
  ],
  "rows": [
    ["App", 258000],
    ["Web", 187500],
    ["H5", 96500],
    ["小程序", 142300]
  ],
  "total_rows": 4,
  "execution_ms": 12
}
```

**`chart_spec`** — 图表规格（ECharts option）

```json
{
  "type": "bar",
  "echarts_option": {
    "xAxis": { "type": "category", "data": ["App", "Web", "H5", "小程序"] },
    "yAxis": { "type": "value" },
    "series": [{ "type": "bar", "data": [258000, 187500, 96500, 142300] }]
  }
}
```

`type` 可选值：`bar` / `line` / `pie` / `card` / `table`

**`interpretation`** — 流式文字解读（逐 token 推送）

```json
{ "token": "App 渠道", "done": false }
{ "token": " 成交额最高，达 25.8 万元", "done": false }
{ "token": "", "done": true }
```

每个 token 追加到上一个 token 之后，`done: true` 表示解读完毕。

**`error`** — 错误信息

```json
{
  "code": "clarification_needed",
  "message": "请告诉我您想查看哪些指标？例如：GMV、订单量、用户数等。"
}
```

| `code` | 含义 |
|--------|------|
| `clarification_needed` | NLU 无法理解，需要用户补充信息 |
| `semantic_not_found` | 指标或维度在语义模型中不存在 |
| `sql_unsafe` | 生成的 SQL 未通过安全检查 |
| `complexity_blocked` | 查询复杂度超过阈值 |
| `adapter_error` | 数据源执行失败 |
| `llm_unavailable` | LLM 服务不可用（API Key 错误、网络超时等） |
| `unexpected_error` | 未预期的服务端错误 |

**`done`** — 流结束标志（无论成功还是错误均会推送）

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "latency_ms": 1234,
  "token_usage": {
    "prompt": 450,
    "completion": 120
  }
}
```

错误情况下 `request_id` 为 `null`，`latency_ms` 和 `token_usage` 可能为 `null`。

#### 完整事件流示例

```
event: intent_summary
data: {"metrics":["GMV"],"dimensions":["渠道"],"time_range":{"type":"last_week","start":"2025-03-31","end":"2025-04-06"},"filters":[],"clarification_needed":false,"clarification_question":null,"clarification_options":[]}

event: sql
data: {"sql":"SELECT channel, SUM(amount) AS gmv FROM dw.fact_orders WHERE status = 'paid' AND order_date BETWEEN '2025-03-31' AND '2025-04-06' GROUP BY channel"}

event: table_data
data: {"columns":[{"name":"channel","type":"string"},{"name":"gmv","type":"number","format":"currency"}],"rows":[["App",258000],["Web",187500],["H5",96500],["小程序",142300]],"total_rows":4,"execution_ms":12}

event: chart_spec
data: {"type":"bar","echarts_option":{...}}

event: interpretation
data: {"token":"App 渠道成交额最高","done":false}

event: interpretation
data: {"token":"，达 25.8 万元，","done":false}

event: interpretation
data: {"token":"","done":true}

event: done
data: {"request_id":"550e8400-...","latency_ms":1842,"token_usage":{"prompt":520,"completion":98}}

```

### 错误响应（HTTP 层）

| 状态码 | 场景 |
|--------|------|
| `400` | 请求体缺少 `user_id` 或格式错误 |
| `422` | 请求体 JSON Schema 验证失败 |
| `429` | 超过速率限制，响应头含 `Retry-After` |

---

## GET /api/v1/semantic/metrics

获取语义模型中所有可用指标，按业务域分组返回。可用于前端展示可查询的指标范围或提示词提示。

### 响应

```json
{
  "version": 3,
  "domains": [
    {
      "id": "sales",
      "name": "销售域",
      "metrics": [
        {
          "id": "gmv",
          "name": "GMV",
          "aliases": ["GMV", "成交额", "交易额", "销售额"],
          "description": "实付成交总额",
          "format": "currency"
        }
      ]
    }
  ]
}
```

---

## POST /api/v1/semantic/reload

热重载语义模型配置文件（`semantic_model.yaml`），无需重启服务。

### 请求头

```
X-Admin-Token: your-admin-token
```

### 响应

**成功**

```json
{
  "status": "reloaded",
  "version": 4,
  "domains": 4,
  "metrics": 23
}
```

**认证失败**（HTTP 403）

```json
{
  "detail": "Forbidden"
}
```

---

## GET /health

健康检查端点，供 Docker Compose 和负载均衡器使用。

### 响应

```json
{ "status": "ok" }
```

---

## 前端 SSE 接入示例

由于标准 `EventSource` 不支持 POST 请求，ChatBI 使用 `fetch` + `ReadableStream` 手动解析 SSE：

```typescript
async function* streamChat(request: ChatRequest, signal: AbortSignal) {
  const response = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()!  // 保留不完整的最后一行

    let event = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        event = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        yield { event, data: line.slice(6) }
        event = ''
      }
    }
  }
}
```
