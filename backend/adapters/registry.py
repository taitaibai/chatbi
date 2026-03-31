from __future__ import annotations

from adapters.base import DataSourceAdapter
from adapters.mock import MockAdapter
from config.settings import settings


def get_adapter(datasource_type: str | None = None) -> DataSourceAdapter:
    source = (datasource_type or settings.datasource_type).lower()
    if source == "mock":
        return MockAdapter()
    raise ValueError(f"Unsupported datasource type: {source}")
