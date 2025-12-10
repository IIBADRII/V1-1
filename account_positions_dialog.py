# ui/account_positions_dialog.py
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)


class AccountPositionsDialog(QDialog):
    """
    نافذة مراكز الحساب (Spot) مع إمكانية:
    - استعراض رموز الحساب (USDT فقط)
    - نقل الصفقة المحددة إلى مراكز البوت (adopt_account_position)

    positions: dict[symbol -> AccountPosition أو dict]
    adopt_cb: دالة تستقبل symbol وترجع bool (نجاح/فشل)
    """

    def __init__(
        self,
        positions: Dict[str, Any],
        adopt_cb: Callable[[str], bool],
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)

        self.positions: Dict[str, Any] = positions or {}
        self.adopt_cb = adopt_cb

        self.setWindowTitle("مراكز الحساب (Spot)")
        self.resize(900, 500)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ---------------- هيدر + أزرار ----------------
        header_layout = QHBoxLayout()
        title_label = QLabel("مراكز الحساب (Spot)")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)

        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # زر نقل الصفقة المحددة للبوت
        self.btn_adopt = QPushButton("نقل الصفقة المحددة للبوت")
        self.btn_adopt.setToolTip("ينقل الصفقة المحددة إلى مراكز البوت ليتم التحكم فيها.")
        self.btn_adopt.clicked.connect(self._on_adopt_clicked)

        header_layout.addWidget(self.btn_adopt)

        main_layout.addLayout(header_layout)

        # ---------------- الجدول ----------------
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "الرمز",          # 0
            "الكمية",         # 1
            "المتاح (Free)",  # 2
            "سعر الدخول",     # 3
            "آخر سعر",        # 4
            "القيمة USDT",    # 5
            "الربح USDT",     # 6
            "الربح %"         # 7
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)

        main_layout.addWidget(self.table)

        # تعبئة الجدول
        self._populate_table()

    # -------------------------------------------------
    # تعبئة الجدول من dict positions
    # -------------------------------------------------
    def _populate_table(self) -> None:
        rows = []

        # positions: dict [symbol -> dataclass AccountPosition أو dict]
        for sym, pos in self.positions.items():
            try:
                asset = getattr(pos, "asset", getattr(pos, "symbol", sym))
                symbol = getattr(pos, "symbol", sym)

                qty = float(getattr(pos, "qty", 0.0) or 0.0)
                free = float(getattr(pos, "free", 0.0) or 0.0)
                entry = float(getattr(pos, "entry_price", 0.0) or 0.0)
                last = float(getattr(pos, "last_price", 0.0) or 0.0)
                value = float(getattr(pos, "value_usdt", 0.0) or 0.0)
                pnl_usdt = float(getattr(pos, "pnl_usdt", 0.0) or 0.0)
                pnl_pct = float(getattr(pos, "pnl_percent", 0.0) or 0.0)
            except Exception:
                # في حال كان pos dict عادي
                d = pos if isinstance(pos, dict) else {}
                symbol = d.get("symbol", sym)
                qty = float(d.get("qty", 0.0) or 0.0)
                free = float(d.get("free", 0.0) or 0.0)
                entry = float(d.get("entry_price", 0.0) or 0.0)
                last = float(d.get("last_price", 0.0) or 0.0)
                value = float(d.get("value_usdt", 0.0) or 0.0)
                pnl_usdt = float(d.get("pnl_usdt", 0.0) or 0.0)
                pnl_pct = float(d.get("pnl_percent", 0.0) or 0.0)

            rows.append((
                symbol,
                qty,
                free,
                entry,
                last,
                value,
                pnl_usdt,
                pnl_pct,
            ))

        # ترتيب حسب الرمز
        rows.sort(key=lambda r: r[0])

        self.table.setRowCount(len(rows))

        for row, data in enumerate(rows):
            symbol, qty, free, entry, last, value, pnl_usdt, pnl_pct = data

            def _item(text: str) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter)
                return it

            self.table.setItem(row, 0, _item(str(symbol)))
            self.table.setItem(row, 1, _item(f"{qty:.6f}"))
            self.table.setItem(row, 2, _item(f"{free:.6f}"))
            self.table.setItem(row, 3, _item(f"{entry:.6f}" if entry > 0 else "-"))
            self.table.setItem(row, 4, _item(f"{last:.6f}" if last > 0 else "-"))
            self.table.setItem(row, 5, _item(f"{value:.2f}"))

            # الربح/الخسارة
            pnl_item = _item(f"{pnl_usdt:.2f}")
            if pnl_usdt > 0:
                pnl_item.setForeground(Qt.green)
            elif pnl_usdt < 0:
                pnl_item.setForeground(Qt.red)
            self.table.setItem(row, 6, pnl_item)

            pnl_pct_item = _item(f"{pnl_pct:.2f}%")
            if pnl_pct > 0:
                pnl_pct_item.setForeground(Qt.green)
            elif pnl_pct < 0:
                pnl_pct_item.setForeground(Qt.red)
            self.table.setItem(row, 7, pnl_pct_item)

    # -------------------------------------------------
    # زر "نقل الصفقة المحددة للبوت"
    # -------------------------------------------------
    def _on_adopt_clicked(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "تنبيه", "رجاءً اختر صفقة من الجدول أولاً.")
            return

        sym_item = self.table.item(row, 0)
        if not sym_item:
            QMessageBox.warning(self, "خطأ", "تعذر قراءة الرمز من الصف المحدد.")
            return

        symbol = sym_item.text().strip()
        if not symbol:
            QMessageBox.warning(self, "خطأ", "الرمز غير صالح.")
            return

        reply = QMessageBox.question(
            self,
            "تأكيد",
            f"هل تريد نقل صفقة {symbol} إلى مراكز البوت؟\n"
            f"سيبدأ البوت بإدارتها كصفقة manual/live.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            ok = bool(self.adopt_cb(symbol))
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"فشل نقل الصفقة:\n{e}")
            return

        if ok:
            QMessageBox.information(self, "تم", "تم نقل الصفقة إلى مراكز البوت ✅")
            # بإمكانك إما إغلاق النافذة أو تركها مفتوحة
            # هنا نكتفي فقط بإعلام المستخدم
        else:
            QMessageBox.warning(
                self,
                "فشل",
                "لم يتم نقل الصفقة.\n"
                "تحقق من أن البوت في وضع LIVE وأن الرمز موجود في مراكز الحساب."
            )
