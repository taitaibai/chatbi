# 快速开始

## 前置条件

- Docker 20.10+
- Docker Compose v2+
- 一个兼容 OpenAI SDK 的 LLM 服务的 API Key（OpenAI、DeepSeek、MiniMax 等均可）

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/your-username/chatbi.git
cd chatbi
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

打开 `.env`，至少填写以下三项：

```bash
# 填写你使用的 LLM 服务的 Key
LLM_API_KEY=sk-your-api-key

# 填写模型名称
LLM_MODEL=gpt-4o-mini

# 填写 API 端点（使用 OpenAI 官方服务时留空）
LLM_BASE_URL=
```

### 3. 启动服务

```bash
docker compose up -d
```

首次启动会拉取基础镜像并构建，约需 1-3 分钟。启动后：

- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- API 文档（Swagger）：http://localhost:8000/docs

查看服务状态：

```bash
docker compose ps
docker compose logs -f backend   # 实时查看后端日志
```

### 4. 开始提问

打开 http://localhost:5173，在输入框中尝试：

```
上周各渠道 GMV 对比
```

你将看到系统依次推送：意图解析结果、生成的 SQL、数据表格、图表，以及流式文字解读。

其他可以尝试的问题：

```
最近 30 天新增用户趋势
各品类销售额和退款率
今天的 DAU 是多少
App 渠道的 7 日留存率
```

---

## 不使用 Docker 的本地运行方式

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 将项目根目录的 .env 复制一份到 backend/.env，或直接从根目录启动
uvicorn main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev   # 启动 Vite Dev Server，默认 :5173
```

前端开发服务器会将 `/api` 请求代理到 `http://localhost:8000`，无需额外配置。

---

## 运行测试

```bash
cd backend
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

后端共有 9 个测试模块，覆盖 NLU、语义映射、SQL 生成、安全检查、Pipeline、审计日志等核心逻辑。

---

## 常见问题

**Q：提问后返回"AI 分析服务暂时不可用"**

检查 `.env` 中的 `LLM_API_KEY` 是否正确，以及 `LLM_BASE_URL` 是否可以访问。

```bash
# 验证后端是否加载到正确的 Key
docker exec chatbi-backend env | grep LLM
```

**Q：返回"Table not allowed"**

`ALLOWED_TABLES` 环境变量中的表名必须与 `semantic_model.yaml` 中定义的物理表名一致（含 schema 前缀，如 `dw.fact_orders`）。修改 `.env` 后需要重新创建容器：

```bash
docker compose up -d backend
```

注意：`docker compose restart` 不会重新加载 `.env`，必须用 `up -d`。

**Q：修改后端代码后不生效**

后端容器挂载了 `./backend:/app` 卷，代码变更会实时同步到容器。uvicorn 在 `--reload` 模式下会自动重启。如果修改了 `requirements.txt`，需要重新构建镜像：

```bash
docker compose build backend && docker compose up -d backend
```

**Q：修改前端代码后不生效**

前端代码被打包进镜像，每次修改后需要重新构建：

```bash
docker compose build frontend && docker compose up -d frontend
```

**Q：如何接入自己的数据库**

参考 [系统架构文档](architecture.md#数据源适配器) 实现 `DataSourceAdapter` 接口，然后更新 `semantic_model.yaml` 配置业务指标和维度。
