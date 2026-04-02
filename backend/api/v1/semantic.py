from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from config.loader import get_semantic_model
from config.settings import settings
from services.semantic import semantic_service

router = APIRouter(prefix="/api/v1/semantic", tags=["semantic"])


@router.get("/metrics")
async def get_semantic_metrics() -> dict[str, object]:
    return {"domains": semantic_service.get_available_metrics()}


@router.post("/reload")
async def reload_semantic_model(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, object]:
    if x_admin_token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
        )

    model = get_semantic_model(force_reload=True)
    return {
        "status": "reloaded",
        "version": model.version,
        "domain_count": len(model.domains),
    }
