"""Aion-style run harness for two-stage analysis.

The harness is deliberately deterministic.  It records the immutable analysis
contract, appends audit events, and derives the decision that the UI is allowed
to act on after the pre-delivery gate has checked the raw Stage 2 output.
"""

from __future__ import annotations

import copy
import dataclasses
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pa_agent.data.base import KlineFrame
from pa_agent.util.timefmt import now_local_ms

TRADE_ORDER_TYPES: frozenset[str] = frozenset({"限价单", "突破单", "市价单"})


class AnalysisContract(BaseModel):
    """Immutable facts that define exactly what an analysis run may use."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    symbol: str
    timeframe: str
    data_source: str
    bar_count: int
    timezone: str
    allowed_kline_range: dict[str, int]
    latest_closed_bar_ts_open: float | None
    validation_profile: dict[str, Any]
    prompt_strategy_scope: dict[str, Any]
    decision_stance: str


class HarnessEvent(BaseModel):
    """One append-only audit event in a run trace."""

    model_config = ConfigDict(extra="forbid")

    ts_ms: int
    run_id: str
    kind: str
    stage: str
    status: str
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class PreDeliveryGateResult(BaseModel):
    """Result of the deterministic gate between validation and persistence."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["allow", "blocked_trade", "failed"]
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.status == "allow"


def build_analysis_contract(
    frame: KlineFrame,
    settings: Any | None,
    *,
    run_id: str | None = None,
) -> AnalysisContract:
    """Build the run contract from the closed K-line frame and settings."""

    tz = datetime.now().astimezone().tzinfo
    general = getattr(settings, "general", None)
    validation = getattr(settings, "validation", None)
    prompt = getattr(settings, "prompt", None)

    latest_ts = frame.bars[0].ts_open if frame.bars else None
    validation_profile = validation.model_dump() if hasattr(validation, "model_dump") else {}
    prompt_strategy_scope = prompt.model_dump() if hasattr(prompt, "model_dump") else {}
    if general is not None:
        prompt_strategy_scope["analysis_mode"] = getattr(general, "analysis_mode", "original")

    return AnalysisContract(
        run_id=run_id or uuid.uuid4().hex,
        symbol=frame.symbol,
        timeframe=frame.timeframe,
        data_source=str(getattr(general, "last_data_source", "unknown") or "unknown"),
        bar_count=len(frame.bars),
        timezone=str(tz) if tz is not None else "local",
        allowed_kline_range={"min_seq": 1, "max_seq": len(frame.bars)},
        latest_closed_bar_ts_open=latest_ts,
        validation_profile=validation_profile,
        prompt_strategy_scope=prompt_strategy_scope,
        decision_stance=str(getattr(general, "decision_stance", "conservative") or "conservative"),
    )


