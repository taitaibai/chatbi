# 系统架构

## 整体设计

ChatBI 采用**管道（Pipeline）架构**。一次用户提问经过 8 个串行步骤处理，每个步骤独立、可替换，每个中间结果通过 SSE 实时推送到前端，用户无需等待全部完成就能看到分析进展。

```
用户输入
   │
   ▼
┌─────────────────────────────────────────────┐
│            查询管道 (pipeline.py)            │
│                                             │
│  ① NLU         自然语言 → 结构化意图         │
│  ② 语义映射    业务术语 → 物理 SQL 元素       │
│  ③ SQL 生成    SQL 元素 → SQL 语句           │
│  ④ 安全检查    AST 分析，拦截危险操作         │
│  ⑤ 复杂度评估  预估扫描行数，超限拦截         │
│  ⑥ 执行        适配器执行 SQL，返回结果集     │
│  ⑦ 可视化      规则推荐图表类型              │
│  ⑧ 解读        LLM 流式生成业务洞察文字       │
│                                             │
└─────────────────────────────────────────────┘
         │  SSE 流式推送
         ▼
      前端实时渲染
```

**短路机制**：任何步骤出错均立即中止并推送错误事件，不继续后续步骤：
- NLU 无法理解 → 推送 `clarification_needed` 事件，引导用户重新描述
- 语义映射失败 → 推送可用指标列表
- SQL 不安全 → 推送具体违规原因
- 复杂度超限 → 推送优化建议

---

## 前端架构

```
App.tsx
└── ChatWindow.tsx          # 顶栏 + 对话区 + 输入框
    ├── useSSEChat (hook)   # 状态机，管理消息列表和 SSE 连接
    │   └── streamChat()    # fetch + ReadableStream 解析 SSE
    └── MessageBubble.tsx   # 渲染单条消息
        ├── IntentSummaryCard.tsx   # 意图解析卡（默认折叠）
        ├── SQLPanel.tsx            # SQL 展示（默认折叠）
        ├── ResultTable.tsx         # 查询结果表格
        ├── ChartRenderer.tsx       # ECharts 图表
        └── ClarificationCard.tsx   # 澄清问题卡
```

### SSE 状态机

`useSSEChat` 使用 `useReducer` 管理对话状态，确保多个并发 SSE 事件更新不产生竞态：

```
Action 类型：
  SEND               → 创建用户消息和助手 loading 消息
  INTENT_SUMMARY     → 追加意图摘要到当前助手消息
  SQL                → 追加 SQL 内容
  TABLE_DATA         → 追加结果表格
  CHART_SPEC         → 追加图表规格
  INTERPRETATION_TOKEN → 追加/拼接流式文字
  BOT_ERROR          → 标记错误状态
  DONE               → 标记完成，写入延迟和 token 信息
  CLEAR              → 重置对话，生成新 session_id
```

---

## 后端各模块说明

### NLU 意图解析 (`services/nlu.py`)

将用户的中文自然语言转换为结构化的 `ParsedIntent`。

**输入**：用户原始查询文本

**处理**：
1. 检测是否为"追问"（正则匹配"那""也""呢""对比""换成"等词），决定是否继承上轮上下文
2. 用 Jinja2 渲染提示词，将所有可用指标（含别名）、维度、会话上下文注入
3. 以 `response_format: json_object` 调用 LLM，JSON 解析失败时最多重试 3 次
4. 自动剥离推理模型输出的 `<think>` 标签（支持 DeepSeek-R1、MiniMax-M2.7 等推理模型）
5. 若 LLM 返回 `clarification_needed=true`，直接短路，不进入后续步骤

**输出**：`ParsedIntent`
```python
{
  "metrics": ["GMV"],
  "dimensions": ["渠道"],
  "time_range": {
    "type": "last_week",
    "start": "2025-03-31",
    "end": "2025-04-06"
  },
  "filters": [],
  "is_followup": False,
  "clarification_needed": False
}
```

---

### 语义映射 (`services/semantic.py`)

将 `ParsedIntent` 中的业务术语（"GMV"、"渠道"）映射到物理 SQL 元素。这是系统与具体数据库解耦的关键层。

