from __future__ import annotations

import copy

from pa_agent.config.settings import Settings
from pa_agent.data.base import KlineBar
from pa_agent.orchestrator.harness import (
    append_harness_event,
    build_analysis_contract,
    derive_effective_decision,
    run_pre_delivery_gate,
)
from pa_agent.records.schema import AnalysisRecord
from tests.fixtures.ai_payloads import VALID_STAGE2_ORDER
from tests.integration.conftest import make_frame


def test_analysis_contract_captures_frame_and_settings() -> None:
    settings = Settings()
    settings.general.last_data_source = "tradingview"
    settings.general.decision_stance = "balanced"
    frame = make_frame()

    contract = build_analysis_contract(frame, settings, run_id="run-1")

    assert contract.run_id == "run-1"
    assert contract.symbol == frame.symbol
    assert contract.timeframe == frame.timeframe
    assert contract.data_source == "tradingview"
    assert contract.allowed_kline_range == {"min_seq": 1, "max_seq": len(frame.bars)}
    assert contract.latest_closed_bar_ts_open == frame.bars[0].ts_open
    assert contract.validation_profile["trade_critic_enabled"] is False
    assert contract.decision_stance == "balanced"


def test_harness_trace_append_is_ordered_and_validated() -> None:
    trace: list[dict] = []

    first = append_harness_event(
        trace,
        run_id="run-1",
        kind="preflight",
        stage="preflight",
        status="started",
    )
    second = append_harness_event(
        trace,
        run_id="run-1",
        kind="validation",
        stage="stage2",
        status="passed",
    )

    assert trace == [first, second]
    assert trace[0]["kind"] == "preflight"
    assert trace[1]["stage"] == "stage2"


def test_pre_delivery_gate_allows_valid_trade() -> None:
    settings = Settings()
    settings.general.decision_confidence_threshold = 60

    gate = run_pre_delivery_gate(
        stage2_decision=copy.deepcopy(VALID_STAGE2_ORDER),
        frame=make_frame(),
        settings=settings,
    )

    assert gate.status == "allow"
    assert gate.blockers == []
    assert gate.evidence["trade_confidence"] == 70.0
    assert "10.3" in gate.evidence["decision_trace_node_ids"]


def test_pre_delivery_gate_blocks_out_of_range_kline_reference() -> None:
    payload = copy.deepcopy(VALID_STAGE2_ORDER)
    payload["decision"]["reasoning"] = "Use K999 as confirmation."

    gate = run_pre_delivery_gate(stage2_decision=payload, frame=make_frame(), settings=Settings())

    assert gate.status == "blocked_trade"
    assert any("outside the submitted frame" in blocker for blocker in gate.blockers)


def test_pre_delivery_gate_blocks_missing_required_trade_trace_nodes() -> None:
    payload = copy.deepcopy(VALID_STAGE2_ORDER)
    payload["decision_trace"] = [
        node for node in payload["decision_trace"] if node["node_id"] != "10.3"
    ]

    gate = run_pre_delivery_gate(stage2_decision=payload, frame=make_frame(), settings=Settings())

    assert gate.status == "blocked_trade"
    assert any("10.3" in blocker for blocker in gate.blockers)


def test_pre_delivery_gate_blocks_forming_k0_bar() -> None:
    frame = make_frame()
    bars = list(frame.bars)
    bars[0] = KlineBar(
        seq=0,
        ts_open=bars[0].ts_open,
        open=bars[0].open,
        high=bars[0].high,
        low=bars[0].low,
        close=bars[0].close,
        volume=bars[0].volume,
        closed=False,
    )
    frame = dataclass_replace_frame(frame, tuple(bars))

    gate = run_pre_delivery_gate(
        stage2_decision=copy.deepcopy(VALID_STAGE2_ORDER),
        frame=frame,
        settings=Settings(),
    )

    assert gate.status == "blocked_trade"
    assert any("unclosed/forming" in blocker for blocker in gate.blockers)


def test_effective_decision_replaces_blocked_trade_with_no_order() -> None:
    settings = Settings()
    settings.general.decision_confidence_threshold = 80
    raw = copy.deepcopy(VALID_STAGE2_ORDER)
    gate = run_pre_delivery_gate(stage2_decision=raw, frame=make_frame(), settings=settings)

    effective = derive_effective_decision(raw, gate)

    assert gate.status == "blocked_trade"
    assert raw["decision"]["order_type"] == "突破单"
    assert effective is not None
    assert effective["decision"]["order_type"] == "不下单"
    assert effective["decision"]["entry_price"] is None
    assert effective["gate_blocked"] is True


def test_analysis_record_accepts_legacy_payload_without_harness_fields() -> None:
    payload = {
        "meta": {
            "timestamp_local_iso": "2026-01-01T00:00:00.000",
            "timestamp_local_ms": 1767225600000,
            "symbol": "XAUUSD",
            "timeframe": "1h",
            "bar_count": 20,
            "ai_provider": {"model": "m"},
        },
        "kline_data": [],
        "htf_text": "",
        "stage1_messages": [],
        "stage1_response": None,
        "stage1_diagnosis": None,
        "stage2_messages": [],
        "stage2_response": None,
        "stage2_decision": None,
        "strategy_files_used": [],
        "experience_loaded": [],
        "exception": None,
        "usage_total": {},
    }

    record = AnalysisRecord.model_validate(payload)

    assert record.analysis_contract is None
    assert record.harness_trace == []
    assert record.pre_delivery_gate is None
    assert record.effective_decision is None


def dataclass_replace_frame(frame, bars):
    from dataclasses import replace

    return replace(frame, bars=bars)
