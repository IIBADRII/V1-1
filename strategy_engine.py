# core/strategy_engine.py
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable, Tuple

from core.logger import Logger
from core.settings_manager import SettingsManager
from core.market_data_manager import Candle


@dataclass
class StrategyOutput:
    symbol: str
    score: float
    signal: str  # "ENTRY" | "EXIT" | "HOLD"
    details: Dict[str, Any]


class StrategyEngine:
    """
    StrategyEngine - مع عتبات دخول أسهل
    """

    def __init__(self, settings: SettingsManager, logger: Optional[Logger] = None) -> None:
        self.settings = settings
        self.logger = logger or Logger()

        self.outputs: Dict[str, StrategyOutput] = {}

        # aliases for backward compatibility if any UI/old modules use them
        self.last_outputs = self.outputs
        self.cache = self.outputs
        self.latest_outputs = self.outputs
        self.signals_cache = self.outputs

        self._lock = threading.RLock()
        self._listeners: List[Callable[[StrategyOutput], None]] = []

        # trend snapshot from higher timeframe
        self._trend_1h: Dict[str, str] = {}

        self._load_settings()

    # ---------------------------
    # Listeners
    # ---------------------------
    def add_listener(self, callback: Callable[[StrategyOutput], None]) -> None:
        if not callable(callback):
            return
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[StrategyOutput], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, out: StrategyOutput) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(out)
            except Exception:
                pass

    # ---------------------------
    # Settings - مرن أكثر
    # ---------------------------
    def _load_settings(self) -> None:
        cfg = self.settings.get("strategy", {}) or {}

        self.enabled: bool = bool(cfg.get("enabled", True))

        self.entry_threshold: float = float(cfg.get("entry_score_threshold", 60.0))  # خفّضنا من 70
        self.exit_threshold: float = float(cfg.get("exit_score_threshold", 45.0))  # خفّضنا من 40
        self.smart_exit: bool = bool(cfg.get("smart_exit", True))

        self.rsi_period: int = int(cfg.get("rsi_period", 14))
        self.macd_fast: int = int(cfg.get("macd_fast", 12))
        self.macd_slow: int = int(cfg.get("macd_slow", 26))
        self.macd_signal: int = int(cfg.get("macd_signal", 9))
        self.ema_fast: int = int(cfg.get("ema_fast", 20))
        self.ema_slow: int = int(cfg.get("ema_slow", 50))
        self.bb_period: int = int(cfg.get("bb_period", 20))
        self.bb_stddev: float = float(cfg.get("bb_stddev", 2.0))

        # Weights (Score components)
        w = cfg.get("weights", {}) or {}
        self.weights = {
            "momentum": float(w.get("momentum", w.get("rsi", 30.0))),
            "trend": float(w.get("trend", w.get("ema_trend", 30.0))),
            "volatility": float(w.get("volatility", w.get("bollinger", 20.0))),
            "liquidity": float(w.get("liquidity", 20.0)),
            "macd": float(w.get("macd", 0.0)),
        }

        self.base_interval: str = str(cfg.get("base_interval", "15m")).lower()

        # أقل تاريخ مطلوب
        self._min_history = max(
            self.rsi_period + 1,
            self.bb_period,
            self.macd_slow + self.macd_signal + 5,
            self.ema_slow,
            40,
        )

    def refresh_settings(self) -> None:
        self._load_settings()

    # ---------------------------
    # Main update entry point
    # ---------------------------
    def on_kline_update(self, symbol: str, interval: str, candles: List[Candle]) -> None:
        try:
            if not self.enabled or not candles:
                return

            symbol = str(symbol).upper().strip()
            interval_l = str(interval).lower()

            closes = [float(c.close) for c in candles if getattr(c, "close", None) is not None]
            vols = [float(getattr(c, "volume", 0.0) or 0.0) for c in candles]

            if len(closes) < self._min_history:
                return

            last_close = closes[-1]

            rsi_val = self._calc_rsi(closes, self.rsi_period)
            ema_fast = self._ema(closes, self.ema_fast)
            ema_slow = self._ema(closes, self.ema_slow)
            macd_val, macd_sig, macd_hist = self._calc_macd(
                closes, self.macd_fast, self.macd_slow, self.macd_signal
            )
            bb_upper, bb_mid, bb_lower = self._calc_bollinger(closes, self.bb_period, self.bb_stddev)

            # update 1H trend memory
            if interval_l in ("1h", "60m", "60"):
                self._trend_1h[symbol] = self._describe_trend(last_close, ema_fast or last_close)
                return

            # only base interval produces outputs
            if interval_l != self.base_interval:
                return

            # states
            rsi_state = self._describe_rsi(rsi_val)
            macd_state = self._describe_macd(macd_val, macd_sig, macd_hist)
            ema_state = self._describe_ema(last_close, ema_fast, ema_slow)
            bb_state = self._describe_bb(last_close, bb_upper, bb_mid, bb_lower)

            # component scores
            liquidity_score = self._calc_volume_score(vols)
            momentum_score = self._score_momentum(rsi_val, macd_hist)
            trend_score = self._score_trend(last_close, ema_fast, ema_slow)
            volatility_score = self._score_volatility(last_close, bb_upper, bb_lower)

            # Combine
            extra_macd_weight = max(0.0, float(self.weights.get("macd", 0.0)))
            mom_weight = max(0.0, float(self.weights.get("momentum", 30.0))) + extra_macd_weight

            base_weights = {
                "momentum": mom_weight,
                "trend": float(self.weights.get("trend", 30.0)),
                "volatility": float(self.weights.get("volatility", 20.0)),
                "liquidity": float(self.weights.get("liquidity", 20.0)),
            }

            w_sum = sum(base_weights.values()) or 1.0

            score = (
                momentum_score * (base_weights["momentum"] / w_sum)
                + trend_score * (base_weights["trend"] / w_sum)
                + volatility_score * (base_weights["volatility"] / w_sum)
                + liquidity_score * (base_weights["liquidity"] / w_sum)
            )
            score = max(0.0, min(100.0, float(score)))

            signal = "HOLD"
            if score >= self.entry_threshold:
                signal = "ENTRY"
            elif score <= self.exit_threshold and self.smart_exit:
                signal = "EXIT"

            details: Dict[str, Any] = {
                "rsi": rsi_val,
                "rsi_state": rsi_state,
                "macd": macd_val,
                "macd_signal": macd_sig,
                "macd_hist": macd_hist,
                "macd_state": macd_state,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "ema_state": ema_state,
                "bb_upper": bb_upper,
                "bb_mid": bb_mid,
                "bb_lower": bb_lower,
                "bb_state": bb_state,
                "trend_1h": self._trend_1h.get(symbol, "--"),
                "score_components": {
                    "momentum": momentum_score,
                    "trend": trend_score,
                    "volatility": volatility_score,
                    "liquidity": liquidity_score,
                },
            }

            out = StrategyOutput(symbol=symbol, score=score, signal=signal, details=details)

            with self._lock:
                self.outputs[symbol] = out

            self._notify_listeners(out)

        except Exception as e:
            self.logger.log(f"StrategyEngine error for {symbol} {interval}: {e}", level="ERROR")

    # ---------------------------
    # Scoring
    # ---------------------------
    def _calc_volume_score(self, vols: List[float]) -> float:
        try:
            if not vols:
                return 50.0

            last = float(vols[-1])
            window = vols[-20:] if len(vols) >= 20 else vols
            avg = sum(window) / len(window) if window else last

            if avg <= 0:
                return 50.0

            ratio = last / avg
            score = 50.0 + (ratio - 1.0) * 40.0
            return max(0.0, min(100.0, score))
        except Exception:
            return 50.0

    def _score_momentum(self, rsi: Optional[float], macd_hist: Optional[float]) -> float:
        base = 50.0
        try:
            if rsi is not None:
                if 50 <= rsi <= 65:
                    base += 20
                elif 65 < rsi <= 75:
                    base += 10
                elif rsi < 35:
                    base -= 10
                elif rsi > 80:
                    base -= 5

            if macd_hist is not None:
                base += 15 if macd_hist > 0 else -10
        except Exception:
            pass

        return max(0.0, min(100.0, base))

    def _score_trend(self, price: float, ema_fast: Optional[float], ema_slow: Optional[float]) -> float:
        if not ema_fast or not ema_slow:
            return 50.0

        base = 50.0
        try:
            if ema_fast > ema_slow and price > ema_fast:
                base += 25
            elif ema_fast > ema_slow:
                base += 15
            elif ema_fast < ema_slow and price < ema_fast:
                base -= 20
            else:
                base -= 10
        except Exception:
            pass

        return max(0.0, min(100.0, base))

    def _score_volatility(self, price: float, bb_upper: Optional[float], bb_lower: Optional[float]) -> float:
        if not bb_upper or not bb_lower or bb_upper <= bb_lower:
            return 50.0
        try:
            pos = (price - bb_lower) / (bb_upper - bb_lower)
            if 0.35 <= pos <= 0.65:
                return 70.0
            if 0.2 <= pos < 0.35 or 0.65 < pos <= 0.8:
                return 55.0
            return 40.0
        except Exception:
            return 50.0

    # ---------------------------
    # Indicators
    # ---------------------------
    def _calc_rsi(self, closes: List[float], period: int) -> Optional[float]:
        try:
            if len(closes) < period + 1:
                return None

            gains = 0.0
            losses = 0.0
            for i in range(-period, 0):
                diff = closes[i] - closes[i - 1]
                if diff > 0:
                    gains += diff
                else:
                    losses -= diff

            if gains + losses == 0:
                return 50.0

            avg_gain = gains / period
            avg_loss = losses / period if losses > 0 else 0.0

            if avg_loss == 0:
                return 100.0

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return float(rsi)
        except Exception:
            return None

    def _ema(self, values: List[float], period: int) -> Optional[float]:
        try:
            if not values or period <= 1 or len(values) < period:
                return None

            k = 2 / (period + 1)
            ema = sum(values[:period]) / period
            for v in values[period:]:
                ema = v * k + ema * (1 - k)

            return float(ema)
        except Exception:
            return None

    def _calc_macd(
        self, closes: List[float], fast: int, slow: int, signal: int
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        try:
            ema_fast = self._ema(closes, fast)
            ema_slow = self._ema(closes, slow)
            if ema_fast is None or ema_slow is None:
                return None, None, None

            macd_line = ema_fast - ema_slow

            macd_series: List[float] = []
            for i in range(len(closes)):
                sub = closes[: i + 1]
                ef = self._ema(sub, fast)
                es = self._ema(sub, slow)
                if ef is None or es is None:
                    continue
                macd_series.append(ef - es)

            sig = self._ema(macd_series, signal) if macd_series else None
            hist = macd_line - sig if sig is not None else None

            return (
                float(macd_line),
                float(sig) if sig is not None else None,
                float(hist) if hist is not None else None,
            )
        except Exception:
            return None, None, None

    def _calc_bollinger(
        self, closes: List[float], period: int, stddev: float
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        try:
            if len(closes) < period:
                return None, None, None

            window = closes[-period:]
            mean = sum(window) / period
            var = sum((x - mean) ** 2 for x in window) / period
            sd = var ** 0.5

            upper = mean + stddev * sd
            lower = mean - stddev * sd

            return float(upper), float(mean), float(lower)
        except Exception:
            return None, None, None

    # ---------------------------
    # Describers
    # ---------------------------
    def _describe_rsi(self, rsi: Optional[float]) -> str:
        if rsi is None:
            return "--"
        if rsi >= 70:
            return "Overbought"
        if rsi <= 30:
            return "Oversold"
        if rsi >= 55:
            return "Bullish"
        if rsi <= 45:
            return "Bearish"
        return "Neutral"

    def _describe_macd(self, macd: Optional[float], sig: Optional[float], hist: Optional[float]) -> str:
        if macd is None or sig is None or hist is None:
            return "--"
        if hist > 0 and macd > sig:
            return "Bullish"
        if hist < 0 and macd < sig:
            return "Bearish"
        return "Neutral"

    def _describe_ema(self, price: float, ema_fast: Optional[float], ema_slow: Optional[float]) -> str:
        if ema_fast is None or ema_slow is None:
            return "--"
        if price > ema_fast > ema_slow:
            return "Bull Trend"
        if price < ema_fast < ema_slow:
            return "Bear Trend"
        if ema_fast > ema_slow:
            return "Rising"
        return "Falling"

    def _describe_bb(
        self, price: float, upper: Optional[float], mid: Optional[float], lower: Optional[float]
    ) -> str:
        if upper is None or lower is None:
            return "--"
        if price >= upper:
            return "Upper Break"
        if price <= lower:
            return "Lower Break"
        return "Inside"

    def _describe_trend(self, price: float, ema: float) -> str:
        return "UP" if price >= ema else "DOWN"

    # ---------------------------
    # Public methods for UI
    # ---------------------------
    def get_outputs(self) -> Dict[str, StrategyOutput]:
        """ترجع نسخة من الإشارات الحالية للعرض في الواجهة."""
        with self._lock:
            return self.outputs.copy()

    def get_symbol_output(self, symbol: str) -> Optional[StrategyOutput]:
        with self._lock:
            return self.outputs.get(str(symbol).upper().strip())

    def clear_cache(self) -> None:
        with self._lock:
            self.outputs.clear()
            self._trend_1h.clear()

    def force_calculate_for_symbol(self, symbol: str, market_data) -> None:
        """
        يجبر إعادة حساب الإشارات لرمز معين.
        """
        try:
            candles = market_data.get_candles(symbol, self.base_interval)
            if candles:
                self.on_kline_update(symbol, self.base_interval, candles)
        except Exception as e:
            self.logger.log(f"Force calculate error for {symbol}: {e}", level="ERROR")