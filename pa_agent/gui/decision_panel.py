"""DecisionPanel — displays the AI trading decision in the home tab.

Task 14.3:
  - When order_type == "不下单": shows only reasoning text and the conclusion.
  - Otherwise: shows direction, type, entry, TP, SL, and brief reasoning.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_NO_ORDER = "不下单"


class DecisionPanel(QWidget):
    """Panel that renders the Stage-2 AI decision.

    Parameters
    ----------
    parent:
        Optional Qt parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Title
        title = QLabel("AI 决策")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Conclusion label (always visible)
        self._conclusion_label = QLabel("—")
        self._conclusion_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        self._conclusion_label.setWordWrap(True)
        layout.addWidget(self._conclusion_label)

        # Trade details (hidden when 不下单)
        self._details_widget = QWidget()
        details_layout = QVBoxLayout(self._details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(4)

        self._direction_label = QLabel()
        self._order_type_label = QLabel()
        self._entry_label = QLabel()
        self._tp_label = QLabel()
        self._sl_label = QLabel()
        self._confidence_label = QLabel()

        for lbl in (
            self._direction_label,
            self._order_type_label,
            self._entry_label,
            self._tp_label,
            self._sl_label,
            self._confidence_label,
        ):
            lbl.setWordWrap(True)
            details_layout.addWidget(lbl)

        layout.addWidget(self._details_widget)

        # Reasoning text area
        reasoning_title = QLabel("分析理由")
        reasoning_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(reasoning_title)

        self._reasoning_edit = QTextEdit()
        self._reasoning_edit.setReadOnly(True)
        self._reasoning_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._reasoning_edit)

        # Start in cleared state
        self.clear()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_decision(self, decision: dict) -> None:
        """Populate the panel with the given Stage-2 decision dict."""
        order_type = decision.get("order_type", _NO_ORDER)
        reasoning = decision.get("reasoning", decision.get("brief_reasoning", ""))
        confidence = decision.get("confidence", None)

        # Confidence score colour mapping (0-100 integer)
        def _conf_color(score: int) -> str:
            if score >= 70:
                return "#00c850"   # green
            if score >= 50:
                return "#e6b800"   # yellow
            return "#dc3232"       # red

        if order_type == _NO_ORDER:
            self._conclusion_label.setText("结论：不下单")
            self._conclusion_label.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #aaaaaa;"
            )
            self._details_widget.setVisible(False)
        else:
            direction = decision.get("order_direction", "—")
            entry = decision.get("entry_price")
            tp = decision.get("take_profit_price")
            sl = decision.get("stop_loss_price")

            self._conclusion_label.setText(f"结论：{order_type}")
            color = "#00c850" if "多" in direction else "#dc3232"
            self._conclusion_label.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {color};"
            )

            self._direction_label.setText(f"方向：{direction}")
            self._order_type_label.setText(f"订单类型：{order_type}")
            self._entry_label.setText(
                f"入场价：{entry:.5g}" if entry is not None else "入场价：—"
            )
            self._tp_label.setText(
                f"止盈价：{tp:.5g}" if tp is not None else "止盈价：—"
            )
            self._sl_label.setText(
                f"止损价：{sl:.5g}" if sl is not None else "止损价：—"
            )

            # Confidence score
            if confidence is not None:
                try:
                    score = int(confidence)
                    c_color = _conf_color(score)
                    self._confidence_label.setText(f"信心评分：{score} / 100")
                    self._confidence_label.setStyleSheet(
                        f"font-weight: bold; color: {c_color};"
                    )
                except (ValueError, TypeError):
                    # Fallback: model returned old-style string
                    _legacy = {"high": 80, "medium": 55, "low": 30}
                    score = _legacy.get(str(confidence).lower(), 50)
                    c_color = _conf_color(score)
                    self._confidence_label.setText(f"信心评分：{score} / 100（{confidence}）")
                    self._confidence_label.setStyleSheet(
                        f"font-weight: bold; color: {c_color};"
                    )
            else:
                self._confidence_label.setText("")

            self._details_widget.setVisible(True)

        self._reasoning_edit.setPlainText(str(reasoning) if reasoning else "")

    def clear(self) -> None:
        """Reset the panel to its initial empty state."""
        self._conclusion_label.setText("—")
        self._conclusion_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #888888;"
        )
        self._details_widget.setVisible(False)
        self._reasoning_edit.clear()
