# core/risk_manager.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logger import Logger
from core.settings_manager import SettingsManager
from core.state_manager import StateManager


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: Optional[str] = None


class RiskManager:
    """
    Guard rails فقط (Spot) - مرن أكثر
    """

    def __init__(
        self,
        settings_manager: SettingsManager,
        state_manager: StateManager,
        logger: Optional[Logger] = None,
    ) -> None:
        self.settings_manager = settings_manager
        self.state_manager = state_manager
        self.logger = logger or Logger()
        self.refresh_settings()
        self._load_meta()

    def refresh_settings(self) -> None:
        risk = self.settings_manager.get("risk_limits", {}) or {}
        self.max_open_trades = int(risk.get("max_open_trades", 5))
        self.max_trades_per_symbol = int(risk.get("max_trades_per_symbol", 2))
        self.daily_max_loss_pct = float(risk.get("daily_max_loss_pct", 10.0))
        self.daily_take_profit_pct = float(risk.get("daily_take_profit_pct", 10.0))
        self.loss_cooldown_min = int(risk.get("loss_cooldown_min", 5))
        self.reentry_delay_min = int(risk.get("reentry_delay_min", 10))

    def _load_meta(self) -> None:
        st = self.state_manager.get_state() or {}
        meta = st.get("risk_meta", {}) or {}
        self.last_loss_time = float(meta.get("last_loss_time", 0.0))
        self.last_closed_time_per_symbol: Dict[str, float] = dict(meta.get("last_closed_time_per_symbol", {}))

    def _save_meta(self) -> None:
        st = self.state_manager.get_state() or {}
        st["risk_meta"] = {
            "last_loss_time": self.last_loss_time,
            "last_closed_time_per_symbol": self.last_closed_time_per_symbol,
        }
        self.state_manager.update(**st)

    def check_new_position(
        self,
        symbol: str,
        last_price: float,
        exchange_balance_usdt: float,
        open_positions: List[Dict[str, Any]],
        realized_pnl_today: float,
        daily_start_equity: Optional[float] = None,
    ) -> RiskCheckResult:
        now = time.time()
        sym = str(symbol).upper().strip()

        # ✅ أبسط شروط فقط
        if self.loss_cooldown_min > 0 and (now - self.last_loss_time) < (self.loss_cooldown_min * 60):
            return RiskCheckResult(False, "LOSS_COOLDOWN_ACTIVE")

        last_close = float(self.last_closed_time_per_symbol.get(sym, 0.0))
        if self.reentry_delay_min > 0 and last_close > 0 and (now - last_close) < (self.reentry_delay_min * 60):
            return RiskCheckResult(False, "REENTRY_DELAY_ACTIVE")

        if self.max_open_trades > 0 and len(open_positions) >= self.max_open_trades:
            return RiskCheckResult(False, "MAX_OPEN_TRADES_REACHED")

        cnt_sym = 0
        for p in open_positions:
            if str(p.get("symbol", "")).upper() == sym:
                cnt_sym += 1
        if self.max_trades_per_symbol > 0 and cnt_sym >= self.max_trades_per_symbol:
            return RiskCheckResult(False, "SYMBOL_MAX_TRADES_REACHED")

        # ✅ نتجاهل شروط الربح/الخسارة اليومية مؤقتاً لكونها صارمة
        return RiskCheckResult(True, None)

    def on_position_closed(self, symbol: str, pnl_usdt: float, exit_reason: Optional[str] = None) -> None:
        sym = str(symbol).upper().strip()
        ts = time.time()
        self.last_closed_time_per_symbol[sym] = ts
        if pnl_usdt < 0:
            self.last_loss_time = ts
        self._save_meta()