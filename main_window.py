# ui/main_window.py
from __future__ import annotations

import os
import sys
import threading
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QFont, QIcon, QFontDatabase, QColor, QBrush
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QLineEdit, QMessageBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QCheckBox, QComboBox, QTextEdit, QTabWidget, QDialog,
)

from core.settings_manager import SettingsManager
from core.state_manager import StateManager
from core.logger import Logger, LogEntry
from core.trading_engine import TradingEngine
from core.strategy_engine import StrategyOutput
from core.position_manager import PositionEvent
from ui.sound_alerts import SoundAlerts, SoundConfig
from ui.popup_notifications import NotificationManager
from ui.watchlist_integrations import attach_watchlist_details
from ui.manual_close_dialog import ManualCloseDialog
from core.api_keys import load_api_keys, save_api_keys


# =========================================================
# Qt Bridge
# =========================================================
class EngineBridge(QObject):
    price_update = pyqtSignal(str, float, float)
    strategy_update = pyqtSignal(object)
    position_event = pyqtSignal(object)
    engine_event = pyqtSignal(str, dict)
    log_event = pyqtSignal(object)
    market_status = pyqtSignal(str)
    bot_status_changed = pyqtSignal(str)


# =========================================================
# Premium Themes
# =========================================================
PREMIUM_DARK = """
QMainWindow, QWidget {
    background: #020617;
    color: #e5e7eb;
    font-size: 11pt;
    font-family: "IBM Plex Sans Arabic", "Tajawal", "Segoe UI";
}

QFrame#AppShell {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #020617,
        stop:1 #041f1d
    );
}

QFrame#SideBar {
    background: #020c0b;
    border-right: 1px solid #0f172a;
}

QFrame#TopBar {
    background: rgba(3, 7, 18, 0.96);
    border-bottom: 1px solid #0f172a;
}

QPushButton#NavBtn {
    background: transparent;
    color: #cbd5f5;
    text-align: left;
    padding: 9px 12px;
    border-radius: 9px;
    font-weight: 600;
}
QPushButton#NavBtn:hover {
    background: rgba(255, 255, 255, 0.04);
    color: #ffffff;
}
QPushButton#NavBtn:checked {
    background: rgba(29, 72, 69, 0.90);
    color: #facc15;
    border: 1px solid #22c55e;
}

QPushButton#StartBtn {
    background: #022c22;
    color: #bbf7d0;
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: 800;
    border: 1px solid #16a34a;
}
QPushButton#StartBtn:hover {
    background: #065f46;
}

QPushButton#StopBtn {
    background: #3f1a1a;
    color: #fecaca;
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: 800;
    border: 1px solid #f97373;
}
QPushButton#StopBtn:hover {
    background: #7f1d1d;
}

QPushButton {
    background: #020c0b;
    color: #e5e7eb;
    border: 1px solid #1f2933;
    padding: 6px 10px;
    border-radius: 7px;
    font-weight: 600;
}
QPushButton:hover {
    background: #1d4845;
    border-color: #22c55e;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: #020b10;
    color: #e5e7eb;
    border: 1px solid #1f2933;
    border-radius: 6px;
    padding: 4px 6px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border-color: #22c55e;
}

QTabBar::tab {
    background: #020b10;
    color: #9ca3af;
    padding: 6px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background: #1d4845;
    color: #facc15;
}

QTableWidget {
    background: #020b10;
    color: #e5e7eb;
    gridline-color: #111827;
    selection-background-color: #1d4845;
    selection-color: #f9fafb;
    border: 1px solid #111827;
}
QHeaderView::section {
    background: #020b10;
    color: #9ca3af;
    padding: 4px 6px;
    border: 0px;
    border-bottom: 1px solid #111827;
}

QScrollBar:vertical {
    background: #020617;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #1d4845;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}

QMessageBox {
    background: #020617;
}
QMessageBox QLabel {
    color: #e5e7eb;
}
"""

PREMIUM_LIGHT = """
QMainWindow, QWidget {
    background: #f4f4f5;
    color: #020617;
    font-size: 11pt;
    font-family: "IBM Plex Sans Arabic", "Tajawal", "Segoe UI";
}

QFrame#AppShell {
    background: #f4f4f5;
}

QFrame#SideBar {
    background: #ffffff;
    border-right: 1px solid #e5e7eb;
}

QFrame#TopBar {
    background: rgba(255, 255, 255, 0.96);
    border-bottom: 1px solid #e5e7eb;
}

QPushButton#NavBtn {
    background: transparent;
    color: #334155;
    text-align: left;
    padding: 9px 12px;
    border-radius: 9px;
    font-weight: 600;
}
QPushButton#NavBtn:hover {
    background: #e5f4f2;
    color: #022c22;
}
QPushButton#NavBtn:checked {
    background: #1d4845;
    color: #facc15;
    border: 1px solid #16a34a;
}

QPushButton#StartBtn {
    background: #dcfce7;
    color: #166534;
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: 800;
    border: 1px solid #86efac;
}
QPushButton#StartBtn:hover {
    background: #bbf7d0;
}

QPushButton#StopBtn {
    background: #fee2e2;
    color: #b91c1c;
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: 800;
    border: 1px solid #fecaca;
}
QPushButton#StopBtn:hover {
    background: #fecaca;
}

QPushButton {
    background: #ffffff;
    color: #0f172a;
    border-radius: 7px;
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
    font-weight: 600;
}
QPushButton:hover {
    background: #e5f4f2;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: #ffffff;
    color: #020617;
    border-radius: 6px;
    border: 1px solid #e2e8f0;
    padding: 4px 6px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border-color: #1d4845;
}

QTabBar::tab {
    background: #e5e7eb;
    color: #4b5563;
    padding: 6px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background: #1d4845;
    color: #facc15;
}

QTableWidget {
    background: #ffffff;
    color: #020617;
    gridline-color: #e5e7eb;
    selection-background-color: #1d4845;
    selection-color: #f9fafb;
    border: 1px solid #e5e7eb;
}
QHeaderView::section {
    background: #f9fafb;
    color: #6b7280;
    padding: 4px 6px;
    border: 0px;
    border-bottom: 1px solid #e5e7eb;
}

QScrollBar:vertical {
    background: #f4f4f5;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #cbd5f5;
    border-radius: 4px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}

QMessageBox {
    background: #ffffff;
}
QMessageBox QLabel {
    color: #020617;
}
"""


