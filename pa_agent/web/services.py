"""Backend services used by the FastAPI browser surface."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pa_agent.app_context import AppContext
from pa_agent.config.paths import RECORDS_PENDING_DIR, SETTINGS_JSON_PATH
from pa_agent.config.settings import Settings, load_settings, save_settings
from pa_agent.data.factory import (
    DATA_SOURCE_CHOICES,
    create_data_source,
    normalize_data_source_kind,
)
from pa_agent.data.snapshot import build_analysis_frame, build_live_frame
from pa_agent.records.schema import AnalysisRecord
from pa_agent.util.threading import OrchestratorEvent


def serialize_bar(bar: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(bar) and not isinstance(bar, type):
        return dataclasses.asdict(bar)
    if isinstance(bar, dict):
        return dict(bar)
    return dict(getattr(bar, "__dict__", {}))


def serialize_frame(frame: Any | None) -> dict[str, Any] | None:
    if frame is None:
        return None
    bars = [serialize_bar(bar) for bar in getattr(frame, "bars", [])]
    indicators = getattr(frame, "indicators", None)
    return {
        "symbol": getattr(frame, "symbol", ""),
        "timeframe": getattr(frame, "timeframe", ""),
        "snapshot_ts_local_ms": getattr(frame, "snapshot_ts_local_ms", 0),
        "bars": bars,
        "indicators": {
            "ema20": list(getattr(indicators, "ema20", []) or []),
            "atr14": list(getattr(indicators, "atr14", []) or []),
        },
    }


class SettingsService:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or SETTINGS_JSON_PATH

    def get(self) -> Settings:
        return load_settings(self._path)

    def update(self, payload: dict[str, Any]) -> Settings:
        current = load_settings(self._path).model_dump()
        merged = _deep_merge(current, payload)
        settings = Settings.model_validate(merged)
        save_settings(settings, self._path)
        return settings


class MarketService:
    def __init__(self, ctx: AppContext, *, settings_path: Path | None = None) -> None:
        self._ctx = ctx
        self._settings_path = settings_path or SETTINGS_JSON_PATH
        self._lock = threading.Lock()

    @property
    def settings(self) -> Any:
        return getattr(self._ctx, "settings", None)

    def sources(self) -> dict[str, Any]:
        current = ""
        if self.settings is not None:
            current = getattr(self.settings.general, "last_data_source", "")
        return {
            "current": normalize_data_source_kind(current),
            "choices": [{"id": kind, "label": label} for kind, label in DATA_SOURCE_CHOICES],
        }

    def subscribe(
        self, *, data_source: str, symbol: str, timeframe: str, exchange: str = ""
    ) -> dict[str, Any]:
        kind = normalize_data_source_kind(data_source)
        with self._lock:
            settings = self.settings or load_settings(self._settings_path)
            old = getattr(self._ctx, "data_source", None)
            if (
                old is None
                or normalize_data_source_kind(getattr(settings.general, "last_data_source", ""))
                != kind
            ):
                try:
                    if old is not None:
                        old.disconnect()
                except Exception:
                    pass
                self._ctx.data_source = create_data_source(kind)
            source = self._ctx.data_source
            error = ""
            try:
                source.connect()
                if kind == "tradingview" and hasattr(source, "set_exchange"):
                    source.set_exchange(exchange or "")
                source.subscribe(symbol, timeframe)
            except Exception as exc:
                error = str(exc)

            settings.general.last_data_source = kind
            settings.general.last_symbol = symbol
            settings.general.last_timeframe = timeframe
            if hasattr(settings.general, "last_tradingview_exchange"):
                settings.general.last_tradingview_exchange = exchange or ""
            self._ctx.settings = settings
            save_settings(settings, self._settings_path)
            return {
                "ok": not bool(error),
                "error": error,
                "data_source": kind,
                "symbol": symbol,
                "timeframe": timeframe,
                "exchange": exchange or "",
            }

    def snapshot(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        bar_count: int | None = None,
        live: bool = True,
    ) -> dict[str, Any]:
        settings = self.settings or load_settings(self._settings_path)
        symbol = symbol or settings.general.last_symbol
        timeframe = timeframe or settings.general.last_timeframe
        bar_count = int(bar_count or settings.general.analysis_bar_count)
        source = getattr(self._ctx, "data_source", None)
        if source is None:
            return {"ok": False, "error": "No data source is configured.", "frame": None}
        try:
            raw_bars = source.latest_snapshot(bar_count + 1)
            frame = (
                build_live_frame(raw_bars, bar_count, symbol, timeframe)
                if live
                else build_analysis_frame(raw_bars, bar_count, symbol, timeframe)
            )
            return {
                "ok": frame is not None,
                "error": "" if frame else "Insufficient bars.",
                "frame": serialize_frame(frame),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "frame": None}

    def analysis_frame(self, request: Any) -> Any:
        settings = self.settings or load_settings(self._settings_path)
        symbol = request.symbol or settings.general.last_symbol
        timeframe = request.timeframe or settings.general.last_timeframe
        bar_count = int(request.bar_count or settings.general.analysis_bar_count)
        source = getattr(self._ctx, "data_source", None)
        if source is None:
            raise RuntimeError("No data source is configured.")
        raw_bars = source.latest_snapshot(bar_count + 1)
        frame = build_analysis_frame(raw_bars, bar_count, symbol, timeframe)
        if frame is None:
            raise RuntimeError("Insufficient closed bars for analysis.")
        return frame

    def market_events(self) -> Iterator[str]:
        from pa_agent.web.jobs import encode_sse

        while True:
            yield encode_sse(
                {"event": "snapshot", "data": self.snapshot(), "ts_ms": int(time.time() * 1000)}
            )
            time.sleep(1.0)


class AnalysisService:
    def __init__(self, ctx: AppContext, market: MarketService) -> None:
        self._ctx = ctx
        self._market = market

    def run(self, job: Any, request: Any) -> None:
        job.status = "running"
        job.emit("status", {"message": "analysis_started"})
        try:
            frame = self._market.analysis_frame(request)
            job.emit("market_frame", {"frame": serialize_frame(frame)})
            orchestrator = self._build_orchestrator()

            def on_event(event: OrchestratorEvent) -> None:
                job.emit("orchestrator_event", {"name": event.name})

            record = orchestrator.submit(
                frame=frame,
                cancel_token=job.cancel_token,
                on_event=on_event,
                on_stage1_reasoning=lambda chunk: job.emit(
                    "token", {"stage": "stage1", "kind": "reasoning", "text": chunk}
                ),
                on_stage1_content=lambda chunk: job.emit(
                    "token", {"stage": "stage1", "kind": "content", "text": chunk}
                ),
                on_stage2_reasoning=lambda chunk: job.emit(
                    "token", {"stage": "stage2", "kind": "reasoning", "text": chunk}
                ),
                on_stage2_content=lambda chunk: job.emit(
                    "token", {"stage": "stage2", "kind": "content", "text": chunk}
                ),
                on_stage_prompt=lambda stage, system, user: job.emit(
                    "prompt", {"stage": stage, "system": system, "user": user}
                ),
                on_stage2_files=lambda files: job.emit("stage2_files", {"files": files}),
            )
            job.result = record
            job.status = "cancelled" if job.cancel_token.is_set() else "completed"
            job.emit(
                "record",
                {
                    "record": record.model_dump(),
                    "effective_decision": record.effective_decision,
                    "pre_delivery_gate": record.pre_delivery_gate,
                },
            )
        except Exception as exc:
            job.error = str(exc)
            job.status = "failed"
            job.emit("error", {"message": str(exc)})

    def _build_orchestrator(self) -> Any:
        from pa_agent.orchestrator.two_stage import TwoStageOrchestrator

        required = (
            self._ctx.client,
            self._ctx.assembler,
            self._ctx.router,
            self._ctx.validator,
            self._ctx.pending_writer,
            self._ctx.exp_reader,
        )
        if not all(component is not None for component in required):
            raise RuntimeError("Analysis backend is not fully configured.")
        return TwoStageOrchestrator(
            client=self._ctx.client,
            assembler=self._ctx.assembler,
            router=self._ctx.router,
            validator=self._ctx.validator,
            pending_writer=self._ctx.pending_writer,
            exp_reader=self._ctx.exp_reader,
            settings=self._ctx.settings,
        )


class RecordService:
    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or RECORDS_PENDING_DIR

    def list(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self._directory.is_dir():
            return records
        for path in sorted(
            self._directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            raw = self._read_json(path)
            if not isinstance(raw, dict):
                continue
            meta = raw.get("meta") or {}
            records.append(
                {
                    "id": path.stem,
                    "path": str(path),
                    "mtime": path.stat().st_mtime,
                    "symbol": meta.get("symbol", ""),
                    "timeframe": meta.get("timeframe", ""),
                    "timestamp_local_iso": meta.get("timestamp_local_iso", ""),
                    "exception": raw.get("exception"),
                    "pre_delivery_gate": raw.get("pre_delivery_gate"),
                    "effective_decision": raw.get("effective_decision"),
                }
            )
        return records

    def load(self, record_id: str) -> dict[str, Any] | None:
        path = self._path_for_id(record_id)
        raw = self._read_json(path) if path is not None else None
        if not isinstance(raw, dict):
            return None
        raw.pop("_partial_reason", None)
        record = AnalysisRecord.model_validate(raw)
        return record.model_dump()

    def load_model(self, record_id: str | None = None) -> AnalysisRecord | None:
        if record_id is None:
            items = self.list()
            if not items:
                return None
            record_id = str(items[0]["id"])
        data = self.load(record_id)
        if data is None:
            return None
        return AnalysisRecord.model_validate(data)

    def _path_for_id(self, record_id: str) -> Path | None:
        safe_id = Path(record_id).name
        path = self._directory / f"{safe_id}.json"
        if path.is_file():
            return path
        return None

    @staticmethod
    def _read_json(path: Path | None) -> Any:
        if path is None or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None


class FollowupService:
    def __init__(self, ctx: AppContext, records: RecordService) -> None:
        self._ctx = ctx
        self._records = records

    def run(self, job: Any, request: Any) -> None:
        job.status = "running"
        job.emit("status", {"message": "followup_started"})
        try:
            record = self._records.load_model(request.record_id)
            if record is None:
                raise RuntimeError("Record not found.")
            session = self._build_session(record)

            def on_reasoning(chunk: str) -> None:
                job.emit("token", {"kind": "reasoning", "text": chunk})

            def on_content(chunk: str) -> None:
                job.emit("token", {"kind": "content", "text": chunk})

            turn = session.send(
                request.message,
                job.cancel_token,
                on_reasoning_token=on_reasoning,
                on_content_token=on_content,
            )
            job.result = turn
            job.status = "cancelled" if job.cancel_token.is_set() else "completed"
            job.emit("turn", {"turn": turn.model_dump()})
        except Exception as exc:
            job.error = str(exc)
            job.status = "failed"
            job.emit("error", {"message": str(exc)})

    def _build_session(self, record: AnalysisRecord) -> Any:
        from pa_agent.orchestrator.free_chat import FreeChatSession

        required = (
            self._ctx.client,
            self._ctx.assembler,
            self._ctx.pending_writer,
            self._ctx.ledger,
        )
        if not all(component is not None for component in required):
            raise RuntimeError("Follow-up backend is not fully configured.")
        return FreeChatSession(
            base_record=record,
            client=self._ctx.client,
            assembler=self._ctx.assembler,
            pending_writer=self._ctx.pending_writer,
            ledger=self._ctx.ledger,
            settings=self._ctx.settings,
        )


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
