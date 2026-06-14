from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pa_agent.app_context import AppContext
from pa_agent.config.settings import Settings, save_settings
from pa_agent.records.schema import AnalysisRecord, RecordMeta
from pa_agent.web.app import create_app
from tests.fixtures.kline_bars import make_newest_first_bars


class FakeSource:
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def subscribe(self, symbol: str, timeframe: str) -> None:
        self.symbol = symbol
        self.timeframe = timeframe

    def latest_snapshot(self, n: int):
        return make_newest_first_bars(max(n, 25), with_forming=False)


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings()
    settings.general.last_symbol = "XAUUSD"
    settings.general.last_timeframe = "1h"
    settings.general.analysis_bar_count = 20
    settings_path = tmp_path / "settings.json"
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    save_settings(settings, settings_path)
    ctx = AppContext(settings=settings, data_source=FakeSource())
    app = create_app(ctx, settings_path=settings_path, records_dir=records_dir)
    app.state.test_records_dir = records_dir
    return TestClient(app)


def test_health_settings_sources_and_snapshot(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    assert client.get("/api/health").json()["ok"] is True

    settings = client.get("/api/settings").json()
    assert settings["general"]["last_symbol"] == "XAUUSD"
    assert settings["provider"]["api_key"] == ""

    updated = client.put(
        "/api/settings",
        json={"general": {"decision_confidence_threshold": 75}},
    ).json()
    assert updated["general"]["decision_confidence_threshold"] == 75

    sources = client.get("/api/sources").json()
    assert {"id": "mt5", "label": "MT5"} in sources["choices"]

    subscribed = client.post(
        "/api/source/subscribe",
        json={"data_source": "mt5", "symbol": "XAUUSD", "timeframe": "1h"},
    ).json()
    assert subscribed["ok"] is True

    snapshot = client.get("/api/market/snapshot?bar_count=20").json()
    assert snapshot["ok"] is True
    assert len(snapshot["frame"]["bars"]) == 20


def test_analysis_job_sse_and_cancel_shape(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    created = client.post("/api/analysis", json={"bar_count": 20}).json()
    assert created["job_id"]
    assert created["events_url"].endswith("/events")

    cancelled = client.post(f"/api/analysis/{created['job_id']}/cancel").json()
    assert cancelled["ok"] is True

    with client.stream("GET", created["events_url"]) as response:
        assert response.status_code == 200
        text = ""
        for chunk in response.iter_text():
            text += chunk
            if "event: terminal" in text:
                break

    assert "event:" in text
    assert created["job_id"] in text


def test_records_and_followup_endpoints(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    records_dir = client.app.state.test_records_dir
    record = AnalysisRecord(
        meta=RecordMeta(
            timestamp_local_iso="2026-01-01T00:00:00.000",
            timestamp_local_ms=1767225600000,
            symbol="XAUUSD",
            timeframe="1h",
            bar_count=20,
            ai_provider={"model": "test"},
        ),
        kline_data=[],
        htf_text="",
        stage1_messages=[],
        stage1_response=None,
        stage1_diagnosis={"gate_result": "proceed"},
        stage2_messages=[],
        stage2_response=None,
        stage2_decision={"decision": {"order_type": "不下单"}},
        strategy_files_used=[],
        experience_loaded=[],
        exception=None,
        usage_total={},
        effective_decision={"decision": {"order_type": "不下单"}},
    )
    record_id = "2026-01-01_00-00-00_XAUUSD_1h"
    (records_dir / f"{record_id}.json").write_text(
        record.model_dump_json(),
        encoding="utf-8",
    )

    records = client.get("/api/records").json()["records"]
    assert records[0]["id"] == record_id

    detail = client.get(f"/api/records/{record_id}").json()
    assert detail["effective_decision"]["decision"]["order_type"] == "不下单"

    created = client.post(
        "/api/followup",
        json={"record_id": record_id, "message": "What changed?"},
    ).json()
    assert created["job_id"]

    with client.stream("GET", created["events_url"]) as response:
        text = ""
        for chunk in response.iter_text():
            text += chunk
            if "event: terminal" in text:
                break

    assert "followup" in text
