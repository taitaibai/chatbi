import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from observability.audit import audit_logger
from config.settings import settings

# 配置结构化日志
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(__import__("logging"), settings.log_level, 20)
    ),
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="ChatBI API",
    description="面向数据分析的自然语言交互式分析系统",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", summary="健康检查", tags=["系统"])
async def health_check() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup() -> None:
    await audit_logger.initialize()
    logger.info(
        "chatbi_startup",
        llm_model=settings.llm_model,
        datasource_type=settings.datasource_type,
        log_level=settings.log_level,
        semantic_model_path=settings.semantic_model_path,
    )
