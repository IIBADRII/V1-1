# core/position_manager.py
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logger import Logger
from core.settings_manager import SettingsManager
from core.state_manager import StateManager


@dataclass
class PositionEvent:
    kind: str  # OPENED | UPDATED | CLOSED
    position: Dict[str, Any]


class PositionManager:
    """
    Manages positions (Spot):
    - Open / update / close BOT positions.
    - Manual positions are display-only.
    - TP / SL / Trailing checks return recommendations.
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

        self._listeners: List[Callable[[PositionEvent], None]] = []

        state = self.state_manager.get_state() or {}
        self.open_positions: Dict[str, Dict[str, Any]] = {
            p["id"]: p for p in state.get("open_positions", []) if p.get("status") == "open"
        }
        self.closed_positions: List[Dict[str, Any]] = state.get("closed_positions", [])

    # ---------------------------
    def add_listener(self, fn: Callable[[PositionEvent], None]) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def _emit(self, kind: str, position: Dict[str, Any]) -> None:
        evt = PositionEvent(kind=kind, position=position)
        for fn in list(self._listeners):
            try:
                fn(evt)
            except Exception:
                pass

    # ---------------------------
    def get_open_positions(self) -> List[Dict[str, Any]]:
        return list(self.open_positions.values())

    def get_closed_positions(self) -> List[Dict[str, Any]]:
        return list(self.closed_positions)

    def has_open_bot_position(self, symbol: str) -> bool:
        sym = symbol.upper()
        for p in self.open_positions.values():
            if p.get("symbol", "").upper() == sym and p.get("status") == "open" and p.get("source") == "bot":
                return True
        return False

    def get_open_bot_positions_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        sym = symbol.upper()
        out: List[Dict[str, Any]] = []
        for p in self.open_positions.values():
            if p.get("status") != "open":
                continue
            if p.get("source") != "bot":
                continue
            if p.get("symbol", "").upper() == sym:
                out.append(p)
        return out

    def get_total_pnl(self) -> float:
        total = 0.0
        for p in self.open_positions.values():
            if p.get("status") == "open" and p.get("source") == "bot":
                total += float(p.get("pnl_usdt", 0.0) or 0.0)
        return float(total)

    def get_used_bot_balance(self) -> float:
        used = 0.0
        for p in self.open_positions.values():
            if p.get("status") == "open" and p.get("source") == "bot":
                used += float(p.get("entry_price", 0.0)) * float(p.get("qty", 0.0))
        return float(used)

    # ---------------------------
    def open_position(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        mode: Optional[str] = None,
        source: str = "bot",
        opened_at: Optional[float] = None,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        use_trailing: Optional[bool] = None,
        trailing_sl_pct: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if entry_price <= 0 or qty <= 0 or not sym:
            raise ValueError("Invalid position parameters.")

        if source == "bot" and self.has_open_bot_position(sym):
            raise ValueError(f"Bot already has open position on {sym}")

        trade_mode = (mode or self.settings_manager.get("trading.mode", "paper")).lower()

        # fallback settings if AI did not provide
        if tp_price is None or sl_price is None or use_trailing is None or trailing_sl_pct is None:
            take_profit_pct = float(self.settings_manager.get("risk_limits.take_profit_pct", 1.5) or 1.5)
            stop_loss_pct = float(self.settings_manager.get("risk_limits.stop_loss_pct", 1.0) or 1.0)
            use_tr = bool(self.settings_manager.get("risk_limits.use_trailing", True))
            tr_pct = float(self.settings_manager.get("risk_limits.trailing_sl_pct", stop_loss_pct) or stop_loss_pct)

            if tp_price is None and take_profit_pct > 0:
                tp_price = entry_price * (1 + take_profit_pct / 100.0)
            if sl_price is None and stop_loss_pct > 0:
                sl_price = entry_price * (1 - stop_loss_pct / 100.0)

            if use_trailing is None:
                use_trailing = use_tr
            if trailing_sl_pct is None:
                trailing_sl_pct = tr_pct

        pos_id = str(uuid.uuid4())
        ts = opened_at or time.time()

        position: Dict[str, Any] = {
            "id": pos_id,
            "symbol": sym,
            "source": source,
            "entry_price": float(entry_price),
            "qty": float(qty),
            "current_price": float(entry_price),
            "pnl_usdt": 0.0,
            "pnl_percent": 0.0,
            "tp_price": float(tp_price) if tp_price else None,
            "sl_price": float(sl_price) if sl_price else None,
            "use_trailing": bool(use_trailing) if source == "bot" else False,
            "trailing_sl_pct": float(trailing_sl_pct or 0.0),
            "peak_price": float(entry_price),
            "status": "open",
            "mode": trade_mode,
            "opened_at": ts,
            "closed_at": None,
            "exit_reason": None,
            "meta": meta or {},
        }

        self.open_positions[pos_id] = position
        self._persist_open_positions()

        self.logger.info(f"Opened position {sym} qty={qty:.6f} entry={entry_price:.6f} source={source}")
        self._emit("OPENED", position)
        return position

    # ---------------------------
    def update_price(self, symbol: str, price: float) -> None:
        sym = symbol.upper().strip()
        if price <= 0 or not sym:
            return

        changed = False
        for pos in self.open_positions.values():
            if pos.get("symbol", "").upper() != sym or pos.get("status") != "open":
                continue

            entry = float(pos.get("entry_price", 0.0))
            qty = float(pos.get("qty", 0.0))

            pos["current_price"] = float(price)
            pnl_usdt = (price - entry) * qty
            pnl_pct = ((price - entry) / entry) * 100.0 if entry > 0 else 0.0
            pos["pnl_usdt"] = float(pnl_usdt)
            pos["pnl_percent"] = float(pnl_pct)

            if pos.get("source") == "bot" and pos.get("use_trailing") and pos.get("sl_price") is not None:
                peak = float(pos.get("peak_price", entry))
                if price > peak:
                    pos["peak_price"] = float(price)
                    tr_pct = float(pos.get("trailing_sl_pct", 0.0) or 0.0)
                    if tr_pct > 0:
                        new_sl = price * (1 - tr_pct / 100.0)
                        if new_sl > float(pos["sl_price"]):
                            pos["sl_price"] = float(new_sl)

            changed = True
            self._emit("UPDATED", pos)

        if changed:
            self._persist_open_positions()

    def update_market_price(self, symbol: str, price: float) -> None:
        self.update_price(symbol, price)

    # ---------------------------
    def check_exit_recommendations(
        self,
        symbol: str,
        price: float,
        allow_trailing: bool = True,
    ) -> List[Tuple[str, str]]:
        sym = symbol.upper().strip()
        out: List[Tuple[str, str]] = []
        if price <= 0:
            return out

        for pid, pos in self.open_positions.items():
            if pos.get("status") != "open":
                continue
            if pos.get("symbol", "").upper() != sym:
                continue
            if pos.get("source") != "bot":
                continue

            tp = pos.get("tp_price")
            sl = pos.get("sl_price")
            use_tr = bool(pos.get("use_trailing")) and allow_trailing

            if tp is not None and price >= float(tp):
                out.append((pid, "TP"))
                continue

            if sl is not None and price <= float(sl):
                out.append((pid, "SL" if not use_tr else "TRAILING_SL"))
                continue

        return out

    # ---------------------------
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        reason: str,
        closed_at: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        pos = self.open_positions.get(position_id)
        if not pos:
            return None
        if pos.get("status") != "open":
            return None

        if pos.get("source") == "manual":
            return None

        entry = float(pos.get("entry_price", 0.0))
        qty = float(pos.get("qty", 0.0))

        pos["current_price"] = float(exit_price)
        pos["pnl_usdt"] = float((exit_price - entry) * qty)
        pos["pnl_percent"] = float(((exit_price - entry) / entry) * 100.0 if entry > 0 else 0.0)

        pos["status"] = "closed"
        pos["closed_at"] = closed_at or time.time()
        pos["exit_reason"] = str(reason)

        self.closed_positions.insert(0, pos)
        self.open_positions.pop(position_id, None)

        self._persist_open_positions()
        self._persist_closed_positions()

        self.logger.info(
            f"Closed position {pos['symbol']} reason={reason} pnl={pos['pnl_usdt']:.4f} USDT"
        )
        self._emit("CLOSED", pos)
        return pos

    # ---------------------------
    def _persist_open_positions(self) -> None:
        try:
            state = self.state_manager.get_state() or {}
            state["open_positions"] = self.get_open_positions()
            self.state_manager.update(**state)
        except Exception as e:
            self.logger.warning(f"Persist open_positions failed: {e}")

    def _persist_closed_positions(self) -> None:
        try:
            state = self.state_manager.get_state() or {}
            state["closed_positions"] = self.get_closed_positions()
            self.state_manager.update(**state)
        except Exception as e:
            self.logger.warning(f"Persist closed_positions failed: {e}")
