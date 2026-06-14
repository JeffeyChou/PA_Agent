"""Pydantic request/response schemas for the browser API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceSubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_source: str
    symbol: str
    timeframe: str
    exchange: str = ""


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str | None = None
    timeframe: str | None = None
    data_source: str | None = None
    bar_count: int | None = Field(default=None, ge=2, le=5000)
    force_incremental: bool = False
    wait_for_close: bool = False
    keep_analysis: bool = False


class FollowupRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str | None = None
    message: str


class JobCreated(BaseModel):
    job_id: str
    status: str
    events_url: str


def public_settings(settings: Any) -> dict[str, Any]:
    """Serialize settings without exposing a plaintext API key."""

    data = settings.model_dump() if hasattr(settings, "model_dump") else dict(settings)
    provider = dict(data.get("provider") or {})
    api_key = str(provider.get("api_key") or "")
    provider["api_key_configured"] = bool(api_key.strip())
    provider["api_key"] = "****" if api_key.strip() else ""
    data["provider"] = provider
    return data