# =========================================================
# ToggleSwitch - FIXED VERSION (بدون paintEvent)
# =========================================================
class ToggleSwitch(QCheckBox):
    def __init__(self, on_text="حقيقي", off_text="تجريبي", parent=None):
        super().__init__(parent)
        self.on_text = on_text
        self.off_text = off_text
        self.setTristate(False)
        self.setFixedSize(90, 28)
        
        # تحديث النص أولاً
        self._update_text()
        
        # ربط الإشارة لتحديث النص عند التغيير
        self.toggled.connect(self._update_text)
        
        # تطبيق الأنماط
        self._apply_style()

    def _update_text(self):
        """تحديث النص بناءً على الحالة"""
        self.setText(self.on_text if self.isChecked() else self.off_text)

    def _apply_style(self):
        """تطبيق الأنماط باستخدام QSS فقط (بدون paintEvent)"""
        self.setStyleSheet("""
        QCheckBox {
            border-radius: 14px;
            background: #141a24;
            border: 1px solid #232b3a;
            color: #cfd6e4;
            font-weight: 800;
            padding-left: 8px;
            padding-right: 8px;
        }
        QCheckBox::indicator {
            width: 0px;
            height: 0px;
        }
        QCheckBox:checked {
            background: #0f3b26;
            border: 1px solid #1f6b46;
            color: #eaffea;
        }
        QCheckBox:hover {
            background: #1e2636;
        }
        QCheckBox:checked:hover {
            background: #14532d;
        }
        """)


# =========================================================
# Pages
# =========================================================
class WatchlistPage(QWidget):
    def __init__(self, settings: SettingsManager, state: StateManager):
        super().__init__()
        self.settings = settings
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("أضف رمز عملة (BTCUSDT)")
        self.add_btn = QPushButton("إضافة")
        self.remove_btn = QPushButton("حذف المحدد")
        bar.addWidget(self.symbol_input)
        bar.addWidget(self.add_btn)
        bar.addWidget(self.remove_btn)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["العملة", "السعر", "التغيير 24h %"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self._symbols: List[str] = []
        self._symbol_rows: Dict[str, int] = {}

        self.add_btn.clicked.connect(self.add_symbol)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.reload_from_state()

    def reload_from_state(self):
        st = self.state.get_state() or {}
        self._symbols = [s.upper() for s in st.get("watchlist", ["BTCUSDT"])]
        self._symbol_rows.clear()
        self.table.setRowCount(0)

        for row, sym in enumerate(self._symbols):
            self.table.insertRow(row)
            self._symbol_rows[sym] = row
            self.table.setItem(row, 0, QTableWidgetItem(sym))
            self.table.setItem(row, 1, QTableWidgetItem("--"))
            self.table.setItem(row, 2, QTableWidgetItem("--"))

    def update_price(self, sym: str, price: float, change: float):
        sym = sym.upper()
        if sym not in self._symbol_rows:
            return
        row = self._symbol_rows[sym]
        if self.table.item(row, 1):
            self.table.item(row, 1).setText(f"{price:.6f}")
        if self.table.item(row, 2):
            self.table.item(row, 2).setText(f"{change:.2f}%")

    def add_symbol(self):
        sym = self.symbol_input.text().strip().upper()
        if not sym:
            return

        st = self.state.get_state() or {}
        wl = st.get("watchlist", [])
        if sym not in wl:
            wl.append(sym)
            self.state.set_watchlist(wl)

        self.symbol_input.clear()
        QApplication.processEvents()
        self.reload_from_state()

    def remove_selected(self):
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()), reverse=True)
        if not rows:
            return
        st = self.state.get_state() or {}
        wl = st.get("watchlist", [])
        for r in rows:
            if r < len(self._symbols):
                sym = self._symbols[r]
                if sym in wl:
                    wl.remove(sym)
        self.state.set_watchlist(wl)
        self.reload_from_state()


