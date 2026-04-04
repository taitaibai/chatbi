import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware import RateLimitMiddleware
from api.v1.chat import router as chat_router
from api.v1.semantic import router as semantic_router
from config.settings import settings
from observability.audit import audit_logger

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_admin_token_safety()
    _check_openai_api_key()
    await audit_logger.initialize()
    logger.info(
        "chatbi_startup",
        llm_model=settings.llm_model,
        datasource_type=settings.datasource_type,
        log_level=settings.log_level,
        semantic_model_path=settings.semantic_model_path,
    )
    try:
        yield
    finally:
        await audit_logger.close()


app = FastAPI(
    title="ChatBI API",
    description="面向数据分析的自然语言交互式分析系统",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(chat_router)
app.include_router(semantic_router)


@app.get("/health", summary="健康检查", tags=["系统"])
async def health_check() -> dict:
    return {"status": "ok"}


_DEFAULT_ADMIN_TOKEN = "change-me-in-production"


def _check_admin_token_safety() -> None:
    """Guard against deploying with the default admin token.

    In production (APP_ENV=production) the application refuses to start.
    In all other environments a prominent warning is logged.
    """
    if settings.admin_token != _DEFAULT_ADMIN_TOKEN:
        return

    app_env = os.getenv("APP_ENV", "dev").lower()
    if app_env == "production":
        raise RuntimeError(
            "admin_token is still set to the default value. "
            "Set a strong secret via the ADMIN_TOKEN environment variable before deploying."
        )

    logger.warning(
        "admin_token_default_value",
        message="admin_token is using the default value — change ADMIN_TOKEN before deploying to production",
    )


def _check_openai_api_key() -> None:
    if settings.datasource_type == "mock" or settings.openai_api_key.strip():
        return
    raise RuntimeError(
        "llm_api_key is empty. Set OPENAI_API_KEY, MINIMAX_API_KEY, or LLM_API_KEY before starting the service."
    )