def make_harness_event(
    *,
    run_id: str,
    kind: str,
    stage: str,
    status: str,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> HarnessEvent:
    return HarnessEvent(
        ts_ms=now_local_ms(),
        run_id=run_id,
        kind=kind,
        stage=stage,
        status=status,
        message=message,
        data=data or {},
    )


def append_harness_event(
    trace: list[dict[str, Any]],
    *,
    run_id: str,
    kind: str,
    stage: str,
    status: str,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a validated event dict and return it for streaming/logging."""

    event = make_harness_event(
        run_id=run_id,
        kind=kind,
        stage=stage,
        status=status,
        message=message,
        data=data,
    ).model_dump()
    trace.append(event)
    return event


def is_trade_decision(stage2_decision: dict[str, Any] | None) -> bool:
    decision = _decision_inner(stage2_decision)
    return str(decision.get("order_type") or "") in TRADE_ORDER_TYPES


def derive_effective_decision(
    stage2_decision: dict[str, Any] | None,
    gate_result: PreDeliveryGateResult,
) -> dict[str, Any] | None:
    """Return the decision payload that downstream UI/alerts may act on."""

    if not isinstance(stage2_decision, dict):
        return None
    if gate_result.allowed:
        effective = copy.deepcopy(stage2_decision)
        effective.setdefault("pre_delivery_gate_status", gate_result.status)
        return effective

    effective = copy.deepcopy(stage2_decision)
    raw_decision = _decision_inner(stage2_decision)
    reason = "; ".join(gate_result.blockers) or "Pre-delivery gate blocked the order."
    effective["decision"] = {
        "order_direction": None,
        "order_type": "不下单",
        "entry_price": None,
        "take_profit_price": None,
        "stop_loss_price": None,
        "entry_basis_bar": None,
        "entry_basis_extreme": None,
        "entry_rule": None,
        "reasoning": f"Pre-delivery gate blocked the raw trade decision: {reason}",
        "diagnosis_confidence": raw_decision.get("diagnosis_confidence"),
        "diagnosis_confidence_reasoning": raw_decision.get("diagnosis_confidence_reasoning", ""),
        "trade_confidence": 0,
        "trade_confidence_reasoning": reason,
        "estimated_win_rate": None,
        "estimated_win_rate_reasoning": "Gate-blocked decision; no executable order.",
        "key_factors": raw_decision.get("key_factors") or [],
        "watch_points": raw_decision.get("watch_points") or [],
        "risk_assessment": "gate_blocked",
        "invalidation_condition": None,
    }
    effective["terminal"] = {
        "node_id": "pre_delivery_gate",
        "outcome": "wait",
        "label": "Trade blocked by deterministic pre-delivery gate.",
    }
    effective["gate_blocked"] = True
    effective["pre_delivery_gate_status"] = gate_result.status
    effective["pre_delivery_gate_blockers"] = list(gate_result.blockers)
    return effective


def run_pre_delivery_gate(
    *,
    stage2_decision: dict[str, Any] | None,
    frame: KlineFrame,
    settings: Any | None = None,
) -> PreDeliveryGateResult:
    """Validate the raw Stage 2 decision before any UI alert or order overlay."""

    blockers: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {
        "bar_count": len(frame.bars),
        "allowed_kline_range": {"min_seq": 1, "max_seq": len(frame.bars)},
    }

    if not isinstance(stage2_decision, dict):
        return PreDeliveryGateResult(
            status="failed",
            blockers=["Stage 2 decision is missing or is not an object."],
            evidence=evidence,
        )

    decision = _decision_inner(stage2_decision)
    if not decision:
        return PreDeliveryGateResult(
            status="failed",
            blockers=["Stage 2 decision.decision is missing or is not an object."],
            evidence=evidence,
        )

    order_type = str(decision.get("order_type") or "")
    trade = order_type in TRADE_ORDER_TYPES
    evidence["order_type"] = order_type
    evidence["is_trade"] = trade

    unclosed = [
        getattr(b, "seq", i + 1) for i, b in enumerate(frame.bars) if not getattr(b, "closed", True)
    ]
    forming = [
        getattr(b, "seq", i + 1)
        for i, b in enumerate(frame.bars)
        if int(getattr(b, "seq", i + 1) or 0) <= 0
        or (i == 0 and not getattr(b, "closed", True) and int(getattr(b, "seq", 1) or 1) == 0)
    ]
    evidence["unclosed_frame_bars"] = unclosed
    evidence["forming_frame_bars"] = forming
    if forming:
        blockers.append(f"Analysis frame contains unclosed/forming bars: {forming}.")

    cited = sorted(_extract_kline_refs(stage2_decision))
    evidence["cited_k_lines"] = cited
    out_of_range = [k for k in cited if k < 1 or k > len(frame.bars)]
    if out_of_range:
        blockers.append(
            "Stage 2 references K-lines outside the submitted frame: "
            f"{out_of_range}; allowed K1-K{len(frame.bars)}."
        )

    terminal = stage2_decision.get("terminal") if isinstance(stage2_decision, dict) else {}
    terminal_outcome = str(terminal.get("outcome") or "") if isinstance(terminal, dict) else ""
    evidence["terminal_outcome"] = terminal_outcome

    if trade:
        _check_trade_trace(stage2_decision, blockers, evidence)
        _check_trade_prices(decision, blockers, evidence)
        _check_order_terminal_consistency(decision, terminal, blockers, evidence)
        _check_trade_confidence(decision, settings, blockers, evidence)
        _check_trade_critic(stage2_decision, settings, blockers, warnings, evidence)
    elif terminal_outcome == "trade":
        blockers.append("Terminal outcome is trade but decision.order_type is not executable.")

    if blockers:
        return PreDeliveryGateResult(
            status="blocked_trade" if trade else "failed",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )
    return PreDeliveryGateResult(status="allow", warnings=warnings, evidence=evidence)


def _decision_inner(stage2_decision: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(stage2_decision, dict):
        return {}
    decision = stage2_decision.get("decision")
    return decision if isinstance(decision, dict) else {}


def _extract_kline_refs(payload: Any) -> set[int]:
    refs: set[int] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for match in re.finditer(r"\bK\s*(\d+)\b", value, flags=re.IGNORECASE):
                refs.add(int(match.group(1)))
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            walk(dataclasses.asdict(value))

    walk(payload)
    return refs


def _trace_node_ids(stage2_decision: dict[str, Any]) -> set[str]:
    trace = stage2_decision.get("decision_trace")
    if not isinstance(trace, list):
        return set()
    node_ids: set[str] = set()
    for node in trace:
        if not isinstance(node, dict):
            continue
        raw = node.get("node_id")
        if raw is not None:
            node_ids.add(str(raw).strip())
    return node_ids


def _check_trade_trace(
    stage2_decision: dict[str, Any],
    blockers: list[str],
    evidence: dict[str, Any],
) -> None:
    node_ids = _trace_node_ids(stage2_decision)
    evidence["decision_trace_node_ids"] = sorted(node_ids)
    if not any(node_id == "9" or node_id.startswith("9.") for node_id in node_ids):
        blockers.append("Executable trade is missing a §9 signal-bar trace node.")
    for required in ("10.1", "10.2", "10.3"):
        if required not in node_ids:
            blockers.append(f"Executable trade is missing required §{required} trace node.")


def _parse_positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _check_trade_prices(
    decision: dict[str, Any],
    blockers: list[str],
    evidence: dict[str, Any],
) -> None:
    parsed = {
        "entry_price": _parse_positive_float(decision.get("entry_price")),
        "stop_loss_price": _parse_positive_float(decision.get("stop_loss_price")),
        "take_profit_price": _parse_positive_float(decision.get("take_profit_price")),
    }
    evidence["order_prices"] = parsed
    missing = [key for key, value in parsed.items() if value is None]
    if missing:
        blockers.append(f"Executable trade is missing numeric order price fields: {missing}.")
        return

    direction = str(decision.get("order_direction") or "").lower()
    entry = parsed["entry_price"]
    stop = parsed["stop_loss_price"]
    target = parsed["take_profit_price"]
    assert entry is not None and stop is not None and target is not None
    if "空" in direction or "short" in direction:
        if not (target < entry < stop):
            blockers.append("Short order prices are inconsistent; expected target < entry < stop.")
    else:
        if not (stop < entry < target):
            blockers.append("Long order prices are inconsistent; expected stop < entry < target.")


def _check_order_terminal_consistency(
    decision: dict[str, Any],
    terminal: Any,
    blockers: list[str],
    evidence: dict[str, Any],
) -> None:
    direction = str(decision.get("order_direction") or "").strip()
    if not direction:
        blockers.append("Executable trade is missing order_direction.")

    if not isinstance(terminal, dict):
        blockers.append("Executable trade is missing terminal object.")
        return
    if str(terminal.get("outcome") or "") != "trade":
        blockers.append("Executable trade requires terminal.outcome='trade'.")
    if not str(terminal.get("node_id") or "").strip():
        blockers.append("Executable trade terminal is missing node_id.")
    evidence["terminal"] = {
        "node_id": terminal.get("node_id"),
        "outcome": terminal.get("outcome"),
        "label": terminal.get("label"),
    }


def _check_trade_confidence(
    decision: dict[str, Any],
    settings: Any | None,
    blockers: list[str],
    evidence: dict[str, Any],
) -> None:
    general = getattr(settings, "general", None)
    threshold = int(getattr(general, "decision_confidence_threshold", 0) or 0)
    confidence = _parse_positive_float(decision.get("trade_confidence"))
    evidence["trade_confidence"] = confidence
    evidence["trade_confidence_threshold"] = threshold
    if threshold > 0 and (confidence is None or confidence < threshold):
        blockers.append(
            "Executable trade confidence is below threshold: "
            f"{confidence if confidence is not None else 'missing'} < {threshold}."
        )


def _check_trade_critic(
    stage2_decision: dict[str, Any],
    settings: Any | None,
    blockers: list[str],
    warnings: list[str],
    evidence: dict[str, Any],
) -> None:
    validation = getattr(settings, "validation", None)
    enabled = bool(getattr(validation, "trade_critic_enabled", False))
    evidence["trade_critic_enabled"] = enabled
    if not enabled:
        return

    # The critic is intentionally opt-in and read-only.  No critic client is
    # wired into the orchestrator yet, so enabling the flag without one must
    # block the effective trade rather than silently approving it.
    evidence["trade_critic"] = {
        "verdict": "rollback",
        "reasons": ["Trade critic is enabled but no critic service is configured."],
        "blocker_evidence": {"decision_keys": sorted(stage2_decision.keys())},
    }
    blockers.append("Trade critic is enabled but no critic service is configured.")
