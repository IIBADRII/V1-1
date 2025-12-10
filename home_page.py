# ui/home_page.py
from __future__ import annotations

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit, QPushButton,
    QSizePolicy, QApplication
)

import json
from pathlib import Path

CARD_COLORS = {
    "wallet_usdt": "#4661ff",
    "mode":        "#22c55e",
    "protected":   "#f59e0b",
    "wallet_total":"#06b6d4",
    "equity":      "#14b8a6",
    "pnl":         "#a855f7",
    "open":        "#10b981",
    "closed":      "#ef4444",
}


def _app_font(size_delta: int = 0, weight: int = QFont.Normal) -> QFont:
    """خذ خط التطبيق من الإعدادات (QApplication) وعدّل الحجم/الوزن."""
    try:
        app = QApplication.instance()
        if app:
            base = app.font()
        else:
            base = QFont("Arial", 10)
    except Exception:
        base = QFont("Arial", 10)
    
    f = QFont(base.family(), max(7, base.pointSize() + size_delta))
    f.setWeight(weight)
    return f


def _mini_card(title: str, accent: str) -> Tuple[QFrame, QLabel]:
    box = QFrame()
    box.setObjectName("MiniCard")
    box.setStyleSheet(f"""
    QFrame#MiniCard {{
        background: rgba(20,26,36,0.9);
        border: 1px solid rgba(120,130,150,0.25);
        border-radius: 10px;
    }}
    QFrame#Accent {{
        background: {accent};
        border-radius: 6px;
    }}
    """)
    root = QHBoxLayout(box)
    root.setContentsMargins(8, 8, 8, 8)
    root.setSpacing(8)

    accent_bar = QFrame()
    accent_bar.setObjectName("Accent")
    accent_bar.setFixedWidth(6)
    accent_bar.setFixedHeight(48)

    v = QVBoxLayout()
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)

    t = QLabel(title)
    t.setFont(_app_font(-2, QFont.Bold))
    t.setStyleSheet("color:#aab3c5;")
    t.setAlignment(Qt.AlignCenter)

    val = QLabel("--")
    val.setFont(_app_font(+3, QFont.Black))
    val.setStyleSheet("color:#e6e9ef;")
    val.setAlignment(Qt.AlignCenter)

    v.addWidget(t)
    v.addWidget(val)
    root.addWidget(accent_bar, 0, Qt.AlignTop)
    root.addLayout(v, 1)

    box.setFixedHeight(80)
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return box, val


class _EngineBridge(QObject):
    """جسر آمن لنقل أحداث الـ TradingEngine إلى ثريد الـ UI."""
    runtime_stats = pyqtSignal(dict)
    status_changed = pyqtSignal(str)


