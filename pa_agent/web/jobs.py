"""In-process job registry and Server-Sent Event helpers."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pa_agent.util.timefmt import now_local_ms

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(slots=True)
class WebJob:
    id: str
    kind: str
    status: str = "queued"
    cancel_token: Any = None
    events: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)
    result: Any = None
    error: str = ""
    thread: threading.Thread | None = None

    def emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        self.events.put(
            {
                "event": event,
                "job_id": self.id,
                "kind": self.kind,
                "status": self.status,
                "ts_ms": now_local_ms(),
                "data": data or {},
            }
        )


class JobRegistry:
    """Small thread-safe registry for analysis and follow-up jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, WebJob] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, *, cancel_token: Any = None) -> WebJob:
        job = WebJob(id=uuid.uuid4().hex, kind=kind, cancel_token=cancel_token)
        with self._lock:
            self._jobs[job.id] = job
        job.emit("created")
        return job

    def get(self, job_id: str) -> WebJob | None:
        with self._lock:
            return self._jobs.get(job_id)


def encode_sse(payload: dict[str, Any]) -> str:
    event = str(payload.get("event") or "message")
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


def event_stream(job: WebJob, *, timeout: float = 0.25) -> Iterator[str]:
    """Yield queued job events until the job reaches a terminal status."""

    while True:
        try:
            payload = job.events.get(timeout=timeout)
            yield encode_sse(payload)
        except queue.Empty:
            if job.status in TERMINAL_STATUSES:
                yield encode_sse(
                    {
                        "event": "terminal",
                        "job_id": job.id,
                        "kind": job.kind,
                        "status": job.status,
                        "ts_ms": now_local_ms(),
                        "data": {"error": job.error} if job.error else {},
                    }
                )
                return
            yield ": heartbeat\n\n"
