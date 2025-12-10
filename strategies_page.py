# ui/strategies_page.py
from __future__ import annotations

from typing import Dict, Optional, TYPE_CHECKING, Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView
)

from core.state_manager import StateManager


class StrategiesPage(QWidget):
    def __init__(self, state: StateManager, engine):
        super().__init__()
        self.state = state
        self.engine = engine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        info = QLabel("تفاصيل المؤشرات لكل عملة (Live)")
        info.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(info)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "العملة", "Score", "Signal", "RSI", "MACD", "EMA Trend", "BB State"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        self._rows: Dict[str, int] = {}

        self.preload_from_watchlist()

        self.timer = QTimer(self)
        self.timer.setInterval(9000)
        self.timer.timeout.connect(self.refresh_from_engine_cache)
        self.timer.start()

    # -------------------------
    # preload
    # -------------------------
    def preload_from_watchlist(self):
        try:
            st = self.state.get_state() or {}
            wl = st.get("watchlist", ["BTCUSDT", "ETHUSDT"])
            for sym in wl:
                self._ensure_row(str(sym))
        except Exception as e:
            print(f"Error preloading watchlist: {e}")

    def _ensure_row(self, sym: str):
        sym = sym.upper().strip()
        if not sym:
            return
        if sym in self._rows:
            return

        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[sym] = row

        for col in range(7):
            item = QTableWidgetItem("--")
            if col == 0:
                item.setText(sym)
            self.table.setItem(row, col, item)

    # -------------------------
    # update from StrategyOutput-like object
    # -------------------------
    def update_strategy(self, out: Any):
        """
        تحديث صف الاستراتيجية.
        يستخدم duck-typing لتفادي اعتماد صارم على StrategyOutput
        وبالتالي يقلل فرص circular imports.
        """
        try:
            sym = str(getattr(out, "symbol", "") or "").upper().strip()
            if not sym:
                return

            if sym not in self._rows:
                self._ensure_row(sym)

            row = self._rows[sym]

            score = float(getattr(out, "score", 0.0) or 0.0)
            signal = str(getattr(out, "signal", "") or "")

            # Score / Signal
            self.table.item(row, 1).setText(f"{score:.2f}")
            self.table.item(row, 2).setText(signal or "--")

            # Signal color
            signal_item = self.table.item(row, 2)
            if signal == "ENTRY":
                signal_item.setForeground(QColor(0, 255, 0))
            elif signal == "EXIT":
                signal_item.setForeground(QColor(255, 0, 0))
            else:
                signal_item.setForeground(QColor(255, 255, 255))

            details = getattr(out, "details", None) or {}
            if not isinstance(details, dict):
                details = {}

            # RSI
            rsi_val = details.get("rsi")
            if rsi_val is not None:
                try:
                    rsi_val_f = float(rsi_val)
                    self.table.item(row, 3).setText(f"{rsi_val_f:.2f}")
                    rsi_item = self.table.item(row, 3)
                    if rsi_val_f < 30:
                        rsi_item.setForeground(QColor(0, 255, 0))
                    elif rsi_val_f > 70:
                        rsi_item.setForeground(QColor(255, 0, 0))
                    else:
                        rsi_item.setForeground(QColor(255, 255, 255))
                except Exception:
                    self.table.item(row, 3).setText("--")
            else:
                self.table.item(row, 3).setText("--")

            # MACD / EMA / BB
            self.table.item(row, 4).setText(str(details.get("macd_state", "--")))
            self.table.item(row, 5).setText(str(details.get("ema_state", "--")))
            self.table.item(row, 6).setText(str(details.get("bb_state", "--")))

        except Exception as e:
            print(f"Error updating strategy in table: {e}")

    def on_strategy_update(self, out: Any):
        self.update_strategy(out)

    # -------------------------
    # refresh from engine cache
    # -------------------------
    def refresh_from_engine_cache(self):
        try:
            strat = getattr(self.engine, "strategy", None)
            if strat is None:
                return

            outputs = getattr(strat, "outputs", None)

            if outputs is None:
                get_fn = getattr(strat, "get_outputs", None)
                if callable(get_fn):
                    outputs = get_fn()
                else:
                    outputs = {}

            if not isinstance(outputs, dict) or not outputs:
                return

            for symbol, out in outputs.items():
                if out is None:
                    continue
                self.update_strategy(out)

        except Exception as e:
            print(f"Error refreshing strategy cache: {e}")