**语义模型** (`config/semantic_model.yaml`)：

```yaml
domains:
  - id: sales
    name: 销售域
    tables:
      - id: fact_orders
        name: dw.fact_orders      # 物理表名（含 schema）
        time_field: order_date    # 时间过滤字段
        dimensions:
          - id: channel
            name: 渠道
            aliases: ["渠道", "下单渠道"]
            field: channel
    metrics:
      - id: gmv
        name: GMV
        aliases: ["GMV", "成交额", "交易额", "销售额"]
        expression: SUM(amount)   # 聚合表达式
        base_table: fact_orders
        filters: ["status = 'paid'"]  # 内置过滤条件
        format: currency
```

**支持的关系**：
- 单表聚合查询
- 跨表 JOIN（每个指标可配置依赖的额外 JOIN）
- 多指标混合（自动合并去重 JOIN 和 WHERE 条件）

**输出**：`ResolvedQuery`（完整的 SQL 构成元素，可直接编译为 SQL）

---

### SQL 生成 (`services/sql_gen.py`)

将 `ResolvedQuery` 生成可执行 SQL，支持两种路径：

**路径一：LLM 生成（默认）**
- 将 resolved_query 结构化信息注入提示词，由 LLM 生成 SQL
- 自动提取 SQL 代码块（`\`\`\`sql ... \`\`\``），剥离注释和多余空白
- 适合复杂查询，灵活性高

**路径二：确定性编译器（LLM 不可用时的 fallback）**
- 直接按照规则拼接 SELECT、FROM、JOIN、WHERE、GROUP BY
- 结果稳定可预期，适合单元测试

---

### SQL 安全检查 (`services/security.py`)

使用 sqlglot 将 SQL 解析为 AST，进行多层校验：

| 检查项 | 规则 | 错误类型 |
|--------|------|----------|
| 语句类型 | 仅允许 SELECT | `SQLUnsafeError` |
| SELECT * | 禁止通配符 | `SQLUnsafeError` |
| 多语句 | 禁止分号分隔的多条语句 | `SQLUnsafeError` |
| 危险操作 | 禁止 INSERT/UPDATE/DELETE/DROP/ALTER | `SQLUnsafeError` |
| 表白名单 | 所有表必须在 `ALLOWED_TABLES` 中 | `SQLUnsafeError` |
| JOIN 数量 | 最多 3 个 JOIN | `SQLUnsafeError` |

**注**：使用 AST 而非字符串匹配，可以正确处理注释、引号内内容等边界情况。

---

### 复杂度评估 (`services/complexity.py`)

在执行前预估查询代价，超限拦截或给出优化建议：

```
评估结果：
  BLOCKED  → HTTP 错误 + 拦截原因 + 优化建议
  WARNING  → 允许执行，同时推送警告给前端
  OK       → 正常执行
```

默认复杂度阈值：1 亿行（`COMPLEXITY_THRESHOLD`）。

---

### 数据源适配器 (`adapters/`)

采用策略模式，通过抽象接口屏蔽底层数据库差异：

```python
class DataSourceAdapter(ABC):
    async def execute(self, sql: str) -> QueryResult: ...
    async def estimate_complexity(self, sql: str) -> ComplexityEstimate: ...
    async def health_check(self) -> bool: ...
```

**当前实现**：`MockAdapter` — 内置 4 个业务域的模拟数据，无需真实数据库即可体验完整功能。

**接入真实数据库**：实现上述接口，在 `adapters/registry.py` 中注册，并设置 `DATASOURCE_TYPE` 环境变量。

---

### 可视化推荐 (`services/visualization.py`)

基于查询结果的数据特征自动推荐最合适的图表类型：

| 条件 | 推荐图表 |
|------|---------|
| 单行单指标 | 数字卡片（Card） |
| 第一列为日期 | 折线图（Line） |
| ≤ 6 行 + 单指标 | 饼图（Pie） |
| 多行多维度 | 柱状图（Bar） |
| 否则 | 表格（Table） |

输出 ECharts option JSON，前端 `ChartRenderer` 直接传入 `echarts.setOption()`。

