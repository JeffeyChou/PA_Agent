"""Main application window for PA Agent."""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt

from pa_agent.app_context import AppContext

logger = logging.getLogger(__name__)

# Zombie timeout in milliseconds (5 seconds)
_WORKER_JOIN_TIMEOUT_MS = 5000


# ── AI Worker ─────────────────────────────────────────────────────────────────

class _AnalysisWorker(QThread):
    """Runs TwoStageOrchestrator.submit() on a background thread.

    Signals
    -------
    finished(dict):
        Emitted with the stage2_decision dict on success (or empty dict on
        failure / cancellation).
    status_update(str):
        Emitted with human-readable progress text.
    """

    finished = pyqtSignal(dict)
    record_ready = pyqtSignal(object)   # emits the full AnalysisRecord
    status_update = pyqtSignal(str)

    def __init__(
        self,
        orchestrator: Any,
        frame: Any,
        htf_text: str,
        cancel_token: Any,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._orchestrator = orchestrator
        self._frame = frame
        self._htf_text = htf_text
        self._cancel_token = cancel_token

    def run(self) -> None:
        from pa_agent.util.threading import OrchestratorEvent

        _EVENT_LABELS = {
            OrchestratorEvent.Stage1Started: "阶段一分析中…",
            OrchestratorEvent.Stage1Done: "阶段一完成",
            OrchestratorEvent.Stage2Started: "阶段二分析中…",
            OrchestratorEvent.Stage2Done: "阶段二完成",
            OrchestratorEvent.RecordSaved: "记录已保存",
            OrchestratorEvent.Cancelled: "已取消",
            OrchestratorEvent.Stage1Failed: "阶段一失败",
            OrchestratorEvent.Stage2Failed: "阶段二失败",
        }

        def on_event(event: OrchestratorEvent) -> None:
            label = _EVENT_LABELS.get(event, str(event))
            self.status_update.emit(label)

        try:
            record = self._orchestrator.submit(
                self._frame,
                self._htf_text,
                self._cancel_token,
                on_event,
            )
            decision = record.stage2_decision or {}
        except Exception as exc:  # noqa: BLE001
            logger.error("Analysis worker error: %s", exc, exc_info=True)
            decision = {}
            record = None  # type: ignore[assignment]

        if record is not None:
            self.record_ready.emit(record)
        self.finished.emit(decision)


# ── MainWindow ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Top-level window with a three-tab layout and a status bar.

    Tabs
    ----
    0 — 主页    (home / chart + analysis)
    1 — 对话页  (conversation / free-chat)
    2 — 调试页  (debug / raw AI output)
    """

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PA Agent")
        self.resize(1280, 800)
        self._ctx = ctx
        self._worker: _AnalysisWorker | None = None
        self._cancel_token: Any = None
        self._analysis_in_progress = False
        self._switching = False
        self._free_chat_session: Any = None
        # RefreshLoop runs in its own QThread
        self._refresh_loop: Any = None
        self._refresh_thread: QThread | None = None
        self._setup_ui()
        self._connect_event_bus()
        self._start_refresh_loop()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        # ── Tab widget ────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._home_tab = self._build_home_tab()

        # ── Tab 2: Conversation ───────────────────────────────────────────────
        from pa_agent.gui.conversation_widget import ConversationWidget
        self._conversation_widget = ConversationWidget()
        self._chat_tab = self._conversation_widget

        # ── Tab 3: Debug ──────────────────────────────────────────────────────
        from pa_agent.gui.debug_widget import DebugWidget
        _api_key = ""
        _exc_counter = getattr(self._ctx, "exc_counter", None)
        _settings = getattr(self._ctx, "settings", None)
        if _settings is not None:
            _api_key = getattr(_settings.provider, "api_key", "") or ""
        self._debug_widget = DebugWidget(api_key=_api_key, exc_counter=_exc_counter)
        self._debug_tab = self._debug_widget

        self._tabs.addTab(self._home_tab, "主页")
        self._tabs.addTab(self._chat_tab, "对话页")
        self._tabs.addTab(self._debug_tab, "调试页")

        self.setCentralWidget(self._tabs)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪")

        # ── Menu bar ──────────────────────────────────────────────────────────
        menu_bar: QMenuBar = self.menuBar()  # type: ignore[assignment]
        settings_menu = menu_bar.addMenu("设置")

        open_settings_action = QAction("打开设置…", self)
        open_settings_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(open_settings_action)

    def _build_home_tab(self) -> QWidget:
        """Build and return the home tab widget."""
        from pa_agent.gui.chart_widget import ChartWidget
        from pa_agent.gui.decision_panel import DecisionPanel

        tab = QWidget()
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)

        # ── Control bar ───────────────────────────────────────────────────────
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        # Symbol — editable combo (user can type any MT5 symbol)
        ctrl_layout.addWidget(QLabel("品种:"))
        self._symbol_combo = QComboBox()
        self._symbol_combo.setEditable(True)
        self._symbol_combo.addItems(["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAGUSD"])
        # Restore last-used symbol from settings
        _last_symbol = "XAUUSD"
        _last_tf = "1h"
        _settings = getattr(self._ctx, "settings", None)
        if _settings is not None:
            _last_symbol = getattr(_settings.general, "last_symbol", "XAUUSD") or "XAUUSD"
            _last_tf = getattr(_settings.general, "last_timeframe", "1h") or "1h"
        self._symbol_combo.setCurrentText(_last_symbol)
        self._symbol_combo.setMinimumWidth(110)
        self._symbol_combo.lineEdit().setPlaceholderText("输入品种名…")
        ctrl_layout.addWidget(self._symbol_combo)

        # Timeframe
        ctrl_layout.addWidget(QLabel("周期:"))
        self._tf_combo = QComboBox()
        self._tf_combo.addItems(["1m", "5m", "15m", "1h", "4h", "1d"])
        self._tf_combo.setCurrentText(_last_tf)
        self._tf_combo.setMinimumWidth(60)
        ctrl_layout.addWidget(self._tf_combo)
        # Bar count
        ctrl_layout.addWidget(QLabel("K线数:"))
        self._bar_count_spin = QSpinBox()
        self._bar_count_spin.setRange(2, 5000)
        self._bar_count_spin.setValue(200)
        self._bar_count_spin.setMinimumWidth(70)
        ctrl_layout.addWidget(self._bar_count_spin)

        ctrl_layout.addStretch()

        # Submit button
        self._submit_btn = QPushButton("提交分析")
        self._submit_btn.setMinimumWidth(100)
        self._submit_btn.clicked.connect(self._on_submit_analysis)
        ctrl_layout.addWidget(self._submit_btn)

        outer_layout.addLayout(ctrl_layout)

        # ── AI config bar (Base URL / Model / API Key) ────────────────────────
        ai_layout = QHBoxLayout()
        ai_layout.setSpacing(6)

        ai_layout.addWidget(QLabel("Base URL:"))
        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("https://api.deepseek.com")
        self._base_url_edit.setMinimumWidth(200)
        ai_layout.addWidget(self._base_url_edit)

        ai_layout.addWidget(QLabel("模型:"))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("deepseek-v4-pro")
        self._model_edit.setMinimumWidth(130)
        ai_layout.addWidget(self._model_edit)

        ai_layout.addWidget(QLabel("API Key:"))
        self._api_key_inline_edit = QLineEdit()
        self._api_key_inline_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_inline_edit.setPlaceholderText("输入 API Key…")
        self._api_key_inline_edit.setMinimumWidth(180)
        ai_layout.addWidget(self._api_key_inline_edit)

        self._ai_save_btn = QPushButton("保存")
        self._ai_save_btn.setFixedWidth(52)
        self._ai_save_btn.clicked.connect(self._on_save_ai_config)
        ai_layout.addWidget(self._ai_save_btn)

        outer_layout.addLayout(ai_layout)

        # Populate AI config fields from settings
        _ai_settings = getattr(self._ctx, "settings", None)
        if _ai_settings is not None:
            _p = _ai_settings.provider
            self._base_url_edit.setText(getattr(_p, "base_url", "") or "")
            self._model_edit.setText(getattr(_p, "model", "") or "")
            self._api_key_inline_edit.setText(getattr(_p, "api_key", "") or "")

        # ── HTF status label (auto-fetched, read-only) ────────────────────────
        htf_row = QHBoxLayout()
        htf_row.addWidget(QLabel("HTF 周期:"))
        self._htf_tf_label = QLabel("—")
        self._htf_tf_label.setStyleSheet("color: #888888;")
        htf_row.addWidget(self._htf_tf_label)
        htf_row.addStretch()
        self._htf_status_label = QLabel("（提交时自动获取）")
        self._htf_status_label.setStyleSheet("color: #888888; font-size: 11px;")
        htf_row.addWidget(self._htf_status_label)

        # ── Last refresh elapsed label ────────────────────────────────────────
        self._last_refresh_ts: float = 0.0   # monotonic time of last chart update
        self._refresh_elapsed_label = QLabel("距上次刷新: —")
        self._refresh_elapsed_label.setStyleSheet("color: #888888; font-size: 11px;")
        htf_row.addWidget(self._refresh_elapsed_label)

        # 1-second ticker to update the elapsed label
        from PyQt6.QtCore import QTimer as _QTimer
        self._elapsed_ticker = _QTimer(tab)
        self._elapsed_ticker.setInterval(1000)
        self._elapsed_ticker.timeout.connect(self._update_refresh_elapsed)
        self._elapsed_ticker.start()

        outer_layout.addLayout(htf_row)
        # Set initial HTF label based on restored timeframe
        _htf_init = self._HTF_MAP.get(_last_tf, "—")
        self._htf_tf_label.setText(_htf_init)

        # ── Chart + Decision splitter ─────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._chart_widget = ChartWidget()
        self._chart_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        splitter.addWidget(self._chart_widget)

        self._decision_panel = DecisionPanel()
        self._decision_panel.setMinimumWidth(220)
        self._decision_panel.setMaximumWidth(360)
        splitter.addWidget(self._decision_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        outer_layout.addWidget(splitter, stretch=1)

        # Initial button state
        self._update_submit_button_state()

        # Connect symbol/timeframe combo boxes to the switch handler
        self._symbol_combo.currentTextChanged.connect(
            lambda _: self._on_symbol_or_tf_changed(
                self._symbol_combo.currentText(), self._tf_combo.currentText()
            )
        )
        self._tf_combo.currentTextChanged.connect(
            lambda _: self._on_symbol_or_tf_changed(
                self._symbol_combo.currentText(), self._tf_combo.currentText()
            )
        )

        return tab

    def _connect_event_bus(self) -> None:
        """Wire EventBus signals to status bar and tab slots (if bus is ready)."""
        bus = self._ctx.event_bus
        if bus is None:
            return
        bus.status.connect(self._on_status_update)

    def _start_refresh_loop(self) -> None:
        """Start the RefreshLoop only when the data source is connected."""
        data_source = getattr(self._ctx, "data_source", None)
        buffer = getattr(self._ctx, "buffer", None)
        if data_source is None or buffer is None:
            logger.debug("RefreshLoop not started: data_source or buffer not available")
            return

        # Don't start if the data source hasn't connected yet
        if not getattr(data_source, "_connected", False):
            logger.info("Data source not connected — RefreshLoop deferred.")
            self._status_bar.showMessage("数据源未连接，请检查网络后重启程序")
            return

        from pa_agent.data.refresh_loop import RefreshLoop
        from pa_agent.util.threading import CancelToken

        settings = getattr(self._ctx, "settings", None)
        interval_ms = 1000
        n_bars = 200
        if settings is not None:
            interval_ms = getattr(settings.general, "refresh_interval_ms", 1000)
            n_bars = getattr(settings.general, "default_bar_count", 200)

        self._refresh_cancel_token = CancelToken()
        self._refresh_loop = RefreshLoop(
            data_source=data_source,
            buffer=buffer,
            n_bars=n_bars,
            interval_ms=interval_ms,
            cancel_token=self._refresh_cancel_token,
        )

        # Wire RefreshLoop signals
        self._refresh_loop.frame_ready.connect(self._on_refresh_frame_ready)
        self._refresh_loop.status_changed.connect(self._on_status_update)

        self._refresh_loop.start()
        logger.info("RefreshLoop started for %s %s",
                    getattr(data_source, "_symbol", "?"),
                    getattr(data_source, "_timeframe", "?"))

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_status_update(self, text: str) -> None:
        """Update the status bar with subscription / analysis / data-delay text."""
        self._status_bar.showMessage(text)

    def _update_refresh_elapsed(self) -> None:
        """Update the 'distance from last refresh' label every second."""
        import time as _time
        label = getattr(self, "_refresh_elapsed_label", None)
        if label is None:
            return
        if self._last_refresh_ts == 0.0:
            label.setText("距上次刷新: —")
            return
        elapsed = int(_time.monotonic() - self._last_refresh_ts)
        if elapsed < 60:
            label.setText(f"距上次刷新: {elapsed}s")
        else:
            m, s = divmod(elapsed, 60)
            label.setText(f"距上次刷新: {m}m{s:02d}s")
        # Turn red if stale (> 10 seconds without update)
        if elapsed > 10:
            label.setStyleSheet("color: #dc3232; font-size: 11px;")
        else:
            label.setStyleSheet("color: #888888; font-size: 11px;")

    def _on_data_frame(self, frame: Any) -> None:
        """Forward a new KlineFrame to the chart widget (throttled by 30 Hz timer)."""
        self._chart_widget.set_frame(frame)

    def _on_refresh_frame_ready(self, bars: Any) -> None:
        """Handle frame_ready signal from RefreshLoop."""
        if not bars:
            return

        buffer = getattr(self._ctx, "buffer", None)
        if buffer is None:
            return

        try:
            from pa_agent.data.snapshot import take_snapshot
            import time as _time
            settings = getattr(self._ctx, "settings", None)
            n_bars = 200
            if settings is not None:
                n_bars = getattr(settings.general, "default_bar_count", 200)

            symbol = self._symbol_combo.currentText().strip()
            timeframe = self._tf_combo.currentText()

            frame = take_snapshot(buffer, n_bars, symbol, timeframe)
            self._chart_widget.set_frame(frame)

            # Record the time of this successful chart update
            self._last_refresh_ts = _time.monotonic()
            self._update_refresh_elapsed()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Frame build skipped: %s", exc)

    def _on_symbol_or_tf_changed(self, new_symbol: str, new_tf: str) -> None:
        """Handle symbol or timeframe combo box change.

        Steps (design §B.10, R3.1–R3.5):
        1. Cancel current AI worker and wait up to 5 s (zombie if timeout).
        2. Save partial record if analysis was in progress.
        3. Unsubscribe data source, clear buffer, re-subscribe.
        4. Reset ChartWidget.
        5. Destroy FreeChatSession, disable Tab2 input.
        6. Reset or preserve ledger based on settings.
        """
        if self._switching:
            return  # Prevent re-entrant calls

        self._switching = True
        try:
            # ── Step 1: Cancel current AI worker ─────────────────────────────
            if self._worker is not None and self._worker.isRunning():
                if self._cancel_token is not None:
                    self._cancel_token.set()
                finished = self._worker.wait(_WORKER_JOIN_TIMEOUT_MS)
                if not finished:
                    logger.warning(
                        "AI worker did not finish within %d ms after symbol/tf switch; "
                        "marking as zombie",
                        _WORKER_JOIN_TIMEOUT_MS,
                    )
                    # Mark as zombie — do not force-kill
                self._worker = None

            # ── Step 2: Save partial record if analysis was in progress ───────
            if self._analysis_in_progress:
                pending_writer = getattr(self._ctx, "pending_writer", None)
                if pending_writer is not None:
                    # We don't have the active record here; the orchestrator
                    # handles save_partial via the cancel token path.
                    # This is a belt-and-suspenders call for any record that
                    # may have been built but not yet saved.
                    try:
                        pending_writer.save_partial(None, reason="user_switched")
                    except Exception:  # noqa: BLE001
                        pass
                self._analysis_in_progress = False
                self._update_submit_button_state()

            # ── Step 3: Unsubscribe, clear buffer, re-subscribe ───────────────
            data_source = getattr(self._ctx, "data_source", None)
            buffer = getattr(self._ctx, "buffer", None)
            if data_source is not None:
                try:
                    data_source.unsubscribe()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("unsubscribe failed: %s", exc)
            if buffer is not None:
                buffer.clear()
            if data_source is not None:
                try:
                    data_source.subscribe(new_symbol, new_tf)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("subscribe(%s, %s) failed: %s", new_symbol, new_tf, exc)

            # ── Step 4: Reset ChartWidget ─────────────────────────────────────
            if hasattr(self, "_chart_widget"):
                self._chart_widget.reset()

            # ── Step 5: Destroy FreeChatSession, disable Tab2 input ───────────
            self._free_chat_session = None
            self._disable_chat_input()

            # ── Step 6: Reset ledger (always reset on symbol/tf switch) ───────
            ledger = getattr(self._ctx, "ledger", None)
            if ledger is not None:
                try:
                    ledger.reset()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ledger.reset() failed: %s", exc)

            self._status_bar.showMessage(f"已切换至 {new_symbol} {new_tf}")
            logger.info("Symbol/TF switched to %s %s", new_symbol, new_tf)

            # Persist last-used symbol/timeframe to settings
            settings = getattr(self._ctx, "settings", None)
            if settings is not None:
                settings.general.last_symbol = new_symbol
                settings.general.last_timeframe = new_tf
                try:
                    from pa_agent.config.settings import save_settings
                    save_settings(settings)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Failed to persist symbol/tf to settings: %s", exc)

            # Update HTF label to reflect new timeframe
            htf = self._HTF_MAP.get(new_tf, "—")
            self._htf_tf_label.setText(htf)
            self._htf_status_label.setText("（提交时自动获取）")

        finally:
            self._switching = False

    def _disable_chat_input(self) -> None:
        """Disable the Tab2 free-chat input widget if it exists."""
        # The ConversationWidget is in Tab2; try to find and disable its input.
        chat_tab = self._tabs.widget(1)
        if chat_tab is None:
            return
        # Look for QPlainTextEdit children (the input box)
        from PyQt6.QtWidgets import QPlainTextEdit as _PTE
        for child in chat_tab.findChildren(_PTE):
            child.setEnabled(False)
            break

    def _on_submit_analysis(self) -> None:
        """Handle the '提交分析' button click."""
        if not self._can_submit():
            return

        # Cancel any existing worker before starting a new one
        if self._worker is not None and self._worker.isRunning():
            if self._cancel_token is not None:
                self._cancel_token.set()
            self._worker.wait(_WORKER_JOIN_TIMEOUT_MS)
            self._worker = None

        # Gather inputs
        symbol = self._symbol_combo.currentText()
        timeframe = self._tf_combo.currentText()
        bar_count = self._bar_count_spin.value()

        # Auto-fetch HTF K-line data
        htf_text = self._fetch_htf_text(symbol, timeframe)

        # Try to build a KlineFrame snapshot
        frame = self._take_snapshot(symbol, timeframe, bar_count)
        if frame is None:
            self._status_bar.showMessage("数据不足，请等待缓冲区填满后再提交")
            return

        # Build orchestrator (if ctx has the necessary components)
        orchestrator = self._build_orchestrator()
        if orchestrator is None:
            self._status_bar.showMessage("编排器未就绪，请检查设置")
            return

        # Create cancel token
        from pa_agent.util.threading import CancelToken

        self._cancel_token = CancelToken()

        # Start worker in its own QThread (worker IS a QThread subclass)
        self._worker = _AnalysisWorker(
            orchestrator=orchestrator,
            frame=frame,
            htf_text=htf_text,
            cancel_token=self._cancel_token,
            parent=None,  # No parent so it can be moved/managed independently
        )
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.record_ready.connect(self._on_record_ready)
        self._worker.status_update.connect(self._on_status_update)
        self._worker.finished.connect(lambda _: self._on_worker_done())

        self._analysis_in_progress = True
        self._update_submit_button_state()
        self._status_bar.showMessage("分析中…")

        # Clear previous results from conversation and debug tabs
        conv = getattr(self, "_conversation_widget", None)
        if conv is not None:
            conv.clear()
            conv.on_analysis_started()
        debug = getattr(self, "_debug_widget", None)
        if debug is not None:
            debug.clear()

        self._worker.start()

    def _on_analysis_finished(self, decision: dict) -> None:
        """Called on the main thread when the AI worker completes.

        *decision* is the full stage2 JSON dict (``{"decision": {...},
        "diagnosis_summary": {...}}``).  The chart and panel widgets expect
        the inner ``decision`` sub-dict, so we extract it here.
        """
        if decision:
            # The stage2 JSON has a nested "decision" key; extract it so that
            # ChartWidget and DecisionPanel receive the flat decision dict.
            inner = decision.get("decision", decision)
            self._chart_widget.set_decision(inner)
            self._decision_panel.set_decision(inner)
        else:
            self._decision_panel.clear()

    def _on_record_ready(self, record: Any) -> None:
        """Push the full AnalysisRecord to the conversation and debug tabs."""
        import json as _json

        # ── Debug tab: add Stage1 and Stage2 turns ────────────────────────────
        debug = getattr(self, "_debug_widget", None)
        if debug is not None:
            # Stage 1 turn
            s1_msgs = getattr(record, "stage1_messages", []) or []
            s1_system = next((m.get("content", "") for m in s1_msgs if m.get("role") == "system"), "")
            s1_user = next((m.get("content", "") for m in s1_msgs if m.get("role") == "user"), "")
            s1_raw = getattr(record, "stage1_response", {}) or {}
            s1_diag = getattr(record, "stage1_diagnosis", None)
            s1_validation = _json.dumps(s1_diag, ensure_ascii=False, indent=2) if s1_diag else "（验证失败或无数据）"
            debug.add_turn({
                "label": "Stage1 诊断",
                "system_prompt": s1_system,
                "user_prompt": s1_user,
                "raw_response": s1_raw,
                "validation_info": s1_validation,
            })

            # Stage 2 turn
            s2_msgs = getattr(record, "stage2_messages", []) or []
            s2_system = next((m.get("content", "") for m in s2_msgs if m.get("role") == "system"), "")
            s2_user = next((m.get("content", "") for m in s2_msgs if m.get("role") == "user"), "")
            s2_raw = getattr(record, "stage2_response", {}) or {}
            s2_decision = getattr(record, "stage2_decision", None)
            s2_validation = _json.dumps(s2_decision, ensure_ascii=False, indent=2) if s2_decision else "（验证失败或无数据）"
            debug.add_turn({
                "label": "Stage2 决策",
                "system_prompt": s2_system,
                "user_prompt": s2_user,
                "raw_response": s2_raw,
                "validation_info": s2_validation,
            })

            # Exception info if any
            exc_info = getattr(record, "exception", None)
            if exc_info:
                debug.add_turn({
                    "label": "⚠ 异常",
                    "system_prompt": "",
                    "user_prompt": "",
                    "raw_response": {},
                    "validation_info": _json.dumps(exc_info, ensure_ascii=False, indent=2),
                })

        # ── Conversation tab: show stage results ──────────────────────────────
        conv = getattr(self, "_conversation_widget", None)
        if conv is not None:
            # Stage 1 result
            s1_diag = getattr(record, "stage1_diagnosis", None)
            if s1_diag:
                s1_content = _json.dumps(s1_diag, ensure_ascii=False, indent=2)
                s1_raw = getattr(record, "stage1_response", {}) or {}
                s1_reasoning = ""
                if isinstance(s1_raw, dict):
                    choices = s1_raw.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        s1_reasoning = msg.get("reasoning_content", "") or ""
                conv.show_stage_result("阶段一：市场诊断", s1_content, s1_reasoning)

            # Stage 2 result
            s2_decision = getattr(record, "stage2_decision", None)
            if s2_decision:
                s2_content = _json.dumps(s2_decision, ensure_ascii=False, indent=2)
                s2_raw = getattr(record, "stage2_response", {}) or {}
                s2_reasoning = ""
                if isinstance(s2_raw, dict):
                    choices = s2_raw.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        s2_reasoning = msg.get("reasoning_content", "") or ""
                conv.show_stage_result("阶段二：交易决策", s2_content, s2_reasoning)
                conv.on_record_saved()  # enable free-chat input

    def _on_worker_done(self) -> None:
        """Reset in-progress flag and re-enable the submit button."""
        self._analysis_in_progress = False
        self._worker = None
        self._update_submit_button_state()
        self._status_bar.showMessage("分析完成")

    def _on_save_ai_config(self) -> None:
        """Save Base URL / Model / API Key from the inline config bar to settings."""
        settings = getattr(self._ctx, "settings", None)
        if settings is None:
            self._status_bar.showMessage("设置对象未初始化")
            return

        base_url = self._base_url_edit.text().strip()
        model = self._model_edit.text().strip()
        api_key = self._api_key_inline_edit.text()

        if base_url:
            settings.provider.base_url = base_url
        if model:
            settings.provider.model = model
        if api_key:
            settings.provider.api_key = api_key

        try:
            from pa_agent.config.settings import save_settings
            save_settings(settings)
            self._status_bar.showMessage("AI 配置已保存")
            logger.info("AI config saved: base_url=%s model=%s key=***", base_url, model)
        except Exception as exc:  # noqa: BLE001
            self._status_bar.showMessage(f"保存失败: {exc}")
            logger.error("Failed to save AI config: %s", exc)

        # Also update the DeepSeekClient in ctx so the next analysis uses the new key
        client = getattr(self._ctx, "client", None)
        if client is not None:
            try:
                client._settings = settings.provider  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def _open_settings_dialog(self) -> None:
        """Open the SettingsDialog; import lazily to avoid circular imports."""
        from pa_agent.gui.settings_dialog import SettingsDialog
        from pa_agent.config.settings import Settings

        settings: Settings = self._ctx.settings  # type: ignore[assignment]
        if settings is None:
            settings = Settings()

        dlg = SettingsDialog(settings, parent=self)
        dlg.exec()
        self._ctx.settings = settings

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _can_submit(self) -> bool:
        """Return True if the submit button should be enabled."""
        if self._analysis_in_progress:
            return False
        if self._switching:
            return False
        exc_count = self._get_consecutive_count()
        if exc_count >= 2:
            return False
        return True

    def _update_submit_button_state(self) -> None:
        """Enable or disable the submit button based on current state."""
        self._submit_btn.setEnabled(self._can_submit())

    def _get_consecutive_count(self) -> int:
        """Return the current consecutive exception count (0 if unavailable)."""
        try:
            exc_counter = getattr(self._ctx, "exc_counter", None)
            if exc_counter is not None:
                return exc_counter.consecutive_count
        except Exception:  # noqa: BLE001
            pass
        return 0

    def _take_snapshot(self, symbol: str, timeframe: str, bar_count: int) -> Any:
        """Attempt to take a KlineFrame snapshot from the buffer.

        Returns None if the buffer is not ready.
        """
        try:
            buffer = getattr(self._ctx, "buffer", None)
            if buffer is None:
                return None
            from pa_agent.data.snapshot import take_snapshot

            return take_snapshot(buffer, bar_count, symbol, timeframe)
        except ValueError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Snapshot failed: %s", exc)
            return None

    # ── HTF auto-fetch ────────────────────────────────────────────────────────

    # Map current timeframe → higher timeframe to use as context
    _HTF_MAP: dict[str, str] = {
        "1m":  "15m",
        "3m":  "1h",
        "5m":  "1h",
        "15m": "4h",
        "30m": "4h",
        "45m": "4h",
        "1h":  "4h",
        "2h":  "1d",
        "3h":  "1d",
        "4h":  "1d",
        "1d":  "1w",
        "1w":  "1M",
    }

    def _fetch_htf_text(self, symbol: str, timeframe: str) -> str:
        """Fetch the higher-timeframe K-line data and format it as text for the AI.

        Returns an empty string on any error (analysis still proceeds).
        """
        htf = self._HTF_MAP.get(timeframe, "")
        if not htf:
            return ""

        # Update the UI label
        self._htf_tf_label.setText(htf)
        self._htf_status_label.setText("获取中…")

        data_source = getattr(self._ctx, "data_source", None)
        if data_source is None or not getattr(data_source, "_connected", False):
            self._htf_status_label.setText("（数据源未连接）")
            return ""

        try:
            # Temporarily subscribe to HTF, fetch 50 bars, then restore
            original_symbol = getattr(data_source, "_symbol", symbol)
            original_tf = getattr(data_source, "_timeframe", timeframe)

            data_source.subscribe(symbol, htf)
            bars = data_source.latest_snapshot(50)
            data_source.subscribe(original_symbol, original_tf)

            if not bars:
                self._htf_status_label.setText("（无数据）")
                return ""

            # Format as a compact text table for the AI
            lines = [f"## 高时间框架 K 线数据 ({symbol} {htf}，最近 {len(bars)} 根，序号1=最新)"]
            lines.append("序号 | 开盘 | 最高 | 最低 | 收盘 | 成交量")
            lines.append("-----|------|------|------|------|------")
            for bar in bars[:30]:  # cap at 30 to keep prompt size reasonable
                lines.append(
                    f"#{bar.seq} | {bar.open:.2f} | {bar.high:.2f} | "
                    f"{bar.low:.2f} | {bar.close:.2f} | {bar.volume:.0f}"
                )

            self._htf_status_label.setText(f"✓ 已获取 {len(bars)} 根 {htf} K线")
            return "\n".join(lines)

        except Exception as exc:  # noqa: BLE001
            logger.warning("HTF fetch failed (%s %s): %s", symbol, htf, exc)
            self._htf_status_label.setText(f"（获取失败: {exc}）")
            return ""

    def _build_orchestrator(self) -> Any:
        """Build a TwoStageOrchestrator from ctx components, or return None."""
        try:
            from pa_agent.orchestrator.two_stage import TwoStageOrchestrator

            client = getattr(self._ctx, "client", None)
            assembler = getattr(self._ctx, "assembler", None)
            router = getattr(self._ctx, "router", None)
            validator = getattr(self._ctx, "validator", None)
            exc_counter = getattr(self._ctx, "exc_counter", None)
            pending_writer = getattr(self._ctx, "pending_writer", None)
            exp_reader = getattr(self._ctx, "exp_reader", None)
            settings = getattr(self._ctx, "settings", None)

            if any(
                x is None
                for x in [client, assembler, router, validator, exc_counter,
                           pending_writer, exp_reader]
            ):
                return None

            return TwoStageOrchestrator(
                client=client,
                assembler=assembler,
                router=router,
                validator=validator,
                exc_counter=exc_counter,
                pending_writer=pending_writer,
                exp_reader=exp_reader,
                settings=settings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not build orchestrator: %s", exc)
            return None
