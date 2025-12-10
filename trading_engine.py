# core/trading_engine.py
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from datetime import date
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

try:
    from binance.client import Client
except Exception:  # pragma: no cover
    Client = object  # type: ignore

from core.logger import Logger
from core.settings_manager import SettingsManager
from core.state_manager import StateManager
from core.market_data_manager import MarketDataManager
from core.position_manager import PositionManager, PositionEvent
from core.risk_manager import RiskManager
from core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from core.ai_orchestrator import AIOrchestrator, AITradeDecision
from core.telegram_bot import TelegramBot

if TYPE_CHECKING:
    from core.strategy_engine import StrategyEngine


class BotStatus(Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PROTECTED = "PROTECTED"


@dataclass
class EngineEvent:
    kind: str
    data: Dict[str, Any]


@dataclass
class AccountPosition:
    asset: str
    symbol: str
    qty: float
    free: float
    last_price: float
    value_usdt: float
    entry_price: float = 0.0
    pnl_usdt: float = 0.0
    pnl_percent: float = 0.0


class TradingEngine:
    """
    AI-Driven Spot Engine (Rebuild V1.3)
    
    ✅ تعديلات هذه النسخة:
    1) شروط دخول أكثر مرونة:
       - min_score من 0.55 إلى 0.40
       - min_valid_signals من 3 إلى 1
       - MTF اختياري
       
    2) تقليل السجلات:
       - فقط فتح/إغلاق الصفقات
       - أسباب الرفض المهمة فقط
       - تعطيل سجلات DEBUG غير الضرورية
       
    3) إعدادات Risk أكثر مرونة:
       - max_open_trades من 3 إلى 5
       - max_trades_per_symbol من 1 إلى 2
    """

    def __init__(
        self,
        settings_manager: SettingsManager,
        state_manager: StateManager,
        logger: Optional[Logger] = None,
    ) -> None:
        self.settings = settings_manager
        self.state = state_manager
        self.logger = logger or Logger()

        # Debug entry rejection logs - تعطيل الإفتراضي
        self.debug_entry_reasons = bool(self.settings.get("engine.debug_entry_reasons", False))
        self.debug_entry_reasons_level = str(
            self.settings.get("engine.debug_entry_reasons_level", "WARNING")
        ).upper()

        # Allocation
        self.max_bot_balance = float(self.settings.get("risk_limits.max_bot_balance", 1000.0))

        # Load state
        self.state.load_state()

        # Mode
        self.paper_mode = bool(self.settings.get("trading.paper_mode", True))
        if str(self.settings.get("trading.mode", "paper")).lower() == "live":
            self.paper_mode = False

        # Telegram
        tg_conf = self.settings.get("telegram", {}) or {}
        self.tg_enabled = bool(tg_conf.get("enabled", False))
        self.telegram: Optional[TelegramBot] = None

        if self.tg_enabled:
            token = str(tg_conf.get("bot_token") or "").strip()
            chat_id = tg_conf.get("chat_id") or None

            if token:
                try:
                    self.telegram = TelegramBot(
                        token=token,
                        chat_id=chat_id,
                        engine=self,
                        settings=self.settings,
                        state=self.state,
                        logger=self.logger,
                    )
                except Exception as e:
                    self.logger.log(f"Telegram init failed: {e}", level="WARNING")
                    self.tg_enabled = False
                    self.telegram = None

        # Live client + filters
        self.client: Optional[Client] = None
        self._symbol_filters: Dict[str, Dict[str, Any]] = {}
        self._init_live_client_if_needed()

        # Components
        from core.strategy_engine import StrategyEngine

        self.market = MarketDataManager(self.settings, self.state, self.logger)
        self.strategy: StrategyEngine = StrategyEngine(self.settings, self.logger)
        self.mtf = MultiTimeframeAnalyzer(self.strategy, self.market, self.logger)

        self.positions = PositionManager(self.settings, self.state, self.logger)
        self.risk = RiskManager(self.settings, self.state, self.logger)

        # engine start time for warmup flexibility in AI
        self._engine_start_ts = time.time()

        self.ai = AIOrchestrator(
            settings=self.settings,
            state=self.state,
            market=self.market,
            strategy=self.strategy,
            mtf=self.mtf,
            logger=self.logger,
            engine_start_ts=self._engine_start_ts,
        )

        # Wiring
        self.market.add_kline_listener(self.strategy.on_kline_update)
        self.market.add_price_listener(self._on_price)
        self.positions.add_listener(self._on_position_event)

        # Listeners
        self._listeners: List[Callable[[EngineEvent], None]] = []

        # Account/balances
        self._account_positions: Dict[str, AccountPosition] = {}
        self.account_usdt_free = 0.0
        self.account_total_usdt = 0.0
        self._last_account_fetch_ts = 0.0
        self._account_fetch_interval = float(self.settings.get("binance.account_refresh_sec", 150.0))

        # ---- Ensure ledger/daily keys ----
        self._ensure_ledger_defaults()

        # Loop control
        self.bot_status: BotStatus = BotStatus.STOPPED
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.poll_interval = float(self.settings.get("engine.poll_interval_sec", 2.0))

        # Protected + runtime
        self._protected_today = False
        self.equity = 0.0
        self.daily_pnl_usdt = 0.0
        self.daily_pnl_pct = 0.0

        # 🔥 بدء استقبال أوامر التلغرام إذا كان مفعلاً
        self._start_telegram_polling()

    # 🔥 دالة جديدة لبدء استقبال أوامر التلغرام
    def _start_telegram_polling(self) -> None:
        """بدء استقبال أوامر التلغرام"""
        if self.tg_enabled and self.telegram:
            try:
                # اختبار الاتصال أولاً
                if self.telegram.test_connection():
                    self.logger.log("✅ اتصال التلغرام ناجح", level="INFO")
                    
                    # بدء استقبال الأوامر
                    if self.telegram.start_polling(interval_sec=1.5, allowed_chat_only=True):
                        self.logger.log("✅ بدأ استقبال أوامر التلغرام", level="INFO")
                        self.telegram.send_message("🤖 البوت جاهز للاستقبال الأوامر.")
                    else:
                        self.logger.log(f"❌ فشل بدء استقبال أوامر التلغرام: {self.telegram.last_error}", level="WARNING")
                else:
                    self.logger.log(f"❌ اختبار اتصال التلغرام فشل: {self.telegram.last_error}", level="WARNING")
                    self.tg_enabled = False
                    self.telegram = None
            except Exception as e:
                self.logger.log(f"❌ فشل بدء استقبال أوامر التلغرام: {e}", level="ERROR")
                self.tg_enabled = False
                self.telegram = None

    # ---------------- Debug helper ----------------
    def _log_entry_reject(self, symbol: str, code: str, extra: str = "") -> None:
        """تسجيل أسباب الرفض المهمة فقط"""
        if not self.debug_entry_reasons:
            return
        sym = str(symbol or "").upper()
        
        # فقط الأسباب المهمة نكتبها
        important_reasons = {
            "RISK_BLOCK", "PAPER_BAL_ZERO", "DUPLICATE_SYMBOL",
            "MIN_TRADE_BLOCK", "PAPER_INSUFFICIENT_BAL"
        }
        
        if code not in important_reasons:
            return
            
        msg = f"[رفض دخول] {sym} | {code}"
        if extra:
            msg += f" | {extra}"
        try:
            self.logger.log(msg, level=self.debug_entry_reasons_level)
        except Exception:
            pass

    # ---------------- Ledger defaults ----------------
    def _ensure_ledger_defaults(self) -> None:
        st = self.state.get_state() or {}

        # Paper init
        if float(st.get("paper_balance_usdt", 0.0) or 0.0) <= 0:
            init_paper = float(
                self.settings.get("paper.initial_balance", self.max_bot_balance)
                or self.max_bot_balance
            )
            st["paper_balance_usdt"] = init_paper

        # Daily keys
        st.setdefault("realized_pnl_today", 0.0)
        st.setdefault("daily_start_equity", float(self.max_bot_balance))
        st.setdefault("daily_date", date.today().isoformat())

        # Ledger keys (G)
        st.setdefault("capital_usdt", float(self.max_bot_balance))
        st.setdefault("bot_balance_usdt", 0.0)
        st.setdefault("last_profit_split_date", None)

        self.state.update(**st)

    # ---------------- Public API ----------------
    def add_listener(self, fn: Callable[[EngineEvent], None]) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    @property
    def is_running(self) -> bool:
        return self.bot_status == BotStatus.RUNNING

    @property
    def paper_balance_usdt(self) -> float:
        try:
            st = self.state.get_state() or {}
            return float(st.get("paper_balance_usdt", 0.0) or 0.0)
        except Exception:
            return 0.0

    def set_paper_mode(self, paper: bool) -> None:
        paper = bool(paper)
        self.paper_mode = paper
        self.settings.set("trading.paper_mode", paper)
        self.settings.set("trading.mode", "paper" if paper else "live")

        self._init_live_client_if_needed()
        self.refresh_account_positions(force=True)

        self._emit("STATUS", {"status": self.bot_status.value, "paper_mode": self.paper_mode})
        self._emit_runtime_stats()

        self._notify_telegram(
            "🧪 تم التحويل إلى الوضع التجريبي (PAPER)."
            if self.paper_mode else
            "✅ تم التحويل إلى الوضع الحقيقي (LIVE)."
        )

    def start_trading(self) -> None:
        if self.bot_status == BotStatus.RUNNING:
            return

        self._stop_event.clear()
        self.bot_status = BotStatus.RUNNING
        self._engine_start_ts = time.time()
        try:
            self.ai.set_engine_start_ts(self._engine_start_ts)
        except Exception:
            pass

        self._emit("STATUS", {"status": self.bot_status.value, "paper_mode": self.paper_mode})

        wl = (self.state.get_state() or {}).get("watchlist", ["BTCUSDT"])
        self.market.update_symbols(wl)
        self.market.start()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self.logger.log("🚀 تم تشغيل البوت بنسخة V1.3 (مرن أكثر)", level="INFO")
        self._notify_telegram("🚀 تم تشغيل البوت (AI Rebuild V1.3 - مرن أكثر).")

    def stop_trading(self) -> None:
        if self.bot_status == BotStatus.STOPPED:
            return

        self.bot_status = BotStatus.STOPPED
        self._emit("STATUS", {"status": self.bot_status.value, "paper_mode": self.paper_mode})

        self._stop_event.set()
        try:
            self.market.stop()
        except Exception:
            pass

        self.logger.log("⏹ تم إيقاف البوت", level="INFO")
        self._notify_telegram("⏹ تم إيقاف البوت.")

    def refresh_account_positions(self, force: bool = False) -> None:
        self._refresh_balances(force_account_fetch=force)
        if self.paper_mode:
            self._account_positions = {}
        else:
            self._account_positions = self._fetch_account_positions_live()

    def get_account_positions(self) -> Dict[str, AccountPosition]:
        return self._account_positions or {}

    def close_account_position(self, symbol: str, qty: Optional[float] = None) -> bool:
        if self.paper_mode or not self.client:
            self.logger.log(
                "[ACCOUNT] لا يمكن إغلاق مراكز حقيقية في وضع PAPER أو بدون Binance client.",
                level="WARNING",
            )
            return False

        sym = str(symbol).upper().strip()
        pos = self._account_positions.get(sym)
        if not pos:
            return False

        free_qty = float(pos.free or 0.0)
        if free_qty <= 0:
            return False

        sell_qty = float(qty) if qty else free_qty
        sell_qty = min(sell_qty, free_qty)
        if sell_qty <= 0:
            return False

        try:
            self.client.create_order(
                symbol=sym,
                side="SELL",
                type="MARKET",
                quantity=float(f"{sell_qty:.8f}"),
            )
            self.refresh_account_positions(force=True)
            return True
        except Exception as e:
            self.logger.log(f"[ACCOUNT] SELL failed {sym}: {e}", level="ERROR")
            return False

    # ---------------- Loop ----------------
    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._ensure_daily_rollover()

                if self.bot_status != BotStatus.RUNNING:
                    time.sleep(self.poll_interval)
                    continue

                self.max_bot_balance = float(
                    self.settings.get("risk_limits.max_bot_balance", self.max_bot_balance)
                )

                self._refresh_balances()

                outputs = getattr(self.strategy, "outputs", None) or {}
                for sym in list(outputs.keys()):
                    decision = self.ai.evaluate_symbol(sym)
                    self._apply_ai_decision(decision)

                self._emit_runtime_stats()

            except Exception as e:
                self.logger.log(f"خطأ في محرك التداول: {e}", level="ERROR")

            time.sleep(self.poll_interval)

    # ---------------- Daily rollover + profit split ----------------
    def _ensure_daily_rollover(self) -> None:
        st = self.state.get_state() or {}
        today = date.today().isoformat()
        prev_date = st.get("daily_date")

        if not prev_date:
            st["daily_date"] = today
            st["daily_start_equity"] = float(self.max_bot_balance)
            st.setdefault("realized_pnl_today", 0.0)
            self.state.update(**st)
            return

        if str(prev_date) != today:
            self._apply_daily_profit_split(st)

            st["realized_pnl_today"] = 0.0
            st["daily_date"] = today
            st["daily_start_equity"] = float(self.max_bot_balance)

            self.state.update(**st)

    def _apply_daily_profit_split(self, st: Dict[str, Any]) -> None:
        prev_date = str(st.get("daily_date") or "")
        if not prev_date:
            return

        if str(st.get("last_profit_split_date") or "") == prev_date:
            return

        pnl = float(st.get("realized_pnl_today", 0.0) or 0.0)
        capital = float(st.get("capital_usdt", self.max_bot_balance) or self.max_bot_balance)
        bot_bal = float(st.get("bot_balance_usdt", 0.0) or 0.0)

        if pnl > 0:
            half = pnl * 0.5
            bot_bal += half
            capital += half
        elif pnl < 0:
            capital += pnl

        st["capital_usdt"] = float(capital)
        st["bot_balance_usdt"] = float(bot_bal)
        st["last_profit_split_date"] = prev_date

        self.state.update(**st)

        self._notify_telegram(
            f"📅 إقفال يوم {prev_date}\n"
            f"PnL: {pnl:.3f} USDT\n"
            f"تم تحديث Bot Balance + Capital وفق 50/50."
        )

    # ---------------- AI Apply - مرن أكثر ----------------
    def _apply_ai_decision(self, decision: AITradeDecision) -> None:
        sym = str(decision.symbol or "").upper()
        if not sym:
            return

        last = float(self.market.prices.get(sym, 0.0) or 0.0)
        if last <= 0:
            self._log_entry_reject(sym, "NO_PRICE")
            return

        try:
            self.positions.update_market_price(sym, last)
        except Exception:
            pass

        open_all = self.positions.get_open_positions()
        bot_positions_sym = [
            p for p in open_all
            if p.get("symbol") == sym and p.get("source") == "bot"
        ]

        # Exit recommendations
        try:
            recs = self.positions.check_exit_recommendations(sym, last, allow_trailing=True)
        except Exception:
            recs = []
        for pid, reason in recs:
            self._execute_close(pid, last, reason)

        # AI forced exit
        if decision.action == "EXIT" and bot_positions_sym:
            for p in list(bot_positions_sym):
                self._execute_close(p["id"], last, "AI_EXIT")
            return

        # Only entry logic below
        if decision.action != "ENTRY":
            return

        st = self.state.get_state() or {}
        realized_today = float(st.get("realized_pnl_today", 0.0) or 0.0)

        # Risk gate - مرن أكثر
        risk_res = self.risk.check_new_position(
            symbol=sym,
            last_price=last,
            exchange_balance_usdt=float(self.account_usdt_free),
            open_positions=open_all,
            realized_pnl_today=realized_today,
        )
        if not getattr(risk_res, "allowed", False):
            reason = str(getattr(risk_res, "reason", "RISK_BLOCK"))
            self._log_entry_reject(sym, "RISK_BLOCK", reason)
            return

        # prevent duplication for same symbol
        if bot_positions_sym:
            self._log_entry_reject(sym, "DUPLICATE_SYMBOL")
            return

        req_usdt = float(decision.requested_trade_usdt or 0.0)
        if req_usdt <= 0:
            self._log_entry_reject(sym, "REQ_USDT_ZERO")
            return

        # Clip by paper balance
        if self.paper_mode:
            paper_bal = float(st.get("paper_balance_usdt", 0.0) or 0.0)
            if paper_bal <= 0:
                self._log_entry_reject(sym, "PAPER_BAL_ZERO")
                return
            req_usdt = min(req_usdt, paper_bal)

        # Small trades block - مرن أكثر
        min_trade = float(self.settings.get("risk_limits.min_trade_usdt", 2.0))
        if req_usdt < min_trade:
            self._log_entry_reject(sym, "MIN_TRADE_BLOCK", f"req={req_usdt:.2f} < {min_trade:.2f}")
            return

        qty_raw = req_usdt / last
        qty = self._normalize_quantity(sym, qty_raw, last)
        if qty <= 0:
            self._log_entry_reject(sym, "QTY_NORMALIZE_ZERO", f"raw={qty_raw:.8f}")
            return

        sl_price = last * (1 - float(decision.sl_pct or 0.0) / 100.0) if decision.sl_pct else None
        tp_price = last * (1 + float(decision.tp_pct or 0.0) / 100.0) if decision.tp_pct else None

        # ✅ سجل فتح الصفقة
        self.logger.log(f"✅ فتح صفقة: {sym} | حجم: {req_usdt:.2f} USDT | سعر: {last:.6f}", level="INFO")
        
        self._execute_entry(
            sym,
            last,
            qty,
            tp_price=tp_price,
            sl_price=sl_price,
            use_trailing=bool(decision.use_trailing),
            trailing_sl_pct=float(decision.trailing_sl_pct or 0.0),
            reason_tags=decision.reason_tags,
        )

    # ---------------- Execution - نكتب فقط الفتح والإغلاق ----------------
    def _execute_entry(
        self,
        symbol: str,
        price: float,
        qty: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        use_trailing: bool = True,
        trailing_sl_pct: float = 0.0,
        reason_tags: Optional[List[str]] = None,
    ) -> None:
        symbol = symbol.upper()

        # LIVE order
        if not self.paper_mode:
            self._init_live_client_if_needed()
            if not self.client:
                self.logger.log("[دخول] لا يوجد اتصال بينانس", level="ERROR")
                return
            try:
                order = self.client.create_order(
                    symbol=symbol,
                    side="BUY",
                    type="MARKET",
                    quantity=float(f"{qty:.8f}"),
                )
                filled_qty = float(order.get("executedQty", "0") or 0.0)
                cumm_quote = float(order.get("cummulativeQuoteQty", "0") or 0.0)
                if filled_qty > 0 and cumm_quote > 0:
                    price = float(cumm_quote / filled_qty)
                    qty = float(filled_qty)
            except Exception as e:
                self.logger.log(f"فشل الشراء الحقيقي {symbol}: {e}", level="ERROR")
                return

        # PAPER balance debit
        st = self.state.get_state() or {}
        if self.paper_mode:
            trade_amount = float(price * qty)
            paper_bal = float(st.get("paper_balance_usdt", 0.0) or 0.0)
            if trade_amount > paper_bal + 1e-9:
                self._log_entry_reject(symbol, "PAPER_INSUFFICIENT_BAL", f"need={trade_amount:.2f}")
                return
            st["paper_balance_usdt"] = float(max(0.0, paper_bal - trade_amount))
            self.state.update(**st)

        # Open position in manager
        try:
            self.positions.open_position(
                symbol=symbol,
                entry_price=float(price),
                qty=float(qty),
                mode=("paper" if self.paper_mode else "live"),
                source="bot",
                tp_price=float(tp_price) if tp_price else None,
                sl_price=float(sl_price) if sl_price else None,
                use_trailing=bool(use_trailing and trailing_sl_pct > 0),
                trailing_sl_pct=float(trailing_sl_pct or 0.0),
                meta={"ai_tags": reason_tags or []},
            )
        except Exception as e:
            self.logger.log(f"[دخول] فشل فتح الصفقة {symbol}: {e}", level="ERROR")
            return

        trade_value = float(price * qty)

        # ✅ سجل مهم فقط
        self.logger.log(
            f"✅ تم فتح صفقة:\n"
            f"الرمز: {symbol}\n"
            f"الوضع: {'تجريبي' if self.paper_mode else 'حقيقي'}\n"
            f"السعر: {price:.6f}\n"
            f"الكمية: {qty:.6f}\n"
            f"القيمة: {trade_value:.2f} USDT",
            level="INFO"
        )

        self._notify_telegram(
            f"✅ تم فتح صفقة\n"
            f"الرمز: {symbol}\n"
            f"السعر: {price:.6f}\n"
            f"القيمة: {trade_value:.2f} USDT"
        )

    def _execute_close(self, pid: str, price: float, reason: str) -> None:
        pos = self.positions.open_positions.get(pid)
        if not pos or pos.get("source") != "bot":
            return

        symbol = str(pos.get("symbol", "")).upper()
        qty = float(pos.get("qty", 0.0) or 0.0)
        if qty <= 0:
            return

        # LIVE sell
        if not self.paper_mode and self.client:
            try:
                self.client.create_order(
                    symbol=symbol,
                    side="SELL",
                    type="MARKET",
                    quantity=float(f"{qty:.8f}"),
                )
            except Exception as e:
                self.logger.log(f"فشل البيع الحقيقي {symbol}: {e}", level="ERROR")
                return

        closed = self.positions.close_position(pid, price, reason)
        if not closed:
            return

        pnl = float(closed.get("pnl_usdt", 0.0) or 0.0)

        st = self.state.get_state() or {}
        st["realized_pnl_today"] = float(st.get("realized_pnl_today", 0.0) or 0.0) + pnl

        # PAPER credit
        if self.paper_mode:
            proceeds = float(qty * price)
            st["paper_balance_usdt"] = float(st.get("paper_balance_usdt", 0.0) or 0.0) + proceeds

        self.state.update(**st)

        try:
            self.risk.on_position_closed(symbol, pnl, exit_reason=reason)
        except Exception:
            pass

        try:
            self.ai.on_trade_closed(symbol, pnl)
        except Exception:
            pass

        trade_value = float(price * qty)
        
        # ✅ سجل مهم فقط
        self.logger.log(
            f"❌ تم إغلاق صفقة:\n"
            f"الرمز: {symbol}\n"
            f"السبب: {reason}\n"
            f"السعر: {price:.6f}\n"
            f"الربح/الخسارة: {pnl:.3f} USDT",
            level="INFO"
        )

        self._notify_telegram(
            f"❌ تم إغلاق صفقة\n"
            f"الرمز: {symbol}\n"
            f"السبب: {reason}\n"
            f"الربح/الخسارة: {pnl:.3f} USDT"
        )

    # ---------------- Market events ----------------
    def _on_price(self, symbol: str, price: float, change_24h: float) -> None:
        try:
            self.positions.update_market_price(symbol, price)
        except Exception:
            pass

    def _on_position_event(self, evt: PositionEvent) -> None:
        try:
            if evt.kind == "CLOSED":
                self._emit("POSITION_CLOSED", evt.position)
            elif evt.kind == "OPENED":
                self._emit("POSITION_OPENED", evt.position)
            elif evt.kind == "UPDATED":
                self._emit("POSITION_UPDATED", evt.position)
        except Exception:
            pass

    # ---------------- Emitters ----------------
    def _emit(self, kind: str, data: Dict[str, Any]) -> None:
        evt = EngineEvent(kind=kind, data=data)
        for fn in list(self._listeners):
            try:
                fn(evt)
            except Exception:
                pass

    def _emit_runtime_stats(self) -> None:
        st = self.state.get_state() or {}

        paper_bal = float(st.get("paper_balance_usdt", 0.0) or 0.0)
        realized_today = float(st.get("realized_pnl_today", 0.0) or 0.0)

        capital = float(st.get("capital_usdt", self.max_bot_balance) or self.max_bot_balance)
        bot_bal = float(st.get("bot_balance_usdt", 0.0) or 0.0)

        self.equity = paper_bal if self.paper_mode else float(self.account_total_usdt)
        self.daily_pnl_usdt = realized_today
        self.daily_pnl_pct = (
            (realized_today / self.max_bot_balance * 100.0)
            if self.max_bot_balance > 0 else 0.0
        )

        data = {
            "status": self.bot_status.value,
            "paper_mode": self.paper_mode,
            "equity": float(self.equity),
            "daily_pnl_usdt": float(self.daily_pnl_usdt),
            "daily_pnl_pct": float(self.daily_pnl_pct),
            "protected": bool(self._protected_today),
            "account_usdt_free": float(self.account_usdt_free),
            "account_total_usdt": float(self.account_total_usdt),
            "max_bot_balance": float(self.max_bot_balance),
            "paper_balance_usdt": float(paper_bal),
            "capital_usdt": float(capital),
            "bot_balance_usdt": float(bot_bal),
        }

        self._emit("RUNTIME_STATS", data)

    # ---------------- Balances / account ----------------
    def _init_live_client_if_needed(self) -> None:
        if self.paper_mode:
            self.client = None
            return
        if self.client is not None:
            return

        try:
            from core.api_keys import load_api_keys
            api_key, api_secret = load_api_keys()
        except Exception:
            api_key, api_secret = "", ""

        use_testnet = bool(self.settings.get("binance.use_testnet", False))

        if api_key and api_secret:
            try:
                self.client = Client(api_key, api_secret, testnet=use_testnet)
            except Exception as e:
                self.client = None
                self.logger.log(f"Binance client init failed: {e}", level="ERROR")
        else:
            self.client = None

    def _refresh_balances(self, force_account_fetch: bool = False) -> None:
        if self.paper_mode:
            st = self.state.get_state() or {}
            self.account_usdt_free = float(st.get("paper_balance_usdt", 0.0) or 0.0)
            self.account_total_usdt = self.account_usdt_free
            return

        now = time.time()
        if not force_account_fetch and (now - self._last_account_fetch_ts) < self._account_fetch_interval:
            return
        self._last_account_fetch_ts = now

        if not self.client:
            self.account_usdt_free = 0.0
            self.account_total_usdt = 0.0
            return

        try:
            acc = self.client.get_account()
            balances = acc.get("balances", []) if isinstance(acc, dict) else []
            usdt_free = 0.0
            for b in balances:
                if b.get("asset") == "USDT":
                    usdt_free = float(b.get("free", 0.0) or 0.0)
                    break
            self.account_usdt_free = float(usdt_free)
            self.account_total_usdt = float(usdt_free)
        except Exception:
            self.account_usdt_free = 0.0
            self.account_total_usdt = 0.0

    def _fetch_account_positions_live(self) -> Dict[str, AccountPosition]:
        out: Dict[str, AccountPosition] = {}
        if not self.client:
            return out

        try:
            acc = self.client.get_account()
            balances = acc.get("balances", []) if isinstance(acc, dict) else []

            for b in balances:
                asset = str(b.get("asset", "") or "")
                free = float(b.get("free", 0.0) or 0.0)
                locked = float(b.get("locked", 0.0) or 0.0)
                qty = free + locked

                if asset == "USDT" or qty <= 0:
                    continue

                symbol = f"{asset}USDT"
                last = float(self.market.prices.get(symbol, 0.0) or 0.0)
                value = qty * last if last > 0 else 0.0

                out[symbol] = AccountPosition(
                    asset=asset,
                    symbol=symbol,
                    qty=float(qty),
                    free=float(free),
                    last_price=float(last),
                    value_usdt=float(value),
                )
        except Exception:
            pass

        return out

    # ---------------- Quantity filters ----------------
    def _load_symbol_filters(self, symbol: str) -> None:
        if self.paper_mode or not self.client:
            return
        if symbol in self._symbol_filters:
            return

        try:
            info = self.client.get_symbol_info(symbol=symbol)
            if not info:
                return

            filters = info.get("filters", [])
            data: Dict[str, Any] = {}

            for f in filters:
                ftype = f.get("filterType")
                if ftype == "LOT_SIZE":
                    data["LOT_SIZE"] = {
                        "minQty": float(f.get("minQty", 0.0)),
                        "maxQty": float(f.get("maxQty", 0.0)),
                        "stepSize": float(f.get("stepSize", 0.0)),
                    }
                elif ftype == "MIN_NOTIONAL":
                    data["MIN_NOTIONAL"] = float(f.get("minNotional", 0.0))

            self._symbol_filters[symbol] = data
        except Exception:
            pass

    def _normalize_quantity(self, symbol: str, qty: float, price: float) -> float:
        if qty <= 0 or price <= 0:
            return 0.0

        if self.paper_mode:
            return float(f"{qty:.6f}")

        self._load_symbol_filters(symbol)
        f = self._symbol_filters.get(symbol, {})
        lot = f.get("LOT_SIZE")

        if lot:
            step = float(lot.get("stepSize", 0.0))
            min_qty = float(lot.get("minQty", 0.0))
            max_qty = float(lot.get("maxQty", 0.0))

            if step > 0:
                qty = math.floor(qty / step) * step

            if qty < min_qty:
                return 0.0
            if max_qty > 0 and qty > max_qty:
                qty = max_qty

        mn = float(f.get("MIN_NOTIONAL", 0.0) or 0.0)
        if mn > 0 and (qty * price) < mn:
            return 0.0

        return float(f"{qty:.8f}")

    # ---------------- Telegram helper ----------------
    def _notify_telegram(self, msg: str) -> None:
        if not self.tg_enabled or not self.telegram:
            return
        try:
            self.telegram.send_message(msg)
        except Exception:
            pass

    # =========================================================
    # Telegram-friendly helpers
    # =========================================================

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        st = self.state.get_state() or {}

        paper_bal = float(st.get("paper_balance_usdt", 0.0) or 0.0)
        realized_today = float(st.get("realized_pnl_today", 0.0) or 0.0)
        capital = float(st.get("capital_usdt", self.max_bot_balance) or self.max_bot_balance)
        bot_bal = float(st.get("bot_balance_usdt", 0.0) or 0.0)

        equity = paper_bal if self.paper_mode else float(self.account_total_usdt)
        pnl_pct = (realized_today / self.max_bot_balance * 100.0) if self.max_bot_balance else 0.0

        return {
            "status": self.bot_status.value,
            "paper_mode": self.paper_mode,
            "equity": float(equity),
            "daily_pnl_usdt": float(realized_today),
            "daily_pnl_pct": float(pnl_pct),
            "account_usdt_free": float(self.account_usdt_free),
            "account_total_usdt": float(self.account_total_usdt),
            "max_bot_balance": float(self.max_bot_balance),
            "paper_balance_usdt": float(paper_bal),
            "capital_usdt": float(capital),
            "bot_balance_usdt": float(bot_bal),
        }

    def telegram_text_status(self) -> str:
        snap = self.get_runtime_snapshot()
        mode = "PAPER" if snap["paper_mode"] else "LIVE"
        st = snap["status"]
        prot = "✅" if getattr(self, "_protected_today", False) else "—"

        return (
            f"🤖 حالة البوت\n"
            f"Status: {st}\n"
            f"Mode: {mode}\n"
            f"Protected: {prot}\n"
            f"Equity: {snap['equity']:.2f} USDT"
        )

    def telegram_text_pnl(self) -> str:
        snap = self.get_runtime_snapshot()
        return (
            f"📈 الربح/الخسارة اليوم\n"
            f"PnL: {snap['daily_pnl_usdt']:.3f} USDT\n"
            f"PnL %: {snap['daily_pnl_pct']:.2f}%"
        )

    def telegram_text_open_positions(self, limit: int = 10) -> str:
        opens = self.positions.get_open_positions() or []
        if not opens:
            return "📭 لا توجد صفقات مفتوحة حالياً."

        lines = ["📌 الصفقات المفتوحة حالياً:"]
        lim = max(1, int(limit))

        for p in opens[:lim]:
            sym = p.get("symbol", "")
            qty = float(p.get("qty", 0.0) or 0.0)
            entry = float(p.get("entry_price", 0.0) or 0.0)
            cur = float(p.get("current_price", 0.0) or 0.0)
            pnl = float(p.get("pnl_usdt", 0.0) or 0.0)
            pct = float(p.get("pnl_percent", 0.0) or 0.0)
            src = p.get("source", "bot")

            lines.append(
                f"- {sym} ({src}) | Qty:{qty:.6f} | "
                f"Entry:{entry:.6f} | Now:{cur:.6f} | "
                f"PnL:{pnl:.3f} USDT ({pct:.2f}%)"
            )

        if len(opens) > lim:
            lines.append(f"… +{len(opens) - lim} صفقات أخرى")

        return "\n".join(lines)

    def telegram_text_capital(self) -> str:
        snap = self.get_runtime_snapshot()
        free = snap["paper_balance_usdt"] if snap["paper_mode"] else snap["account_usdt_free"]
        used_est = max(0.0, float(self.max_bot_balance) - float(free))
        return (
            f"💰 الرصيد المستخدم والمتبقي\n"
            f"Max Bot Allocation: {self.max_bot_balance:.2f} USDT\n"
            f"Available (Free): {free:.2f} USDT\n"
            f"Estimated Used: {used_est:.2f} USDT"
        )

    def telegram_text_balances_ledger(self) -> str:
        snap = self.get_runtime_snapshot()
        return (
            f"📒 Ledger\n"
            f"Capital: {snap['capital_usdt']:.2f} USDT\n"
            f"Bot Balance: {snap['bot_balance_usdt']:.2f} USDT\n"
            f"Realized PnL Today: {snap['daily_pnl_usdt']:.3f} USDT"
        )

    # =========================================================
    # Convenience methods (safe to call from TelegramBot)
    # =========================================================

    def telegram_start_bot(self) -> bool:
        try:
            self.start_trading()
            return True
        except Exception as e:
            self.logger.log(f"Telegram start bot failed: {e}", level="ERROR")
            return False

    def telegram_stop_bot(self) -> bool:
        try:
            self.stop_trading()
            return True
        except Exception as e:
            self.logger.log(f"Telegram stop bot failed: {e}", level="ERROR")
            return False

    def telegram_toggle_mode(self) -> bool:
        try:
            self.set_paper_mode(not self.paper_mode)
            return True
        except Exception as e:
            self.logger.log(f"Telegram toggle mode failed: {e}", level="ERROR")
            return False