class PositionsPage(QWidget):
    def __init__(self, sounds: Optional[SoundAlerts] = None):
        super().__init__()
        self.sounds = sounds

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.open_table = QTableWidget(0, 7)
        self.open_table.setHorizontalHeaderLabels(
            ["العملة", "المصدر", "سعر الدخول", "السعر الحالي", "الكمية", "PnL USDT", "PnL %"]
        )
        self.open_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.open_table.verticalHeader().setVisible(False)
        self.open_table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.closed_table = QTableWidget(0, 8)
        self.closed_table.setHorizontalHeaderLabels(
            ["العملة", "المصدر", "سعر الدخول", "سعر الخروج", "الكمية", "PnL USDT", "PnL %", "السبب"]
        )
        self.closed_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.closed_table.verticalHeader().setVisible(False)
        self.closed_table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(QLabel("المراكز المفتوحة"))
        layout.addWidget(self.open_table)
        layout.addWidget(QLabel("الصفقات المغلقة"))
        layout.addWidget(self.closed_table)

        self._open_rows: Dict[str, int] = {}
        self._closed_rows: Dict[str, int] = {}

    def load_positions(self, open_positions: List[Dict[str, Any]], closed_positions: List[Dict[str, Any]]):
        self.open_table.setRowCount(0)
        self.closed_table.setRowCount(0)
        self._open_rows.clear()
        self._closed_rows.clear()
        for p in open_positions:
            self._upsert_open(p)
        for p in closed_positions[:200]:
            self._upsert_closed(p)

    def _upsert_open(self, p: Dict[str, Any]):
        pid = p["id"]
        if pid not in self._open_rows:
            row = self.open_table.rowCount()
            self.open_table.insertRow(row)
            self._open_rows[pid] = row
            for c in range(7):
                self.open_table.setItem(row, c, QTableWidgetItem(""))
        row = self._open_rows[pid]

        self.open_table.item(row, 0).setText(p["symbol"])
        self.open_table.item(row, 1).setText(p.get("source", "bot"))
        self.open_table.item(row, 2).setText(f"{p.get('entry_price', 0):.6f}")
        self.open_table.item(row, 3).setText(f"{p.get('current_price', 0):.6f}")
        self.open_table.item(row, 4).setText(f"{p.get('qty', 0):.8f}")
        self.open_table.item(row, 5).setText(f"{p.get('pnl_usdt', 0):.4f}")
        self.open_table.item(row, 6).setText(f"{p.get('pnl_percent', 0):.2f}%")

        try:
            pnl_usdt = float(p.get("pnl_usdt", 0.0) or 0.0)
        except Exception:
            pnl_usdt = 0.0

        if pnl_usdt > 0:
            color = QColor(46, 204, 113)
        elif pnl_usdt < 0:
            color = QColor(239, 68, 68)
        else:
            color = QColor(148, 163, 184)

        for col in (5, 6):
            item = self.open_table.item(row, col)
            if item is not None:
                item.setForeground(QBrush(color))

    def _upsert_closed(self, p: Dict[str, Any]):
        pid = p["id"]
        if pid not in self._closed_rows:
            row = self.closed_table.rowCount()
            self.closed_table.insertRow(row)
            self._closed_rows[pid] = row
            for c in range(8):
                self.closed_table.setItem(row, c, QTableWidgetItem(""))
        row = self._closed_rows[pid]

        self.closed_table.item(row, 0).setText(p["symbol"])
        self.closed_table.item(row, 1).setText(p.get("source", "bot"))
        self.closed_table.item(row, 2).setText(f"{p.get('entry_price', 0):.6f}")

        exit_price = p.get("exit_price", p.get("current_price", 0))
        self.closed_table.item(row, 3).setText(f"{exit_price:.6f}")

        self.closed_table.item(row, 4).setText(f"{p.get('qty', 0):.8f}")
        self.closed_table.item(row, 5).setText(f"{p.get('pnl_usdt', 0):.4f}")
        self.closed_table.item(row, 6).setText(f"{p.get('pnl_percent', 0):.2f}%")
        self.closed_table.item(row, 7).setText(str(p.get("exit_reason", "")))

        try:
            pnl_usdt = float(p.get("pnl_usdt", 0.0) or 0.0)
        except Exception:
            pnl_usdt = 0.0

        if pnl_usdt > 0:
            color = QColor(46, 204, 113)
        elif pnl_usdt < 0:
            color = QColor(239, 68, 68)
        else:
            color = QColor(148, 163, 184)

        for col in (5, 6):
            item = self.closed_table.item(row, col)
            if item is not None:
                item.setForeground(QBrush(color))

    def on_position_event(self, evt: PositionEvent):
        p = evt.position

        if evt.kind == "OPENED":
            self._upsert_open(p)
            try:
                if self.sounds:
                    self.sounds.play_entry()
            except Exception:
                pass

        elif evt.kind == "UPDATED":
            if p["id"] in self._open_rows:
                self._upsert_open(p)

        elif evt.kind == "CLOSED":
            pid = p["id"]
            if pid in self._open_rows:
                row = self._open_rows.pop(pid)
                self.open_table.removeRow(row)
            self._upsert_closed(p)
            try:
                if self.sounds:
                    self.sounds.play_exit()
            except Exception:
                pass


