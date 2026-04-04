from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM 配置
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "MINIMAX_API_KEY", "LLM_API_KEY"),
        description="LLM API Key（兼容 OpenAI SDK，如 MiniMax）",
    )
    llm_model: str = Field(default="MiniMax-M2.5", description="默认 LLM 模型")
    llm_base_url: str = Field(
        default="https://api.minimaxi.com/v1",
        description="LLM 接口基础 URL（兼容 OpenAI SDK，如 MiniMax）",
    )
    llm_timeout_seconds: int = Field(default=60, description="LLM 请求超时时间（秒）")

    # 数据源配置
    datasource_type: str = Field(
        default="mock", description="数据源类型：mock / clickhouse / mysql"
    )
    semantic_model_path: str = Field(
        default="backend/config/semantic_model.yaml",
        description="语义模型 YAML 路径",
    )
    audit_db_path: str = Field(
        default="backend/data/audit.db", description="审计日志 SQLite 路径"
    )
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="允许跨域访问的来源列表",
    )

    # 日志配置
    log_level: str = Field(
        default="INFO", description="日志级别：DEBUG / INFO / WARNING / ERROR"
    )

    # 安全配置
    allowed_tables: str = Field(
        default="fact_orders,fact_refunds,fact_user_daily,dim_users,fact_product_sales,dim_products,fact_page_views,fact_channel_traffic",
        description="SQL 白名单表名，逗号分隔",
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_allowed_origins(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return value
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @property
    def allowed_tables_set(self) -> set[str]:
        return {t.strip() for t in self.allowed_tables.split(",") if t.strip()}

    # 复杂度配置
    complexity_threshold: int = Field(
        default=100_000_000, description="预估扫描行数上限"
    )

    # 会话配置
    session_ttl_seconds: int = Field(
        default=1800, description="会话不活跃超时时间（秒）"
    )

    # 管理接口 Token
    admin_token: str = Field(
        default="change-me-in-production", description="管理接口鉴权 Token"
    )
    rate_limit_per_minute: int = Field(
        default=20, description="同一 user_id 每分钟最大请求数"
    )

    # LLM 并发控制
    llm_max_concurrent: int = Field(
        default=10, description="同时进行的 LLM 调用数上限（asyncio.Semaphore）"
    )


settings = Settings()