---

### 结果解读 (`services/interpreter.py`)

用 LLM 流式生成业务洞察文字，逐 token 推送到前端：

- 只传入聚合结果的前 10 行（防止 prompt 过长，也避免暴露大量明细数据）
- 要求 LLM 第一句指出最高值维度及具体数字，第二句描述分布或最低值
- 使用 streaming 模式，用户可在数据展示后立即看到文字分析开始出现

---

### 审计日志 (`observability/audit.py`)

每次请求全量记录到 SQLite，用于问题排查和用量统计。

**关键设计**：
- **非阻塞写入**：通过 `asyncio.Queue` + 后台单消费者任务，写入不阻塞业务响应
- **隐私保护**：用户 ID 存储 SHA-256 哈希，长数字串（电话、身份证等）自动脱敏
- **单连接复用**：SQLite 使用长连接，避免频繁 open/close 开销

**记录字段**：`request_id`、`session_id`、`user_id_hash`、`raw_query`、`intent_json`、`generated_sql`、`response_type`、`error_code`、`datasource_exec_ms`、`total_ms`、`llm_tokens`、`created_at`

---

## 完整数据流示例

**用户提问**："上周各渠道 GMV 对比"

```
① NLU
   LLM 识别：metrics=["GMV"], dimensions=["渠道"], time_range={type:"last_week"}
   → SSE 推送 intent_summary 事件

② 语义映射
   GMV → base_table=fact_orders, expression=SUM(amount), filter="status='paid'"
   渠道 → field=channel, table=fact_orders
   → 构建 ResolvedQuery

③ SQL 生成
   SELECT channel, SUM(amount) AS gmv
   FROM dw.fact_orders
   WHERE status = 'paid'
     AND order_date BETWEEN '2025-03-31' AND '2025-04-06'
   GROUP BY channel
   → SSE 推送 sql 事件

④ 安全检查
   AST 分析：SELECT ✓，表在白名单 ✓，无危险操作 ✓
   → 通过

⑤ 复杂度评估
   预估扫描行数 120,000 < 1 亿
   → OK

⑥ 执行
   MockAdapter 返回：
   [("App", 258000), ("Web", 187500), ("H5", 96500), ("小程序", 142300)]
   → SSE 推送 table_data 事件

⑦ 可视化
   多行 + 单指标 → 柱状图
   生成 ECharts option
   → SSE 推送 chart_spec 事件

⑧ 解读
   LLM 流式输出："App 渠道成交额最高，达 25.8 万元……"
   → SSE 逐 token 推送 interpretation 事件

   → SSE 推送 done 事件（含延迟、token 消耗）
```

---

## 安全设计

| 防护层 | 位置 | 机制 |
|--------|------|------|
| 速率限制 | `api/middleware.py` | 滑动窗口，按 user_id，默认 20 次/分钟 |
| SQL 注入防护 | `services/security.py` | LLM 生成的 SQL 经 AST 级别校验 |
| 表访问控制 | `services/security.py` | 白名单机制，只允许配置中声明的表 |
| 数据脱敏 | `observability/audit.py` | 用户 ID 哈希，敏感数字串自动脱敏 |
| Admin 接口认证 | `api/v1/semantic.py` | X-Admin-Token 头部校验 |

---

## 部署架构

```
                  ┌──────────────────────────────┐
用户浏览器  ──►   │  chatbi-frontend (Nginx:80)   │ :5173
                  │  /api → proxy → backend:8000  │
                  └──────────────┬───────────────┘
                                 │
                  ┌──────────────▼───────────────┐
                  │  chatbi-backend (uvicorn)     │ :8000
                  │  ./backend:/app (volume)      │
                  │  chatbi_data:/app/data        │
                  └──────────────────────────────┘
                                 │
                  ┌──────────────▼───────────────┐
                  │  LLM API（外部服务）           │
                  │  OpenAI / DeepSeek / MiniMax  │
                  └──────────────────────────────┘
```

Docker volume `chatbi_data` 持久化 SQLite 审计日志，后端容器重建后数据不丢失。
