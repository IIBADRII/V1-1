# core/ai_orchestrator.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AITradeDecision:
    symbol: str
    action: str = "HOLD"  # ENTRY | EXIT | HOLD
    score: float = 0.0
    signal: str = "HOLD"
    requested_trade_usdt: float = 0.0
    sl_pct: Optional[float] = None
    tp_pct: Optional[float] = None
    use_trailing: bool = False
    trailing_sl_pct: float = 0.0
    reason_tags: List[str] = field(default_factory=list)
    reject_reason: Optional[str] = None
    debug: Dict[str, Any] = field(default_factory=dict)


class AIOrchestrator:
    """
    AI Orchestrator (Flexible Gate v3) - مرن أكثر
    """
    
    def __init__(
        self,
        settings,
        state,
        market,
        strategy,
        mtf=None,
        logger=None,
        engine_start_ts: Optional[float] = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.market = market
        self.strategy = strategy
        self.mtf = mtf
        self.logger = logger

        # -------- Performance / caching --------
        self._last_eval_ts: Dict[str, float] = {}
        self._last_decision_cache: Dict[str, AITradeDecision] = {}

        # -------- Warmup --------
        self._boot_ts = engine_start_ts or time.time()

    # =========================================================
    # Settings readers (safe)
    # =========================================================

    def _get(self, key: str, default: Any) -> Any:
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    def _ai_conf(self) -> Dict[str, Any]:
        try:
            c = self.settings.get("ai", {}) or {}
            if isinstance(c, dict):
                return c
        except Exception:
            pass
        return {}

    def _conf_val(self, dotted: str, default: Any) -> Any:
        ai = self._ai_conf()
        sub_key = dotted.replace("ai.", "")
        if sub_key in ai:
            return ai.get(sub_key, default)
        return self._get(dotted, default)

    def set_engine_start_ts(self, ts: float) -> None:
        """للتحديث من TradingEngine"""
        self._boot_ts = ts

    # =========================================================
    # Public hooks
    # =========================================================

    def on_trade_closed(self, symbol: str, pnl_usdt: float) -> None:
        return

    # =========================================================
    # Main evaluation - مرن أكثر
    # =========================================================

    def evaluate_symbol(self, symbol: str) -> AITradeDecision:
        sym = str(symbol).upper().strip()

        # ---------- Eval cooldown to reduce heavy load ----------
        cooldown = float(self._conf_val("ai.eval_cooldown_sec", 2.0) or 2.0)
        now = time.time()
        last_ts = float(self._last_eval_ts.get(sym, 0.0))
        if cooldown > 0 and (now - last_ts) < cooldown:
            cached = self._last_decision_cache.get(sym)
            if cached:
                return cached
        self._last_eval_ts[sym] = now

        # ---------- Strategy output ----------
        outputs = getattr(self.strategy, "outputs", None) or {}
        out = outputs.get(sym)

        # لو ما فيه مخرجات بعد
        if not out:
            d = AITradeDecision(
                symbol=sym,
                action="HOLD",
                score=0.0,
                signal="HOLD",
                reject_reason="NO_STRATEGY_OUTPUT_YET",
            )
            self._last_decision_cache[sym] = d
            return d

        # استخراج آمن للحقول المحتملة
        signal = str(getattr(out, "signal", "HOLD") or "HOLD").upper()
        score = float(getattr(out, "score", 0.0) or 0.0)

        # مرن أكثر: نأخذ أي إشارة موجبة
        valid_count = 1
        
        reason_tags: List[str] = []
        try:
            rt = getattr(out, "reason_tags", None)
            if isinstance(rt, list):
                reason_tags = [str(x) for x in rt]
        except Exception:
            pass

        # ---------- MTF summary (optional) ----------
        mtf_ok = True

        # ---------- Flexible gate config - مرن أكثر ----------
        min_score_base = float(self._conf_val("ai.min_score", 0.40) or 0.40)
        min_signals_base = int(self._conf_val("ai.min_valid_signals", 1) or 1)

        # SL/TP defaults أكثر مرونة
        default_sl = self._conf_val("ai.default_sl_pct", 2.0)
        default_tp = self._conf_val("ai.default_tp_pct", 3.0)
        default_trailing = self._conf_val("ai.default_trailing_sl_pct", 1.0)

        # Trade size
        trade_usdt = float(self._conf_val("ai.trade_usdt", 10.0) or 10.0)
        trade_usdt_min = float(self._conf_val("ai.trade_usdt_min", 2.0) or 2.0)
        trade_usdt_max = float(self._conf_val("ai.trade_usdt_max", 30.0) or 30.0)
        trade_usdt = max(trade_usdt_min, min(trade_usdt, trade_usdt_max))

        # ---------- Warmup relaxed logic - فترة أقل ----------
        warmup_sec = float(self._conf_val("ai.warmup_relax_sec", 300.0) or 300.0)
        elapsed = now - self._boot_ts

        relaxed = elapsed < warmup_sec

        # أثناء warmup: نكون أكثر مرونة
        min_score = min_score_base
        min_signals = min_signals_base

        if relaxed:
            relax_score_delta = float(self._conf_val("ai.warmup_relax_score_delta", 0.10) or 0.10)
            min_score = max(0.0, min_score_base - relax_score_delta)

        # ---------- Build decision skeleton ----------
        d = AITradeDecision(
            symbol=sym,
            score=score,
            signal=signal,
            reason_tags=reason_tags,
            requested_trade_usdt=trade_usdt,
            sl_pct=float(getattr(out, "sl_pct", 0.0) or 0.0) or float(default_sl or 0.0) or None,
            tp_pct=float(getattr(out, "tp_pct", 0.0) or 0.0) or float(default_tp or 0.0) or None,
            use_trailing=bool(getattr(out, "use_trailing", False) or False),
            trailing_sl_pct=float(getattr(out, "trailing_sl_pct", 0.0) or 0.0) or float(default_trailing or 0.0),
        )

        # لو الاستراتيجية ما حددت use_trailing و فيه default ملموس
        if d.trailing_sl_pct and d.trailing_sl_pct > 0:
            d.use_trailing = bool(d.use_trailing)

        # ---------- EXIT logic ----------
        if signal in ("EXIT", "SELL", "CLOSE"):
            d.action = "EXIT"
            d.reject_reason = None
            self._last_decision_cache[sym] = d
            return d

        # ---------- ENTRY candidate gating - مرن أكثر ----------
        entry_signals = {"ENTRY", "BUY", "LONG"}
        if signal not in entry_signals:
            d.action = "HOLD"
            d.reject_reason = "STRATEGY_SIGNAL_NOT_ENTRY"
            self._last_decision_cache[sym] = d
            return d

        # شرط السكور - مرن أكثر
        if score < min_score:
            d.action = "HOLD"
            d.reject_reason = "SCORE_BELOW_MIN"
            self._last_decision_cache[sym] = d
            return d

        # شرط عدد الإشارات - مرن أكثر
        if valid_count < min_signals:
            d.action = "HOLD"
            d.reject_reason = "NOT_ENOUGH_VALID_SIGNALS"
            self._last_decision_cache[sym] = d
            return d

        # ---------- Passed gates ----------
        d.action = "ENTRY"
        d.reject_reason = None

        self._last_decision_cache[sym] = d
        return d