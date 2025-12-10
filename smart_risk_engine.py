# core/smart_risk_engine.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.logger import Logger
from core.settings_manager import SettingsManager
from core.state_manager import StateManager
from core.position_manager import PositionManager


@dataclass
class SymbolStats:
    symbol: str
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    avg_pnl_usdt: float = 0.0
    win_rate: float = 0.0
    max_loss_usdt: float = 0.0
    last_pnl_usdt: float = 0.0
    last_updated_ts: float = 0.0


class SmartRiskEngine:
    """
    SmartRiskEngine V8 (Hybrid / Explainable)

    يحول StrategyOutput.score + details إلى:
    - حجم صفقة ديناميكي
    - SL/TP/Trailing ديناميكية
    مع أخذ الأداء التاريخي للرمز بعين الاعتبار.

    هذا ليس ML ثقيل، لكنه "تعلم تكيّفي" عبر تعديل عوامل الثقة.
    """

    def __init__(
        self,
        settings: SettingsManager,
        state: StateManager,
        positions: PositionManager,
        logger: Optional[Logger] = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.positions = positions
        self.logger = logger or Logger()
        self._symbol_stats: Dict[str, SymbolStats] = {}

    def _clamp(self, x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    def _get_float(self, d: Dict[str, Any], k: str, default: float = 0.0) -> float:
        try:
            v = d.get(k, default)
            return float(v) if v is not None else float(default)
        except Exception:
            return float(default)

    def _compute_symbol_stats(self, symbol: str) -> SymbolStats:
        sym = symbol.upper()
        closed = self.positions.get_closed_positions()
        total = 0
        wins = 0
        losses = 0
        pnl_sum = 0.0
        max_loss = 0.0
        last_pnl = 0.0

        for p in closed:
            try:
                if str(p.get("symbol", "")).upper() != sym:
                    continue
                if p.get("source") != "bot":
                    continue
                total += 1
                pnl = float(p.get("pnl_usdt", 0.0) or 0.0)
                pnl_sum += pnl
                last_pnl = pnl
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                    max_loss = min(max_loss, pnl)
            except Exception:
                continue

        avg = pnl_sum / total if total > 0 else 0.0
        win_rate = (wins / total) if total > 0 else 0.0

        st = SymbolStats(
            symbol=sym,
            total_trades=total,
            win_trades=wins,
            loss_trades=losses,
            avg_pnl_usdt=float(avg),
            win_rate=float(win_rate),
            max_loss_usdt=float(max_loss),
            last_pnl_usdt=float(last_pnl),
            last_updated_ts=time.time(),
        )
        self._symbol_stats[sym] = st
        return st

    def _compute_performance_factor(self, stats: SymbolStats) -> float:
        f = 1.0
        try:
            if stats.total_trades >= 5:
                f += (stats.win_rate - 0.5) * 0.6
                if stats.avg_pnl_usdt > 0:
                    f += self._clamp(stats.avg_pnl_usdt / 20.0, 0.0, 0.15)
                else:
                    f -= self._clamp(abs(stats.avg_pnl_usdt) / 20.0, 0.0, 0.15)
        except Exception:
            pass
        return self._clamp(f, 0.7, 1.25)

    def _compute_confidence_factor(self, score: float) -> float:
        if score <= 0:
            return 0.5
        f = 0.5 + (score / 100.0) * 0.7
        return self._clamp(f, 0.5, 1.2)

    def _compute_volatility_factor(self, details: Dict[str, Any]) -> float:
        try:
            up = self._get_float(details, "bb_upper", 0.0)
            lo = self._get_float(details, "bb_lower", 0.0)
            mid = self._get_float(details, "bb_mid", 0.0)
            if up > 0 and lo > 0 and mid > 0 and up > lo:
                width = (up - lo) / mid
                f = 1.0 - self._clamp(width * 1.5, 0.0, 0.25)
                return self._clamp(f, 0.75, 1.05)
        except Exception:
            pass
        return 1.0

    def _compute_sl_tp_trailing(self, score: float, details: Dict[str, Any]) -> Dict[str, float]:
        sl = 1.2
        rr = 1.6

        ema_state = str(details.get("ema_state", "") or "")
        if "Bull" in ema_state or "Rising" in ema_state:
            rr += 0.2
        elif "Bear" in ema_state or "Falling" in ema_state:
            rr -= 0.2

        if score >= 85:
            sl = 0.9
            rr += 0.5
        elif score >= 75:
            sl = 1.0
            rr += 0.3
        elif score >= 65:
            sl = 1.1
            rr += 0.1
        else:
            sl = 1.3
            rr -= 0.1

        sl = self._clamp(sl, 0.7, 1.8)
        rr = self._clamp(rr, 1.2, 2.8)

        tp = sl * rr

        trailing = 0.0
        if score >= 70:
            trailing = self._clamp(sl * 0.7, 0.4, 1.2)

        return {"sl_pct": float(sl), "tp_pct": float(tp), "trailing_sl_pct": float(trailing)}

    def suggest_for_entry(
        self,
        symbol: str,
        strategy_output: Any,
        equity: float,
        mode: str = "paper",
    ) -> Dict[str, Any]:
        sym = str(symbol).upper()

        try:
            score = float(getattr(strategy_output, "score", 0.0) or 0.0)
        except Exception:
            score = 0.0

        details: Dict[str, Any] = {}
        try:
            details = getattr(strategy_output, "details", {}) or {}
            if not isinstance(details, dict):
                details = {}
        except Exception:
            details = {}

        stats = self._compute_symbol_stats(sym)
        perf_factor = self._compute_performance_factor(stats)
        conf_factor = self._compute_confidence_factor(score)
        vol_factor = self._compute_volatility_factor(details)

        base_pct = 0.06
        if score >= 90:
            base_pct = 0.12
        elif score >= 80:
            base_pct = 0.10
        elif score >= 70:
            base_pct = 0.08
        elif score >= 60:
            base_pct = 0.06
        else:
            base_pct = 0.04

        pct = base_pct * perf_factor * conf_factor * vol_factor
        pct = self._clamp(pct, 0.02, 0.14)

        trade_amount = float(equity) * pct

        last_price = 0.0
        try:
            last_price = float(details.get("last_price", 0.0) or 0.0)
        except Exception:
            last_price = 0.0

        qty = (trade_amount / last_price) if last_price > 0 else 0.0

        sltp = self._compute_sl_tp_trailing(score, details)

        return {
            "symbol": sym,
            "score": float(score),
            "confidence_factor": float(conf_factor),
            "performance_factor": float(perf_factor),
            "volatility_factor": float(vol_factor),

            "trade_amount_usdt": float(trade_amount),
            "qty": float(qty),

            "sl_pct": float(sltp["sl_pct"]),
            "tp_pct": float(sltp["tp_pct"]),
            "trailing_sl_pct": float(sltp["trailing_sl_pct"]),

            "meta": {
                "score_components": details.get("score_components", {}),
                "stats": stats.__dict__,
                "pct": float(pct),
            },
        }
