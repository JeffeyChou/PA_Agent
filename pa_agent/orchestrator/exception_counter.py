"""Persistent consecutive-exception counter for the orchestrator.

Tracks how many consecutive JSON-validation failures have occurred across
multiple analysis submissions.  The state is persisted to
``config/exception_state.json`` so that a program restart does not reset
the streak.

Design references: §B.8, §B.14, R8.3–R8.9, C10.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pa_agent.config.paths import EXCEPTION_STATE_JSON_PATH
from pa_agent.util.timefmt import now_local_ms

if TYPE_CHECKING:
    from pa_agent.ai.json_validator import ValidationError

logger = logging.getLogger(__name__)

# Maximum number of history entries kept on disk (design §B.8).
_MAX_HISTORY = 50


# ── Persisted state ───────────────────────────────────────────────────────────

@dataclass
class ExceptionState:
    """In-memory representation of ``exception_state.json``."""

    consecutive_count: int = 0
    last_error_category: Optional[str] = None
    last_error_at_ms: Optional[int] = None
    history: list[dict[str, Any]] = field(default_factory=list)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "consecutive_count": self.consecutive_count,
            "last_error_category": self.last_error_category,
            "last_error_at_ms": self.last_error_at_ms,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExceptionState":
        return cls(
            consecutive_count=int(data.get("consecutive_count", 0)),
            last_error_category=data.get("last_error_category"),
            last_error_at_ms=data.get("last_error_at_ms"),
            history=list(data.get("history", [])),
        )

    @classmethod
    def zero(cls) -> "ExceptionState":
        """Return a fresh zero-state (used when the file is absent)."""
        return cls()


# ── AlarmPayload ──────────────────────────────────────────────────────────────

@dataclass
class AlarmPayload:
    """Payload emitted to the event bus when a validation alarm fires.

    Matches the shape described in design §B.8 and R8.6.
    """

    category: str                       # 'a' .. 'e'
    stage: str                          # '阶段一-诊断' | '阶段二-决策'
    timestamp_local_iso: str
    raw_text: str
    parse_position: Optional[str]       # "line:col" or None
    missing_fields: list[str]
    invalid_fields: list[dict[str, Any]]
    consecutive_count: int
    history_excerpt: list[dict[str, Any]]  # most-recent N entries
    is_streak: bool                     # True when consecutive_count >= 2


# ── ExceptionCounter ──────────────────────────────────────────────────────────

class ExceptionCounter:
    """Persistent, cross-submission consecutive JSON-exception counter.

    Usage::

        counter = ExceptionCounter(event_bus=bus)
        counter.load()

        # After a validation failure:
        counter.on_validation_error("stage1", validation_error)

        # After a full round-trip success:
        counter.on_round_trip_success()

    The counter persists its state to ``state_path`` after every mutation so
    that a program restart does not lose the streak.

    Parameters
    ----------
    state_path:
        Path to the JSON file used for persistence.  Defaults to
        ``paths.EXCEPTION_STATE_JSON_PATH``.
    event_bus:
        Optional event bus.  When provided, ``raise_alarm`` will call
        ``event_bus.emit("exception", payload)``.  When *None* the alarm is
        only logged.
    """

    def __init__(
        self,
        state_path: Path = EXCEPTION_STATE_JSON_PATH,
        event_bus: Any = None,
    ) -> None:
        self._state_path = state_path
        self._event_bus = event_bus
        self._state: ExceptionState = ExceptionState.zero()

    # ── Persistence ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load state from disk.  If the file is absent, use zero-state."""
        if not self._state_path.exists():
            logger.debug(
                "exception_state.json not found at %s; starting with zero state",
                self._state_path,
            )
            self._state = ExceptionState.zero()
            return

        try:
            raw = self._state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._state = ExceptionState.from_dict(data)
            logger.debug(
                "Loaded exception state: consecutive_count=%d",
                self._state.consecutive_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load exception state from %s (%s); using zero state",
                self._state_path,
                exc,
            )
            self._state = ExceptionState.zero()

    def save(self) -> None:
        """Persist current state to disk.  Errors are logged, not raised."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to save exception state: %s", exc)

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def consecutive_count(self) -> int:
        """Current consecutive failure count (read-only view)."""
        return self._state.consecutive_count

    @property
    def last_error_category(self) -> Optional[str]:
        return self._state.last_error_category

    @property
    def last_error_at_ms(self) -> Optional[int]:
        return self._state.last_error_at_ms

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_validation_error(self, stage: str, err: "ValidationError") -> None:
        """Increment the streak counter and persist.

        Called by the orchestrator whenever ``JsonValidator.validate`` returns
        a ``ValidationError`` (categories a–d).

        Parameters
        ----------
        stage:
            Human-readable stage label, e.g. ``"stage1"`` or ``"stage2"``.
        err:
            The ``ValidationError`` returned by ``JsonValidator``.
        """
        self._state.consecutive_count += 1
        self._state.last_error_category = err.category
        self._state.last_error_at_ms = now_local_ms()
        self._push_history(stage, err)
        self.save()

        # Fire alarm for every validation error (design §B.8).
        is_streak = self._state.consecutive_count >= 2
        self.raise_alarm(stage, err, self._state, is_streak)

    def on_round_trip_success(self) -> None:
        """Reset the streak counter to 0 and persist.

        Must be called **only** when both Stage 1 and Stage 2 pass validation
        in the same submission (design §B.8, R8.4, C10).
        History is preserved for post-mortem review.
        """
        self._state.consecutive_count = 0
        # last_error_category / last_error_at_ms intentionally kept for audit.
        self.save()
        logger.debug("ExceptionCounter reset to 0 after successful round-trip")

    def on_user_cancel(self, reason: str) -> None:
        """Record a cancellation in history without touching the streak.

        User-initiated cancellations (symbol switch, stop button) must NOT
        increment ``consecutive_count`` (R8.8, C7).
        """
        entry: dict[str, Any] = {
            "ts_ms": now_local_ms(),
            "stage": "cancelled",
            "category": "cancel",
            "reason": reason,
            "raw_excerpt": "",
        }
        self._append_history(entry)
        self.save()
        logger.debug("ExceptionCounter: user cancel recorded (%s)", reason)

    def on_network_error(self, err: Exception) -> None:
        """Record a network/timeout error in history without touching the streak.

        Infrastructure errors must NOT increment ``consecutive_count``
        (R8.9, design §B.14).
        """
        entry: dict[str, Any] = {
            "ts_ms": now_local_ms(),
            "stage": "network",
            "category": "network",
            "raw_excerpt": str(err)[:200],
        }
        self._append_history(entry)
        self.save()
        logger.debug("ExceptionCounter: network error recorded (%s)", err)

    def reset_streak(self) -> None:
        """Manually reset the streak (Tab3 'clear' button, R8.7).

        This is the only user-facing reset path outside of a successful
        round-trip.  It is logged for audit purposes.
        """
        old = self._state.consecutive_count
        self._state.consecutive_count = 0
        self.save()
        logger.info(
            "ExceptionCounter streak manually cleared (was %d)", old
        )

    # ── Alarm ─────────────────────────────────────────────────────────────────

    def raise_alarm(
        self,
        stage: str,
        err: "ValidationError",
        state: ExceptionState,
        is_streak: bool,
    ) -> None:
        """Build an ``AlarmPayload`` and emit it on the event bus.

        If no event bus is configured the alarm is only written to the log.

        Parameters
        ----------
        stage:
            Stage label (``"stage1"`` / ``"stage2"``).
        err:
            The ``ValidationError`` that triggered the alarm.
        state:
            Current ``ExceptionState`` snapshot.
        is_streak:
            ``True`` when ``consecutive_count >= 2``.
        """
        from datetime import datetime, timezone

        # Human-readable stage label (design §B.8).
        stage_label = "阶段一-诊断" if "stage1" in stage else "阶段二-决策"

        # Local ISO timestamp.
        ts_ms = state.last_error_at_ms or now_local_ms()
        ts_iso = datetime.fromtimestamp(ts_ms / 1000).isoformat(timespec="seconds")

        # Build invalid_fields list in the shape expected by the UI.
        invalid_fields: list[dict[str, Any]] = []
        for f in err.invalid_fields:
            allowed = err.allowed_values.get(f, [])
            invalid_fields.append({"field": f, "allowed": allowed})

        payload = AlarmPayload(
            category=err.category if not is_streak else "e",
            stage=stage_label,
            timestamp_local_iso=ts_iso,
            raw_text=err.raw_text,
            parse_position=err.parse_position,
            missing_fields=list(err.missing_fields),
            invalid_fields=invalid_fields,
            consecutive_count=state.consecutive_count,
            history_excerpt=list(state.history[-10:]),  # last 10 entries
            is_streak=is_streak,
        )

        logger.warning(
            "Validation alarm: category=%s stage=%s streak=%d is_streak=%s",
            payload.category,
            stage_label,
            state.consecutive_count,
            is_streak,
        )

        if self._event_bus is not None:
            try:
                self._event_bus.emit_exception(payload)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to emit exception alarm: %s", exc)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _push_history(self, stage: str, err: "ValidationError") -> None:
        """Append a validation-error entry to the rolling history."""
        entry: dict[str, Any] = {
            "ts_ms": self._state.last_error_at_ms,
            "stage": stage,
            "category": err.category,
            "raw_excerpt": err.raw_text[:200] if err.raw_text else "",
            "missing_fields": list(err.missing_fields),
            "invalid_fields": list(err.invalid_fields),
        }
        self._append_history(entry)

    def _append_history(self, entry: dict[str, Any]) -> None:
        """Append *entry* to history, capping at ``_MAX_HISTORY`` entries."""
        self._state.history.append(entry)
        if len(self._state.history) > _MAX_HISTORY:
            # Drop oldest entries to stay within the cap.
            self._state.history = self._state.history[-_MAX_HISTORY:]
