"""FastAPI application factory for the PA Agent browser UI."""

from __future__ import annotations

import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pa_agent.app_context import AppContext
from pa_agent.config.paths import PROJECT_ROOT
from pa_agent.config.settings import Settings
from pa_agent.util.threading import CancelToken
from pa_agent.web.jobs import JobRegistry, event_stream
from pa_agent.web.schemas import (
    AnalysisRequest,
    FollowupRequest,
    JobCreated,
    SourceSubscribeRequest,
    public_settings,
)
from pa_agent.web.services import (
    AnalysisService,
    FollowupService,
    MarketService,
    RecordService,
    SettingsService,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    ctx: AppContext | None = None,
    *,
    settings_path: Path | None = None,
    records_dir: Path | None = None,
) -> FastAPI:
    """Create the web app.  Tests may inject a lightweight AppContext."""

    ctx = ctx or AppContext.bootstrap()
    settings_service = SettingsService(settings_path)
    market = MarketService(ctx, settings_path=settings_path)
    records = RecordService(records_dir)
    analysis = AnalysisService(ctx, market)
    followups = FollowupService(ctx, records)
    jobs = JobRegistry()

    app = FastAPI(title="PA Agent", version="0.1.0")
    app.state.ctx = ctx
    app.state.jobs = jobs

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "app": "pa-agent",
            "surface": "web",
            "project_root": str(PROJECT_ROOT),
        }

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        settings = getattr(ctx, "settings", None) or settings_service.get()
        return public_settings(settings)

    @app.put("/api/settings")
    def put_settings(payload: dict[str, Any]) -> dict[str, Any]:
        settings = settings_service.update(payload)
        _copy_settings_into_context(ctx, settings)
        return public_settings(settings)

    @app.get("/api/sources")
    def get_sources() -> dict[str, Any]:
        return market.sources()

    @app.post("/api/source/subscribe")
    def subscribe(req: SourceSubscribeRequest) -> dict[str, Any]:
        return market.subscribe(
            data_source=req.data_source,
            symbol=req.symbol,
            timeframe=req.timeframe,
            exchange=req.exchange,
        )

    @app.get("/api/market/snapshot")
    def snapshot(
        symbol: str | None = None,
        timeframe: str | None = None,
        bar_count: int | None = None,
    ) -> dict[str, Any]:
        return market.snapshot(symbol=symbol, timeframe=timeframe, bar_count=bar_count)

    @app.get("/api/market/events")
    def market_events() -> StreamingResponse:
        return StreamingResponse(market.market_events(), media_type="text/event-stream")

    @app.post("/api/analysis", response_model=JobCreated)
    def post_analysis(req: AnalysisRequest) -> JobCreated:
        token = CancelToken()
        job = jobs.create("analysis", cancel_token=token)
        thread = threading.Thread(target=analysis.run, args=(job, req), daemon=True)
        job.thread = thread
        thread.start()
        return JobCreated(
            job_id=job.id,
            status=job.status,
            events_url=f"/api/analysis/{job.id}/events",
        )

    @app.post("/api/analysis/{job_id}/cancel")
    def cancel_analysis(job_id: str) -> dict[str, Any]:
        job = _get_job_or_404(jobs, job_id)
        if job.cancel_token is not None:
            job.cancel_token.set()
        job.status = "cancelled"
        job.emit("cancelled", {"message": "Cancellation requested."})
        return {"ok": True, "job_id": job_id, "status": job.status}

    @app.get("/api/analysis/{job_id}/events")
    def analysis_events(job_id: str) -> StreamingResponse:
        job = _get_job_or_404(jobs, job_id)
        return StreamingResponse(event_stream(job), media_type="text/event-stream")

    @app.get("/api/records")
    def list_records() -> dict[str, Any]:
        return {"records": records.list()}

    @app.get("/api/records/{record_id}")
    def get_record(record_id: str) -> dict[str, Any]:
        record = records.load(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Record not found.")
        return record

    @app.post("/api/followup", response_model=JobCreated)
    def post_followup(req: FollowupRequest) -> JobCreated:
        if not req.message.strip():
            raise HTTPException(status_code=400, detail="Message is required.")
        token = CancelToken()
        job = jobs.create("followup", cancel_token=token)
        thread = threading.Thread(target=followups.run, args=(job, req), daemon=True)
        job.thread = thread
        thread.start()
        return JobCreated(
            job_id=job.id,
            status=job.status,
            events_url=f"/api/followup/{job.id}/events",
        )

    @app.get("/api/followup/{job_id}/events")
    def followup_events(job_id: str) -> StreamingResponse:
        job = _get_job_or_404(jobs, job_id)
        return StreamingResponse(event_stream(job), media_type="text/event-stream")

    return app


def _copy_settings_into_context(ctx: AppContext, settings: Settings) -> None:
    ctx.settings = settings
    client = getattr(ctx, "client", None)
    if client is not None and hasattr(client, "update_provider"):
        with suppress(Exception):
            client.update_provider(settings.provider)


def _get_job_or_404(jobs: JobRegistry, job_id: str) -> Any:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job
