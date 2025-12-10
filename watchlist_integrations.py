# ui/watchlist_integrations.py
from __future__ import annotations

from typing import Dict, Optional, Any
from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QTableWidget

from ui.coin_details_dialog import CoinDetailsDialog


class WatchlistDetailsController(QObject):
    def __init__(self, watchlist_table: QTableWidget):
        super().__init__()
        self.table = watchlist_table
        self.dialogs: Dict[str, CoinDetailsDialog] = {}

        self.table.cellDoubleClicked.connect(self._open_details_for_row)

    def _open_details_for_row(self, row: int, col: int):
        try:
            sym_item = self.table.item(row, 0)
            if not sym_item:
                return
            symbol = sym_item.text().strip().upper()
            if not symbol:
                return
        except Exception:
            return

        dlg = self.dialogs.get(symbol)
        if dlg is None:
            dlg = CoinDetailsDialog(symbol, parent=self.table.window())
            self.dialogs[symbol] = dlg

        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def push_price(self, symbol: str, price: float, change_pct: float):
        sym = symbol.upper()
        dlg = self.dialogs.get(sym)
        if dlg:
            dlg.update_price(sym, price, change_pct)

    def push_strategy(self, out: Any):
        """يقبل أي كائن له سمة symbol"""
        try:
            symbol = getattr(out, "symbol", "")
            if not symbol:
                return
            sym = symbol.upper()
            dlg = self.dialogs.get(sym)
            if dlg:
                dlg.update_strategy(out)
        except Exception as e:
            print(f"Error pushing strategy to watchlist: {e}")


def attach_watchlist_details(watchlist_table: QTableWidget) -> WatchlistDetailsController:
    return WatchlistDetailsController(watchlist_table)