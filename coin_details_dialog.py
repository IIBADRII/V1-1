# ui/coin_details_dialog.py
from __future__ import annotations

from typing import Optional, Any
import random

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QPushButton, QSizePolicy
)


class MockStrategyOutput:
    def __init__(self, symbol: str, score: float, signal: str, details: dict):
        self.symbol = symbol
        self.score = score
        self.signal = signal
        self.details = details


class CoinDetailsDialog(QDialog):
    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.symbol = symbol.upper().strip()
        self.setWindowTitle(f"تفاصيل {self.symbol}")
        self.resize(520, 520)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.lbl_symbol = QLabel(self.symbol)
        self.lbl_symbol.setFont(QFont("Roboto", 18, QFont.Bold))

        self.lbl_price = QLabel("--")
        self.lbl_price.setFont(QFont("Roboto", 16, QFont.Bold))

        self.lbl_change = QLabel("--")
        self.lbl_change.setFont(QFont("Roboto", 12))

        header.addWidget(self.lbl_symbol)
        header.addStretch(1)
        header.addWidget(self.lbl_price)
        header.addSpacing(10)
        header.addWidget(self.lbl_change)
        root.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        score_row = QHBoxLayout()
        self.lbl_score = QLabel("Score: --")
        self.lbl_score.setFont(QFont("Roboto", 14, QFont.Bold))

        self.lbl_signal = QLabel("Signal: --")
        self.lbl_signal.setFont(QFont("Roboto", 14, QFont.Bold))

        score_row.addWidget(self.lbl_score)
        score_row.addStretch(1)
        score_row.addWidget(self.lbl_signal)
        root.addLayout(score_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        def mk_title(txt: str) -> QLabel:
            l = QLabel(txt)
            l.setFont(QFont("Roboto", 12, QFont.Bold))
            return l

        def mk_val() -> QLabel:
            l = QLabel("--")
            l.setFont(QFont("Roboto", 12))
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            l.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            return l

        grid.addWidget(mk_title("RSI"), 0, 0)
        self.val_rsi = mk_val()
        grid.addWidget(self.val_rsi, 0, 1)

        grid.addWidget(mk_title("RSI State"), 1, 0)
        self.val_rsi_state = mk_val()
        grid.addWidget(self.val_rsi_state, 1, 1)

        grid.addWidget(mk_title("MACD"), 2, 0)
        self.val_macd = mk_val()
        grid.addWidget(self.val_macd, 2, 1)

        grid.addWidget(mk_title("MACD Signal"), 3, 0)
        self.val_macd_sig = mk_val()
        grid.addWidget(self.val_macd_sig, 3, 1)

        grid.addWidget(mk_title("MACD Hist"), 4, 0)
        self.val_macd_hist = mk_val()
        grid.addWidget(self.val_macd_hist, 4, 1)

        grid.addWidget(mk_title("MACD State"), 5, 0)
        self.val_macd_state = mk_val()
        grid.addWidget(self.val_macd_state, 5, 1)

        grid.addWidget(mk_title("EMA Fast"), 6, 0)
        self.val_ema_fast = mk_val()
        grid.addWidget(self.val_ema_fast, 6, 1)

        grid.addWidget(mk_title("EMA Slow"), 7, 0)
        self.val_ema_slow = mk_val()
        grid.addWidget(self.val_ema_slow, 7, 1)

        grid.addWidget(mk_title("EMA State"), 8, 0)
        self.val_ema_state = mk_val()
        grid.addWidget(self.val_ema_state, 8, 1)

        grid.addWidget(mk_title("BB Upper"), 9, 0)
        self.val_bb_upper = mk_val()
        grid.addWidget(self.val_bb_upper, 9, 1)

        grid.addWidget(mk_title("BB Mid"), 10, 0)
        self.val_bb_mid = mk_val()
        grid.addWidget(self.val_bb_mid, 10, 1)

        grid.addWidget(mk_title("BB Lower"), 11, 0)
        self.val_bb_lower = mk_val()
        grid.addWidget(self.val_bb_lower, 11, 1)

        grid.addWidget(mk_title("BB State"), 12, 0)
        self.val_bb_state = mk_val()
        grid.addWidget(self.val_bb_state, 12, 1)

        grid.addWidget(mk_title("Trend 1h"), 13, 0)
        self.val_trend_1h = mk_val()
        grid.addWidget(self.val_trend_1h, 13, 1)

        root.addLayout(grid)
        root.addStretch(1)

        footer = QHBoxLayout()
        self.btn_close = QPushButton("إغلاق")
        self.btn_close.clicked.connect(self.close)
        
        self.btn_test = QPushButton("اختبار البيانات")
        self.btn_test.clicked.connect(self.test_with_sample_data)
        
        footer.addWidget(self.btn_test)
        footer.addStretch(1)
        footer.addWidget(self.btn_close)
        root.addLayout(footer)

        self._last_price: Optional[float] = None
        self._last_change: Optional[float] = None
        self._last_score: Optional[float] = None
        self._last_signal: Optional[str] = None

    def update_price(self, symbol: str, price: float, change_pct: float):
        sym = symbol.upper().strip()
        if sym != self.symbol:
            return
        self._last_price = price
        self._last_change = change_pct

        self.lbl_price.setText(f"{price:.6f}")
        sign = "+" if change_pct >= 0 else ""
        self.lbl_change.setText(f"{sign}{change_pct:.2f}%")

        if change_pct >= 0:
            self.lbl_change.setStyleSheet("color: #2ecc71; font-weight: 700;")
        else:
            self.lbl_change.setStyleSheet("color: #e74c3c; font-weight: 700;")

    def update_strategy(self, out: Any):
        """يقبل أي كائن له سمات symbol, score, signal, details"""
        try:
            symbol = getattr(out, "symbol", "")
            if symbol.upper() != self.symbol:
                return

            score = getattr(out, "score", 0.0)
            signal = getattr(out, "signal", "")
            details = getattr(out, "details", {}) or {}

            self._last_score = score
            self._last_signal = signal

            self.lbl_score.setText(f"Score: {score:.2f}")
            self.lbl_signal.setText(f"Signal: {signal}")

            if signal == "ENTRY":
                self.lbl_signal.setStyleSheet("color:#2ecc71; font-weight:800;")
            elif signal == "EXIT":
                self.lbl_signal.setStyleSheet("color:#e74c3c; font-weight:800;")
            else:
                self.lbl_signal.setStyleSheet("font-weight:800;")

            def setv(label: QLabel, val, fmt: str = "{}"):
                try:
                    label.setText(fmt.format(val))
                except Exception:
                    label.setText(str(val))

            setv(self.val_rsi, details.get("rsi", "--"), "{:.2f}")
            setv(self.val_rsi_state, details.get("rsi_state", "--"))

            setv(self.val_macd, details.get("macd", "--"), "{:.6f}")
            setv(self.val_macd_sig, details.get("macd_signal", "--"), "{:.6f}")
            setv(self.val_macd_hist, details.get("macd_hist", "--"), "{:.6f}")
            setv(self.val_macd_state, details.get("macd_state", "--"))

            setv(self.val_ema_fast, details.get("ema_fast", "--"), "{:.6f}")
            setv(self.val_ema_slow, details.get("ema_slow", "--"), "{:.6f}")
            setv(self.val_ema_state, details.get("ema_state", "--"))

            setv(self.val_bb_upper, details.get("bb_upper", "--"), "{:.6f}")
            setv(self.val_bb_mid, details.get("bb_mid", "--"), "{:.6f}")
            setv(self.val_bb_lower, details.get("bb_lower", "--"), "{:.6f}")
            setv(self.val_bb_state, details.get("bb_state", "--"))

            setv(self.val_trend_1h, details.get("trend_1h", "--"))

        except Exception as e:
            print(f"Error updating strategy in coin details: {e}")

    def test_with_sample_data(self):
        sample_price = 65000.0 + random.uniform(-1000, 1000)
        sample_change = random.uniform(-5, 5)
        
        self.update_price(self.symbol, sample_price, sample_change)
        
        sample_details = {
            "rsi": random.uniform(20, 80),
            "rsi_state": random.choice(["Oversold", "Bullish", "Neutral", "Bearish", "Overbought"]),
            "macd": random.uniform(-10, 10),
            "macd_signal": random.uniform(-10, 10),
            "macd_hist": random.uniform(-2, 2),
            "macd_state": random.choice(["Bullish Cross", "Bearish Cross", "Bullish", "Bearish", "Flat"]),
            "ema_fast": sample_price * random.uniform(0.98, 1.02),
            "ema_slow": sample_price * random.uniform(0.98, 1.02),
            "ema_state": random.choice(["Uptrend", "Downtrend", "Sideways"]),
            "bb_upper": sample_price * 1.02,
            "bb_mid": sample_price,
            "bb_lower": sample_price * 0.98,
            "bb_state": random.choice(["Upper Band", "Lower Band", "Above Mid", "Below Mid"]),
            "trend_1h": random.choice(["Up", "Down", "Sideways"]),
        }
        
        sample_output = MockStrategyOutput(
            symbol=self.symbol,
            score=random.uniform(0, 100),
            signal=random.choice(["ENTRY", "EXIT", "HOLD"]),
            details=sample_details
        )
        
        self.update_strategy(sample_output)


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)

    dlg = CoinDetailsDialog("BTCUSDT")
    dlg.test_with_sample_data()
    dlg.show()
    sys.exit(app.exec_())