class SettingsPage(QWidget):
    def __init__(self, settings: SettingsManager):
        super().__init__()
        self.settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.setDocumentMode(True)

        # -------------------------
        # Binance
        # -------------------------
        tab_api = QWidget()
        api_l = QFormLayout(tab_api)
        api_l.setLabelAlignment(Qt.AlignRight)

        stored_key, stored_secret = load_api_keys()

        self.api_key = QLineEdit(stored_key)
        self.api_secret = QLineEdit(stored_secret)
        self.api_secret.setEchoMode(QLineEdit.Password)

        self.use_testnet = QCheckBox("استخدام Testnet (حساب تجريبي)")
        self.use_testnet.setChecked(bool(self.settings.get("binance.use_testnet", False)))

        self.recv_window = QSpinBox()
        self.recv_window.setRange(0, 60000)
        self.recv_window.setValue(int(self.settings.get("binance.recv_window_ms", 5000)))

        self.timeout_sec = QSpinBox()
        self.timeout_sec.setRange(0, 120)
        self.timeout_sec.setValue(int(self.settings.get("binance.timeout_sec", 10)))

        api_l.addRow("API Key:", self.api_key)
        api_l.addRow("API Secret:", self.api_secret)
        api_l.addRow("استخدام Testnet:", self.use_testnet)
        api_l.addRow("Recv Window (ms):", self.recv_window)
        api_l.addRow("Timeout (ثواني):", self.timeout_sec)

        self.tabs.addTab(tab_api, "Binance")

        # -------------------------
        # Trading
        # -------------------------
        tab_trading = QWidget()
        tr_l = QFormLayout(tab_trading)
        tr_l.setLabelAlignment(Qt.AlignRight)

        self.trading_mode = QComboBox()
        self.trading_mode.addItems(["paper", "live"])
        self.trading_mode.setCurrentText(self.settings.get("trading.mode", "paper"))

        self.trading_manage_only = QCheckBox("إدارة صفقات البوت فقط")
        self.trading_manage_only.setChecked(bool(self.settings.get("trading.manage_only_bot_positions", True)))

        self.trading_close_on_stop = QCheckBox("إغلاق الصفقات عند إيقاف البوت")
        self.trading_close_on_stop.setChecked(bool(self.settings.get("trading.close_positions_on_stop", False)))

        self.trading_cooldown = QSpinBox()
        self.trading_cooldown.setRange(0, 180)
        self.trading_cooldown.setValue(int(self.settings.get("trading.cooldown_on_restart_min", 3)))

        tr_l.addRow("وضع التداول:", self.trading_mode)
        tr_l.addRow("", self.trading_manage_only)
        tr_l.addRow("", self.trading_close_on_stop)
        tr_l.addRow("مدة التبريد بعد إعادة التشغيل (دقيقة):", self.trading_cooldown)

        self.tabs.addTab(tab_trading, "التداول")

        # -------------------------
        # Bot Capital
        # -------------------------
        tab_bot = QWidget()
        bt_l = QFormLayout(tab_bot)
        bt_l.setLabelAlignment(Qt.AlignRight)

        self.bot_alloc_usdt = QDoubleSpinBox()
        self.bot_alloc_usdt.setRange(0, 1_000_000_000)
        self.bot_alloc_usdt.setDecimals(2)
        self.bot_alloc_usdt.setValue(float(self.settings.get("risk_limits.max_bot_balance", 100.0)))

        self.paper_initial_balance = QDoubleSpinBox()
        self.paper_initial_balance.setRange(0, 1_000_000_000)
        self.paper_initial_balance.setDecimals(2)
        self.paper_initial_balance.setValue(float(self.settings.get("paper.initial_balance", 100.0)))

        bt_l.addRow("المبلغ المخصص للبوت (USDT):", self.bot_alloc_usdt)
        bt_l.addRow("رصيد البوت التجريبي (Paper):", self.paper_initial_balance)

        self.tabs.addTab(tab_bot, "البوت")

        # -------------------------
        # Market Data
        # -------------------------
        tab_mkt = QWidget()
        mk_l = QFormLayout(tab_mkt)
        mk_l.setLabelAlignment(Qt.AlignRight)

        self.market_timeout = QSpinBox()
        self.market_timeout.setRange(0, 3600)
        self.market_timeout.setValue(int(self.settings.get("market_data.data_timeout_sec", 60)))

        self.market_history_limit = QSpinBox()
        self.market_history_limit.setRange(1, 10000)
        self.market_history_limit.setValue(int(self.settings.get("market_data.history_candles_limit", 50)))

        k_intervals = self.settings.get("market_data.kline_intervals", ["15m", "1h"])
        k_intervals_text = ", ".join(str(x) for x in k_intervals) if isinstance(k_intervals, list) else str(k_intervals)
        self.market_kline_intervals = QLineEdit(k_intervals_text)

        ws_backoff = self.settings.get("market_data.ws_backoff_sec", [2, 5, 10, 15])
        ws_backoff_text = ", ".join(str(x) for x in ws_backoff) if isinstance(ws_backoff, list) else str(ws_backoff)
        self.market_ws_backoff = QLineEdit(ws_backoff_text)

        mk_l.addRow("مهلة بيانات السوق (ثانية):", self.market_timeout)
        mk_l.addRow("عدد الشموع التاريخية:", self.market_history_limit)
        mk_l.addRow("فواصل الكلاين (مثال: 15m,1h):", self.market_kline_intervals)
        mk_l.addRow("أزمنة إعادة المحاولة WS (مثال: 2,5,10,15):", self.market_ws_backoff)

        self.tabs.addTab(tab_mkt, "بيانات السوق")

        # -------------------------
        # Appearance
        # -------------------------
        tab_app = QWidget()
        ap_l = QFormLayout(tab_app)
        ap_l.setLabelAlignment(Qt.AlignRight)

        self.ap_theme = QComboBox()
        self.ap_theme.addItems(["dark", "light"])
        self.ap_theme.setCurrentText(self.settings.get("appearance.theme", "dark"))

        self.ap_font_family = QLineEdit(self.settings.get("appearance.font_family", "Tajawal"))

        self.ap_font_size = QSpinBox()
        self.ap_font_size.setRange(6, 32)
        self.ap_font_size.setValue(int(self.settings.get("appearance.font_size_base", 9)))

        ap_l.addRow("الثيم:", self.ap_theme)
        ap_l.addRow("نوع الخط:", self.ap_font_family)
        ap_l.addRow("حجم الخط الأساسي:", self.ap_font_size)

        self.tabs.addTab(tab_app, "المظهر")

        # -------------------------
        # Alerts
        # -------------------------
        tab_alerts = QWidget()
        al_l = QFormLayout(tab_alerts)
        al_l.setLabelAlignment(Qt.AlignRight)

        self.alerts_sound_enabled = QCheckBox("تفعيل صوت التنبيهات (Alerts)")
        self.alerts_sound_enabled.setChecked(bool(self.settings.get("alerts.sound_enabled", False)))

        self.alerts_sound_file = QLineEdit(self.settings.get("alerts.sound_file", ""))

        self.alerts_desktop = QCheckBox("تفعيل تنبيهات سطح المكتب")
        self.alerts_desktop.setChecked(bool(self.settings.get("alerts.desktop_notifications", False)))

        al_l.addRow("", self.alerts_sound_enabled)
        al_l.addRow("ملف صوت التنبيه:", self.alerts_sound_file)
        al_l.addRow("تنبيهات سطح المكتب:", self.alerts_desktop)

        self.tabs.addTab(tab_alerts, "Alerts")

        # -------------------------
        # Sound
        # -------------------------
        tab_sound = QWidget()
        sd_l = QFormLayout(tab_sound)
        sd_l.setLabelAlignment(Qt.AlignRight)

        self.sound_enabled = QCheckBox("تفعيل الصوت")
        self.sound_enabled.setChecked(bool(self.settings.get("sound.enabled", True)))

        self.sound_volume = QDoubleSpinBox()
        self.sound_volume.setRange(0.0, 1.0)
        self.sound_volume.setSingleStep(0.05)
        self.sound_volume.setDecimals(2)
        self.sound_volume.setValue(float(self.settings.get("sound.volume", 0.9)))

        self.sound_file = QLineEdit(self.settings.get("sound.file", "data/sounds/notify.wav"))
        self.sound_entry_file = QLineEdit(self.settings.get("sound.entry_file", "data/sounds/entry.wav"))
        self.sound_exit_file = QLineEdit(self.settings.get("sound.exit_file", "data/sounds/exit.wav"))
        self.sound_notify_file = QLineEdit(self.settings.get("sound.notify_file", "data/sounds/notify.wav"))

        sd_l.addRow("", self.sound_enabled)
        sd_l.addRow("ملف الصوت الرئيسي:", self.sound_file)
        sd_l.addRow("صوت دخول الصفقة:", self.sound_entry_file)
        sd_l.addRow("صوت إغلاق الصفقة:", self.sound_exit_file)
        sd_l.addRow("صوت الإشعار العام:", self.sound_notify_file)

        self.tabs.addTab(tab_sound, "الصوت")

        # -------------------------
        # Telegram
        # -------------------------
        tab_tg = QWidget()
        tg_l = QFormLayout(tab_tg)
        tg_l.setLabelAlignment(Qt.AlignRight)

        self.tg_enabled = QCheckBox("تفعيل تيليجرام")
        self.tg_enabled.setChecked(bool(self.settings.get("telegram.enabled", False)))

        self.tg_token = QLineEdit(str(self.settings.get("telegram.bot_token", "")))
        self.tg_chat_id = QLineEdit(str(self.settings.get("telegram.chat_id", "")))

        self.tg_status_interval = QDoubleSpinBox()
        self.tg_status_interval.setRange(10.0, 36000.0)
        self.tg_status_interval.setDecimals(1)
        self.tg_status_interval.setSingleStep(10.0)
        self.tg_status_interval.setValue(float(self.settings.get("telegram.status_interval_sec", 60.0)))

        tg_l.addRow("", self.tg_enabled)
        tg_l.addRow("Bot Token:", self.tg_token)
        tg_l.addRow("Chat ID:", self.tg_chat_id)
        tg_l.addRow("فاصل تقارير الحالة (ثانية):", self.tg_status_interval)

        self.tabs.addTab(tab_tg, "Telegram")

        # -------------------------
        # System
        # -------------------------
        tab_sys = QWidget()
        sy_l = QFormLayout(tab_sys)
        sy_l.setLabelAlignment(Qt.AlignRight)

        self.sys_auto_restart = QCheckBox("إعادة تشغيل تلقائية عند الخطأ")
        self.sys_auto_restart.setChecked(bool(self.settings.get("system.auto_restart_on_error", True)))

        self.sys_state_backup = QCheckBox("تفعيل النسخ الاحتياطي للحالة")
        self.sys_state_backup.setChecked(bool(self.settings.get("system.state_backup_enabled", True)))

        sy_l.addRow("", self.sys_auto_restart)
        sy_l.addRow("", self.sys_state_backup)

        self.tabs.addTab(tab_sys, "النظام")

        self.save_btn = QPushButton("حفظ الإعدادات")
        root.addWidget(self.save_btn, alignment=Qt.AlignLeft)
        self.save_btn.clicked.connect(self.save_settings)

    def save_settings(self):
        save_api_keys(self.api_key.text(), self.api_secret.text())

        self.settings.set("binance.use_testnet", bool(self.use_testnet.isChecked()), auto_save=False)
        self.settings.set("binance.recv_window_ms", int(self.recv_window.value()), auto_save=False)
        self.settings.set("binance.timeout_sec", int(self.timeout_sec.value()), auto_save=False)

        self.settings.set("trading.mode", self.trading_mode.currentText(), auto_save=False)
        self.settings.set("trading.manage_only_bot_positions", bool(self.trading_manage_only.isChecked()), auto_save=False)
        self.settings.set("trading.close_positions_on_stop", bool(self.trading_close_on_stop.isChecked()), auto_save=False)
        self.settings.set("trading.cooldown_on_restart_min", int(self.trading_cooldown.value()), auto_save=False)

        self.settings.set("risk_limits.max_bot_balance", float(self.bot_alloc_usdt.value()), auto_save=False)
        self.settings.set("paper.initial_balance", float(self.paper_initial_balance.value()), auto_save=False)

        self.settings.set("market_data.data_timeout_sec", int(self.market_timeout.value()), auto_save=False)
        self.settings.set("market_data.history_candles_limit", int(self.market_history_limit.value()), auto_save=False)

        intervals_text = self.market_kline_intervals.text().strip()
        intervals = [s.strip() for s in intervals_text.split(",") if s.strip()] if intervals_text else []
        self.settings.set("market_data.kline_intervals", intervals, auto_save=False)

        ws_backoff_text = self.market_ws_backoff.text().strip()
        if ws_backoff_text:
            parts = [s.strip() for s in ws_backoff_text.split(",") if s.strip()]
            backoff: List[int] = []
            for p in parts:
                try:
                    backoff.append(int(p))
                except ValueError:
                    pass
        else:
            backoff = []
        self.settings.set("market_data.ws_backoff_sec", backoff, auto_save=False)

        self.settings.set("appearance.theme", self.ap_theme.currentText(), auto_save=False)
        self.settings.set("appearance.font_family", self.ap_font_family.text().strip(), auto_save=False)
        self.settings.set("appearance.font_size_base", int(self.ap_font_size.value()), auto_save=False)

        self.settings.set("alerts.sound_enabled", bool(self.alerts_sound_enabled.isChecked()), auto_save=False)
        self.settings.set("alerts.sound_file", self.alerts_sound_file.text().strip(), auto_save=False)
        self.settings.set("alerts.desktop_notifications", bool(self.alerts_desktop.isChecked()), auto_save=False)

        self.settings.set("sound.enabled", bool(self.sound_enabled.isChecked()), auto_save=False)
        self.settings.set("sound.volume", float(self.sound_volume.value()), auto_save=False)
        self.settings.set("sound.file", self.sound_file.text().strip(), auto_save=False)
        self.settings.set("sound.entry_file", self.sound_entry_file.text().strip(), auto_save=False)
        self.settings.set("sound.exit_file", self.sound_exit_file.text().strip(), auto_save=False)
        self.settings.set("sound.notify_file", self.sound_notify_file.text().strip(), auto_save=False)

        self.settings.set("telegram.enabled", bool(self.tg_enabled.isChecked()), auto_save=False)
        self.settings.set("telegram.bot_token", self.tg_token.text().strip(), auto_save=False)
        self.settings.set("telegram.chat_id", self.tg_chat_id.text().strip(), auto_save=False)
        self.settings.set("telegram.status_interval_sec", float(self.tg_status_interval.value()), auto_save=False)

        self.settings.set("system.auto_restart_on_error", bool(self.sys_auto_restart.isChecked()), auto_save=False)
        self.settings.set("system.state_backup_enabled", bool(self.sys_state_backup.isChecked()), auto_save=False)

        self.settings.save_settings()
        QMessageBox.information(self, "تم", "تم حفظ الإعدادات ✅")


class LogsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.logs_view = QTextEdit()
        self.logs_view.setReadOnly(True)
        layout.addWidget(self.logs_view)

    def append_log(self, entry: LogEntry):
        self.logs_view.append(entry.format())


# =========================================================
# MainWindow
# =========================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = SettingsManager()
        self.state = StateManager()
        self.state.load_state()
        self.logger = Logger()

        self.engine = TradingEngine(self.settings, self.state, self.logger)

        # Bridge
        self.bridge = EngineBridge()

        # Optional modules
        self.notifications = NotificationManager(self)
        self.sounds = SoundAlerts(SoundConfig(
            enabled=bool(self.settings.get("sound.enabled", False)),
            sound_file=str(self.settings.get("sound.file", "data/sounds/notify.wav")),
            volume=float(self.settings.get("sound.volume", 0.9))
        ))

        # Bridge wiring
        self.engine.market.add_price_listener(lambda s, p, c: self.bridge.price_update.emit(s, p, c))
        self.engine.strategy.add_listener(lambda out: self.bridge.strategy_update.emit(out))
        self.engine.positions.add_listener(lambda evt: self.bridge.position_event.emit(evt))
        self.engine.add_listener(lambda evt: self.bridge.engine_event.emit(evt.kind, evt.data))
        self.engine.market.add_connection_listener(lambda st: self.bridge.market_status.emit(st))
        self.logger.add_listener(lambda e: self.bridge.log_event.emit(e))

        # Window
        self.setWindowTitle("AI Spot Trading Bot — Premium UI")
        self.resize(1020, 640)
        self.setMinimumSize(980, 600)

        # load fonts
        self._load_app_fonts()
        self.apply_font()

        # Shell
        shell = QFrame()
        shell.setObjectName("AppShell")
        self.setCentralWidget(shell)

        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        # Sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("SideBar")
        self.sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 12, 10, 12)
        side_layout.setSpacing(6)

        brand = QLabel("Badr Bot")
        brand.setFont(QFont(QApplication.instance().font().family(), 16, QFont.Black))
        side_layout.addWidget(brand)
        side_layout.addSpacing(6)

        # -------------------------------------------------
        # Nav buttons
        # -------------------------------------------------
        def nav_btn(text: str, icon: str = ""):
            b = QPushButton(text)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            if icon:
                ic = QIcon.fromTheme(icon)
                if not ic.isNull():
                    b.setIcon(ic)
                    b.setIconSize(QSize(18, 18))
            return b

        self.btn_home  = nav_btn("الرئيسية", "go-home")
        self.btn_watch = nav_btn("قائمة عملات المراقبة", "view-list")
        self.btn_strat = nav_btn("الاستراتيجيات", "applications-graphics")
        self.btn_pos   = nav_btn("إدارة المراكز", "document-open-recent")
        self.btn_set   = nav_btn("الإعدادات", "preferences-system")
        self.btn_logs  = nav_btn("سجل الأحداث", "accessories-text-editor")

        # زر مراكز الحساب
        self.btn_account_positions = QPushButton("مراكز الحساب")
        self.btn_account_positions.setObjectName("NavBtn")
        self.btn_account_positions.setCheckable(False)
        self.btn_account_positions.setMinimumWidth(130)
        self.btn_account_positions.clicked.connect(self.show_account_positions_dialog)

        for b in [
            self.btn_home,
            self.btn_watch,
            self.btn_strat,
            self.btn_pos,
            self.btn_account_positions,
            self.btn_set,
            self.btn_logs,
        ]:
            side_layout.addWidget(b)

        side_layout.addStretch(1)

        # Theme toggle
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.settings.get("appearance.theme", "dark"))
        side_layout.addWidget(self.theme_combo)

        shell_layout.addWidget(self.sidebar)

        # Right area
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        shell_layout.addWidget(right, 1)

        # TopBar
        self.topbar = QFrame()
        self.topbar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.topbar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(8)

        self.market_label = QLabel("السوق: غير متصل")
        self.status_label = QLabel("الحالة: متوقف")

        # toggle paper/live - FIXED VERSION
        self.mode_switch = ToggleSwitch(on_text="حقيقي", off_text="تجريبي")
        self.mode_switch.setChecked(not self.engine.paper_mode)
        self.mode_switch.toggled.connect(self.on_mode_toggled)

        self.btn_startstop = QPushButton("تشغيل البوت")
        self.btn_startstop.setObjectName("StartBtn")
        self.btn_startstop.setMinimumWidth(140)

        self.btn_manual_close = QPushButton("إغلاق يدوي")
        self.btn_manual_close.setMinimumWidth(105)

        self.btn_test_details = QPushButton("اختبار التفاصيل")
        self.btn_test_details.setMinimumWidth(105)
        self.btn_test_details.clicked.connect(self.test_coin_details)

        top_layout.addWidget(self.btn_manual_close)
        top_layout.addWidget(self.btn_startstop)
        top_layout.addWidget(self.market_label)
        top_layout.addSpacing(10)
        top_layout.addWidget(self.status_label)
        top_layout.addSpacing(10)
        top_layout.addWidget(QLabel("الوضع:"))
        top_layout.addWidget(self.mode_switch)
        top_layout.addStretch(1)
        top_layout.addWidget(self.btn_test_details)

        right_layout.addWidget(self.topbar)

        # Pages stack
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        # Lazy imports لكسر الـ circular import
        from ui.home_page import HomePage
        from ui.strategies_page import StrategiesPage

        self.page_home  = HomePage()
        self.page_watch = WatchlistPage(self.settings, self.state)
        self.page_strat = StrategiesPage(self.state, self.engine)
        self.page_pos   = PositionsPage(self.sounds)
        self.page_set   = SettingsPage(self.settings)
        self.page_logs  = LogsPage()

        self.stack.addWidget(self.page_home)
        self.stack.addWidget(self.page_watch)
        self.stack.addWidget(self.page_strat)
        self.stack.addWidget(self.page_pos)
        self.stack.addWidget(self.page_set)
        self.stack.addWidget(self.page_logs)

        # Bind home to engine + init lists
        self.page_home.bind_engine(self.engine)
        st = self.state.get_state() or {}
        wl = st.get("watchlist", ["BTCUSDT"])
        self.page_home.set_watchlist(wl)

        # Watchlist details controller
        self.watch_details = attach_watchlist_details(self.page_watch.table)

        # Nav wiring
        self.btn_home.clicked.connect(lambda: self._set_page(0, self.btn_home))
        self.btn_watch.clicked.connect(lambda: self._set_page(1, self.btn_watch))
        self.btn_strat.clicked.connect(lambda: self._set_page(2, self.btn_strat))
        self.btn_pos.clicked.connect(lambda: self._set_page(3, self.btn_pos))
        self.btn_set.clicked.connect(lambda: self._set_page(4, self.btn_set))
        self.btn_logs.clicked.connect(lambda: self._set_page(5, self.btn_logs))
        self._set_page(0, self.btn_home)

        # Start/Stop wiring
        self.btn_startstop.clicked.connect(self.toggle_start_stop)

        # Manual close
        self.btn_manual_close.clicked.connect(self.open_manual_close_dialog)

        # Theme
        self.theme_combo.currentTextChanged.connect(self.apply_theme)
        self.apply_theme(self.theme_combo.currentText())

        # Bridge signals → slots
        self.bridge.price_update.connect(self.on_price_update)
        self.bridge.strategy_update.connect(self.on_strategy_update)
        self.bridge.position_event.connect(self.on_position_event)
        self.bridge.engine_event.connect(self.on_engine_event)
        self.bridge.log_event.connect(self.on_log_event)
        self.bridge.market_status.connect(self.on_market_status)
        self.bridge.bot_status_changed.connect(self.on_bot_status_changed)

        # Load positions initially
        self.page_pos.load_positions(
            self.engine.positions.get_open_positions(),
            self.engine.positions.get_closed_positions()
        )

        # Sync watchlist -> market symbols
        self.watchlist_timer = QTimer()
        self.watchlist_timer.timeout.connect(self.sync_watchlist_to_engine)
        self.watchlist_timer.start(12000)

        # Update button state initially
        self.update_start_stop_button()

    # -------- نافذة مراكز الحساب (إدارة يدوية) --------
    def show_account_positions_dialog(self):
        self.engine.refresh_account_positions()
        positions = self.engine.get_account_positions() or {}

        dlg = QDialog(self)
        dlg.setWindowTitle("مراكز الحساب (تحكم يدوي)")
        dlg.resize(1050, 620)
        dlg.setMinimumSize(1000, 580)

        layout = QVBoxLayout(dlg)

        table = QTableWidget(0, 9)
        table.setHorizontalHeaderLabels([
            "العملة",
            "الرمز",
            "الكمية الكلية",
            "المتاحة",
            "سعر الدخول",
            "السعر الحالي",
            "القيمة بالدولار",
            "الربح/الخسارة",
            "الربح %"
        ])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        def _fill_table():
            table.setRowCount(0)
            for pos in positions.values():
                row = table.rowCount()
                table.insertRow(row)

                asset = pos.asset
                symbol = pos.symbol
                qty = float(pos.qty or 0.0)
                free = float(pos.free or 0.0)
                last_price = float(pos.last_price or 0.0)
                value_usdt = float(pos.value_usdt or 0.0)

                entry_price = float(getattr(pos, "entry_price", 0.0) or 0.0)
                pnl_usdt = float(getattr(pos, "pnl_usdt", 0.0) or 0.0)
                pnl_pct = float(getattr(pos, "pnl_percent", 0.0) or 0.0)

                table.setItem(row, 0, QTableWidgetItem(asset))
                table.setItem(row, 1, QTableWidgetItem(symbol))
                table.setItem(row, 2, QTableWidgetItem(f"{qty:.8f}"))
                table.setItem(row, 3, QTableWidgetItem(f"{free:.8f}"))
                table.setItem(row, 4, QTableWidgetItem(f"{entry_price:.6f}" if entry_price > 0 else "--"))
                table.setItem(row, 5, QTableWidgetItem(f"{last_price:.6f}"))
                table.setItem(row, 6, QTableWidgetItem(f"{value_usdt:.4f}"))

                if entry_price > 0 and last_price > 0 and qty > 0:
                    item_pnl = QTableWidgetItem(f"{pnl_usdt:.4f}")
                    item_pct = QTableWidgetItem(f"{pnl_pct:.2f}%")

                    if pnl_usdt > 0:
                        color = QColor(46, 204, 113)
                    elif pnl_usdt < 0:
                        color = QColor(239, 68, 68)
                    else:
                        color = QColor(148, 163, 184)

                    item_pnl.setForeground(QBrush(color))
                    item_pct.setForeground(QBrush(color))
                else:
                    item_pnl = QTableWidgetItem("--")
                    item_pct = QTableWidgetItem("--")

                table.setItem(row, 7, item_pnl)
                table.setItem(row, 8, item_pct)

        _fill_table()
        layout.addWidget(table)

        btns = QHBoxLayout()
        btns.addStretch(1)

        btn_close_sel = QPushButton("إغلاق المركز المحدد (بيع المتاح)")
        btn_close_sel.setFont(QFont(dlg.font().family(), 9, QFont.Bold))

        btn_cancel = QPushButton("إغلاق")
        btn_cancel.setFont(QFont(dlg.font().family(), 9))

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_close_sel)
        layout.addLayout(btns)

        def _get_selected_symbol_and_qty():
            rows = sorted({i.row() for i in table.selectedIndexes()})
            if not rows:
                return None, 0.0
            r = rows[0]
            sym_item = table.item(r, 1)
            free_item = table.item(r, 3)
            if not sym_item or not free_item:
                return None, 0.0
            try:
                free_val = float(free_item.text() or 0.0)
            except Exception:
                free_val = 0.0
            return sym_item.text(), free_val

        def on_close_selected():
            nonlocal positions

            symbol, free_qty = _get_selected_symbol_and_qty()
            if not symbol:
                QMessageBox.warning(dlg, "تنبيه", "اختر مركزاً أولاً.")
                return
            if free_qty <= 0:
                QMessageBox.warning(dlg, "تنبيه", "لا يوجد كمية متاحة للبيع لهذا الرمز.")
                return

            ok = QMessageBox.question(
                dlg,
                "تأكيد",
                f"هل تريد بيع الكمية المتاحة ({free_qty:.8f}) من {symbol} بأمر MARKET؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ok != QMessageBox.Yes:
                return

            success = self.engine.close_account_position(symbol)
            if not success:
                QMessageBox.critical(dlg, "خطأ", "فشل إغلاق المركز، راجع اللوق.")
                return

            self.engine.refresh_account_positions(force=True)
            positions = self.engine.get_account_positions() or {}
            _fill_table()

        btn_close_sel.clicked.connect(on_close_selected)
        btn_cancel.clicked.connect(dlg.close)

        dlg.exec_()

    # ---------------- Fonts ----------------
    def _load_app_fonts(self):
        fonts_dir = os.path.join(BASE_DIR, "fonts")
        if not os.path.isdir(fonts_dir):
            return
        for fn in os.listdir(fonts_dir):
            if fn.lower().endswith((".ttf", ".otf")):
                try:
                    QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fn))
                except Exception:
                    pass

    def apply_font(self):
        fam = self.settings.get("appearance.font_family", "Tajawal")
        size = int(self.settings.get("appearance.font_size_base", 11))
        QApplication.instance().setFont(QFont(fam, size))
        try:
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        except Exception:
            pass

    # ---------------- UI helpers ----------------
    def _set_page(self, idx: int, btn: QPushButton):
        for b in [self.btn_home, self.btn_watch, self.btn_strat, self.btn_pos, self.btn_set, self.btn_logs]:
            b.setChecked(False)
        btn.setChecked(True)
        self.stack.setCurrentIndex(idx)

    def apply_theme(self, theme: str):
        self.settings.set("appearance.theme", theme)
        self.setStyleSheet(PREMIUM_DARK if theme == "dark" else PREMIUM_LIGHT)
        self.apply_font()
        self._refresh_startstop_style()

    def _refresh_startstop_style(self):
        try:
            self.btn_startstop.style().unpolish(self.btn_startstop)
            self.btn_startstop.style().polish(self.btn_startstop)
            self.btn_startstop.update()
        except Exception:
            pass

    def update_start_stop_button(self):
        if self.engine.is_running:
            self.btn_startstop.setText("إيقاف البوت")
            self.btn_startstop.setObjectName("StopBtn")
        else:
            self.btn_startstop.setText("تشغيل البوت")
            self.btn_startstop.setObjectName("StartBtn")
        self._refresh_startstop_style()

    def toggle_start_stop(self):
        if self.engine.is_running:
            try:
                self.engine.stop_trading()
                self.update_start_stop_button()
                self.status_label.setText("الحالة: متوقف")
                self.page_home.append_log("تم إيقاف البوت")
                self.bridge.bot_status_changed.emit("STOPPED")
            except Exception as e:
                self.page_home.append_log(f"خطأ في إيقاف البوت: {e}")
        else:
            try:
                self.sync_watchlist_to_engine(force=True)
                self.engine.start_trading()
                self.update_start_stop_button()
                self.status_label.setText("الحالة: يعمل")
                self.page_home.append_log("تم تشغيل البوت")
                self.bridge.bot_status_changed.emit("RUNNING")
            except Exception as e:
                self.page_home.append_log(f"خطأ في تشغيل البوت: {e}")

    def on_mode_toggled(self, checked: bool):
        live = bool(checked)
        self.engine.set_paper_mode(not live)
        self.page_home.append_log("تم تغيير الوضع إلى " + ("حقيقي" if live else "تجريبي"))

    def sync_watchlist_to_engine(self, force: bool = False):
        st = self.state.get_state() or {}
        wl = st.get("watchlist", ["BTCUSDT"])

        self.page_home.set_watchlist(wl)
        try:
            self.page_strat.preload_from_watchlist()
        except Exception:
            pass

        if self.engine.is_running and not force:
            return

        def _bg_update():
            try:
                self.engine.market.update_symbols(wl)
            except Exception as e:
                self.logger.log(f"Market update_symbols error: {e}", level="ERROR")

        threading.Thread(target=_bg_update, daemon=True).start()

    def open_manual_close_dialog(self):
        open_positions = self.engine.positions.get_open_positions()

        def close_cb(pid: str) -> bool:
            pos = self.engine.positions.open_positions.get(pid)
            if not pos:
                return False
            sym = pos["symbol"]
            last = self.engine.market.prices.get(sym)
            if not last:
                return False
            self.engine._execute_close(pid, float(last), "MANUAL_CLOSE")
            return True

        dlg = ManualCloseDialog(open_positions, close_cb, parent=self)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def test_coin_details(self):
        try:
            from ui.coin_details_dialog import CoinDetailsDialog
            import random

            symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT"]
            symbol = random.choice(symbols)

            dlg = CoinDetailsDialog(symbol, parent=self)
            dlg.test_with_sample_data()

            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

            self.logger.info(f"فتح نافذة اختبار تفاصيل لـ {symbol}")

        except Exception as e:
            self.logger.error(f"خطأ في اختبار تفاصيل العملة: {e}")
            QMessageBox.critical(self, "خطأ", f"فشل اختبار التفاصيل: {e}")

    # ---------------- Bridge slots ----------------
    def on_price_update(self, sym: str, price: float, change: float):
        try:
            self.page_watch.update_price(sym, price, change)
            self.watch_details.push_price(sym, price, change)
            self.page_home.update_price(sym, price, change)
        except Exception as e:
            self.logger.error(f"Error in price update: {e}")

    def on_strategy_update(self, out: StrategyOutput):
        try:
            self.page_strat.on_strategy_update(out)
            self.watch_details.push_strategy(out)
            self.logger.info(f"Strategy update: {out.symbol} - Score: {out.score}, Signal: {out.signal}")
        except Exception as e:
            self.logger.error(f"Error in strategy update: {e}")

    def on_position_event(self, evt: PositionEvent):
        self.page_pos.on_position_event(evt)

    def on_engine_event(self, kind: str, data: dict):
        if kind in ("STATUS", "RUNTIME_STATS"):
            st = data.get("status", "STOPPED")
            if st == "RUNNING":
                if data.get("protected"):
                    self.status_label.setText("الحالة: حماية")
                    self.bridge.bot_status_changed.emit("PROTECTED")
                else:
                    self.status_label.setText("الحالة: يعمل")
                    self.bridge.bot_status_changed.emit("RUNNING")
            elif st == "PAUSED":
                self.status_label.setText("الحالة: موقّف مؤقتاً")
                self.bridge.bot_status_changed.emit("PAUSED")
            else:
                self.status_label.setText("الحالة: متوقف")
                self.bridge.bot_status_changed.emit("STOPPED")

    def on_bot_status_changed(self, status: str):
        self.update_start_stop_button()

    def on_log_event(self, entry: LogEntry):
        self.page_logs.append_log(entry)
        self.page_home.append_log(entry.format())

    def on_market_status(self, status: str):
        if status == "connected":
            self.market_label.setText("السوق: متصل ✅")
        elif status == "reconnecting":
            self.market_label.setText("السوق: يعيد الاتصال...")
        else:
            self.market_label.setText("السوق: غير متصل ❌")


# =========================================================
# App entry
# =========================================================
def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()