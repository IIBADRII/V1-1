# ui/manual_close_dialog.py
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)


class ManualCloseDialog(QDialog):
    """
    نافذة الإغلاق اليدوي لصفقات البوت فقط.
    signature لازم يطابق اللي في main_window:
        ManualCloseDialog(open_positions, close_cb, parent=self)

    open_positions: list of dict positions
    close_cb(pid)->bool  (تنفذ الإغلاق وترجع True/False)
    """

    def __init__(
        self,
        open_positions: List[Dict[str, Any]],
        close_cb: Callable[[str], bool],
        parent=None
    ):
        super().__init__(parent)
        self.open_positions = open_positions or []
        self.close_cb = close_cb

        self.setWindowTitle("إغلاق يدوي لصفقات البوت")
        # ✅ زيدنا عرض النافذة
        self.resize(950, 520)
        self.setMinimumWidth(1100)

        # ✅ صغرنا الخط داخل النافذة فقط
        base_font = QFont("IBM Plex Sans Arabic", 9)
        self.setFont(base_font)

        self._build_ui()
        self._load_positions()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("اختر صفقة من صفقات البوت المفتوحة ثم اضغط (إغلاق)")
        title.setFont(QFont(self.font().family(), 9, QFont.Bold))
        root.addWidget(title)

        self.table = QTableWidget(0, 7)
        self.table.setFont(QFont(self.font().family(), 9))
        self.table.setHorizontalHeaderLabels([
            "العملة", "سعر الدخول", "السعر الحالي", "الكمية",
            "PnL USDT", "PnL %", "ID"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnHidden(6, True)  # نخفي الـ ID
        root.addWidget(self.table)

        btns = QHBoxLayout()
        btns.addStretch(1)

        self.btn_close = QPushButton("إغلاق الصفقة المحددة")
        self.btn_close.setFont(QFont(self.font().family(), 9, QFont.Bold))
        self.btn_close.setMinimumWidth(170)

        self.btn_cancel = QPushButton("إلغاء")
        self.btn_cancel.setFont(QFont(self.font().family(), 9))
        self.btn_cancel.setMinimumWidth(90)

        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_close.clicked.connect(self._on_close_clicked)
        self.table.itemDoubleClicked.connect(lambda *_: self._on_close_clicked())

    def _load_positions(self):
        self.table.setRowCount(0)
        for p in self.open_positions:
            # فقط صفقات البوت
            if (p.get("source") or "bot") != "bot":
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            sym = str(p.get("symbol", ""))
            entry = float(p.get("entry_price", 0.0) or 0.0)
            cur = float(p.get("current_price", entry) or entry)
            qty = float(p.get("qty", 0.0) or 0.0)
            pnl_u = float(p.get("pnl_usdt", 0.0) or 0.0)
            pnl_p = float(p.get("pnl_percent", 0.0) or 0.0)
            pid = str(p.get("id", ""))

            self.table.setItem(row, 0, QTableWidgetItem(sym))
            self.table.setItem(row, 1, QTableWidgetItem(f"{entry:.6f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{cur:.6f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{qty:.8f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{pnl_u:.4f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{pnl_p:.2f}%"))
            self.table.setItem(row, 6, QTableWidgetItem(pid))

            # تلوين الربح/الخسارة بشكل خفيف
            if pnl_u > 0:
                self.table.item(row, 4).setForeground(Qt.green)
                self.table.item(row, 5).setForeground(Qt.green)
            elif pnl_u < 0:
                self.table.item(row, 4).setForeground(Qt.red)
                self.table.item(row, 5).setForeground(Qt.red)

        if self.table.rowCount() == 0:
            empty = QLabel("لا توجد صفقات بوت مفتوحة حالياً.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setFont(QFont(self.font().family(), 9))
            # نضيفه مؤقتاً
            self.layout().addWidget(empty)

    def _selected_position_id(self) -> Optional[str]:
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()))
        if not rows:
            return None
        r = rows[0]
        item = self.table.item(r, 6)
        return item.text() if item else None

    def _on_close_clicked(self):
        pid = self._selected_position_id()
        if not pid:
            QMessageBox.warning(self, "تنبيه", "حدد صفقة أولاً.")
            return

        # تأكيد
        ok = QMessageBox.question(
            self,
            "تأكيد الإغلاق",
            "هل تريد إغلاق هذه الصفقة؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ok != QMessageBox.Yes:
            return

        try:
            success = bool(self.close_cb(pid))
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"فشل الإغلاق: {e}")
            return

        if success:
            QMessageBox.information(self, "تم", "تم إغلاق الصفقة ✅")
            # حذف الصف من الجدول
            for r in range(self.table.rowCount()):
                if self.table.item(r, 6) and self.table.item(r, 6).text() == pid:
                    self.table.removeRow(r)
                    break
        else:
            QMessageBox.warning(self, "فشل", "لم يتم إغلاق الصفقة (ربما لا يوجد سعر لحظي).")