class HomePage(QWidget):
    """
    Home layout:
    - Mini cards top (2 rows)
    - Watchlist table
    - Logs at bottom
    """

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ===== Cards grid =====
        cards_grid = QGridLayout()
        cards_grid.setHorizontalSpacing(8)
        cards_grid.setVerticalSpacing(8)

        self.card_wallet_usdt, self.lbl_wallet_usdt = _mini_card("USDT بالمحفظة", CARD_COLORS["wallet_usdt"])
        self.card_mode, self.lbl_mode = _mini_card("وضع التشغيل", CARD_COLORS["mode"])
        self.card_protected, self.lbl_protected = _mini_card("وضع الحماية", CARD_COLORS["protected"])
        self.card_wallet_total, self.lbl_wallet_total = _mini_card("رصيد المحفظة الحقيقي (USDT)", CARD_COLORS["wallet_total"])
        self.card_equity, self.lbl_equity = _mini_card("رصيد البوت (USDT)", CARD_COLORS["equity"])
        self.card_pnl, self.lbl_pnl = _mini_card("PnL اليوم (USDT)", CARD_COLORS["pnl"])
        self.card_open, self.lbl_open = _mini_card("مفتوحة", CARD_COLORS["open"])
        self.card_closed, self.lbl_closed = _mini_card("مغلقة (اليوم)", CARD_COLORS["closed"])

        cards_grid.addWidget(self.card_wallet_usdt,   0, 0)
        cards_grid.addWidget(self.card_mode,          0, 1)
        cards_grid.addWidget(self.card_protected,     0, 2)
        cards_grid.addWidget(self.card_wallet_total,  0, 3)

        cards_grid.addWidget(self.card_equity,        1, 0)
        cards_grid.addWidget(self.card_pnl,           1, 1)
        cards_grid.addWidget(self.card_open,          1, 2)
        cards_grid.addWidget(self.card_closed,        1, 3)

        root.addLayout(cards_grid)

        # ===== Watchlist compact =====
        title_wl = QLabel("عملات المراقبة (Live)")
        title_wl.setFont(_app_font(0, QFont.Bold))
        root.addWidget(title_wl)

        self.watch_table = QTableWidget(0, 3)
        self.watch_table.setHorizontalHeaderLabels(["العملة", "السعر", "التغيير 24h %"])
        self.watch_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.watch_table.verticalHeader().setVisible(False)
        self.watch_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.watch_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.watch_table.setFixedHeight(220)
        root.addWidget(self.watch_table)

        # ===== Logs compact =====
        logs_head = QHBoxLayout()
        title_logs = QLabel("سجل الأحداث")
        title_logs.setFont(_app_font(0, QFont.Bold))
        self.btn_clear_logs = QPushButton("مسح")
        self.btn_clear_logs.setFixedWidth(70)
        logs_head.addWidget(title_logs)
        logs_head.addStretch(1)
        logs_head.addWidget(self.btn_clear_logs)
        root.addLayout(logs_head)

        self.logs_view = QTextEdit()
        self.logs_view.setReadOnly(True)
        self.logs_view.setFixedHeight(200)
        root.addWidget(self.logs_view)

        self.btn_clear_logs.clicked.connect(self.logs_view.clear)

        # caches
        self._watch_symbols: List[str] = []
        self._watch_rows: Dict[str, int] = {}

        # engine + bridge
        self._engine = None
        self._bridge = _EngineBridge()
        self._bridge.runtime_stats.connect(self._on_runtime_stats_ui)
        self._bridge.status_changed.connect(self._on_status_changed_ui)

        # مؤقت لتحديث العدادات
        self.auto_timer: Optional[QTimer] = QTimer(self)
        self.auto_timer.setInterval(8000)
        self.auto_timer.timeout.connect(self.refresh_from_engine)

    # -------- Watchlist API --------
    def set_watchlist(self, symbols: List[str]):
        symbols = [s.upper() for s in (symbols or [])]
        self._watch_symbols = symbols
        self._watch_rows.clear()
        self.watch_table.setRowCount(0)
        for s in symbols:
            r = self.watch_table.rowCount()
            self.watch_table.insertRow(r)
            self._watch_rows[s] = r
            self.watch_table.setItem(r, 0, QTableWidgetItem(s))
            self.watch_table.setItem(r, 1, QTableWidgetItem("--"))
            self.watch_table.setItem(r, 2, QTableWidgetItem("--"))

    def update_price(self, sym: str, price: float, change: float):
        sym = sym.upper()
        if sym not in self._watch_rows:
            return
        r = self._watch_rows[sym]
        it1 = self.watch_table.item(r, 1)
        it2 = self.watch_table.item(r, 2)
        if it1:
            it1.setText(f"{price:.6f}")
        if it2:
            it2.setText(f"{change:.2f}%")

    # -------- Logs API --------
    def append_log(self, text: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.logs_view.append(f"[{now}] {text}")

    # -------- Cards API --------
    def update_status(self, status: str, mode: str, protected_reason: Optional[str]):
        self.lbl_mode.setText("حقيقي" if (mode or "").lower() == "live" else "تجريبي")

        if status == "PROTECTED":
            self.lbl_protected.setText("مُفعّل")
            self.lbl_protected.setStyleSheet("color:#f59e0b; font-weight:900;")
        else:
            self.lbl_protected.setText("غير مُفعّل")
            self.lbl_protected.setStyleSheet("")

    def update_wallet_usdt(self, usdt_free: float):
        self.lbl_wallet_usdt.setText(f"{usdt_free:.2f}")

    def update_wallet_total(self, total_usdt: float):
        self.lbl_wallet_total.setText(f"{total_usdt:.2f}")

    def update_equity(self, equity_usdt: float):
        self.lbl_equity.setText(f"{equity_usdt:.2f}")

    def update_daily_pnl(self, pnl_usdt: float):
        self.lbl_pnl.setText(f"{pnl_usdt:.2f}")
        if pnl_usdt > 0:
            self.lbl_pnl.setStyleSheet("color:#22c55e; font-weight:900;")
        elif pnl_usdt < 0:
            self.lbl_pnl.setStyleSheet("color:#ef4444; font-weight:900;")
        else:
            self.lbl_pnl.setStyleSheet("")

    def update_counts(self, open_count: int, closed_today: int):
        self.lbl_open.setText(str(int(open_count)))
        self.lbl_closed.setText(str(int(closed_today)))

    # -------- Engine bind --------
    def bind_engine(self, engine):
        """يتم استدعاؤها من الـ MainWindow لربط الصفحة مع البوت."""
        self._engine = engine
        if hasattr(engine, 'add_listener'):
            engine.add_listener(self._on_engine_event)
        self.auto_timer.start()
        self.refresh_from_engine()

    # -------- Engine events (من ثريد البوت) --------
    def _on_engine_event(self, evt) -> None:
        try:
            if evt.kind == "RUNTIME_STATS":
                self._bridge.runtime_stats.emit(evt.data)
            elif evt.kind == "STATUS":
                status = str(evt.data.get("status", "UNKNOWN"))
                self._bridge.status_changed.emit(status)
        except Exception:
            pass

    # -------- date parser helper --------
    def _parse_closed_date(self, ca: Any):
        if not ca:
            return None
        try:
            if isinstance(ca, (int, float)):
                return datetime.utcfromtimestamp(float(ca)).date()
            s = str(ca)
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s).date()
        except Exception:
            return None

    def _load_today_closed_trades_pnl(self) -> float:
        """
        يحسب PnL اليوم من الصفقات المغلقة اليوم فقط.
        """
        try:
            if self._engine and getattr(self._engine, "state", None):
                st = self._engine.state.get_state() or {}
                closed_list = st.get("closed_positions") or st.get("closed_trades") or []
            else:
                state_path = Path("state") / "bot_state.json"
                if not state_path.exists():
                    return 0.0
                with state_path.open("r", encoding="utf-8") as f:
                    st = json.load(f) or {}
                closed_list = st.get("closed_positions") or st.get("closed_trades") or []

            today = datetime.utcnow().date()
            total_pnl = 0.0

            for pos in closed_list:
                ca = pos.get("closed_at")
                closed_date = self._parse_closed_date(ca)
                if not closed_date or closed_date != today:
                    continue

                pnl_val = pos.get("pnl_usdt", pos.get("pnl", 0.0))
                try:
                    total_pnl += float(pnl_val or 0.0)
                except Exception:
                    continue

            return float(total_pnl)

        except Exception as e:
            self.append_log(f"[UI ERROR] load_today_closed_trades_pnl: {e}")
            return 0.0

    # -------- UI slots --------
    def _on_runtime_stats_ui(self, data: dict) -> None:
        try:
            status = str(data.get("status", "UNKNOWN"))
            protected = bool(data.get("protected", False))
            paper_mode = bool(data.get("paper_mode", True))

            usdt_free = float(data.get("account_usdt_free", 0.0))
            wallet_total = float(data.get("account_total_usdt", 0.0))
            self.update_wallet_usdt(usdt_free if not paper_mode else 0.0)
            self.update_wallet_total(wallet_total if not paper_mode else 0.0)

            pnl_today = self._load_today_closed_trades_pnl()

            max_bot = float(
                data.get("max_bot_balance", getattr(self._engine, "max_bot_balance", 0.0)) or 0.0
            )

            if paper_mode:
                paper_balance = float(data.get("paper_balance_usdt", max_bot) or max_bot)
                bot_balance = paper_balance + pnl_today
            else:
                bot_balance = max_bot + pnl_today

            self.update_equity(bot_balance)
            self.update_daily_pnl(pnl_today)

            mode = "paper" if paper_mode else "live"
            self.update_status(status, mode, "ON" if protected else None)

        except Exception as e:
            self.append_log(f"[UI ERROR] runtime_stats: {e}")

    def _on_status_changed_ui(self, status: str) -> None:
        try:
            paper_mode = True
            if self._engine is not None:
                paper_mode = bool(getattr(self._engine, "paper_mode", True))
            mode = "paper" if paper_mode else "live"
            self.update_status(status, mode, None)
        except Exception as e:
            self.append_log(f"[UI ERROR] status_update: {e}")

    # -------- دورية: تحديث عدد الصفقات --------
    def refresh_from_engine(self):
        if not self._engine:
            return

        pm = getattr(self._engine, "positions", None)
        if pm is None:
            self.update_counts(0, 0)
            return

        try:
            opens = len(pm.get_open_positions())
            closed = pm.get_closed_positions()

            today = datetime.utcnow().date()
            closed_today = 0

            for p in closed:
                ca = p.get("closed_at")
                d = self._parse_closed_date(ca)
                if d and d == today:
                    closed_today += 1

            self.update_counts(opens, closed_today)

        except Exception:
            self.update_counts(0, 0)