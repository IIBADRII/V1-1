# core/binance_client.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceRequestException
except Exception:  # library not installed or import failed
    Client = None
    BinanceAPIException = Exception
    BinanceRequestException = Exception

from core.logger import Logger


@dataclass
class BinanceResult:
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BinanceClient:
    """
    Spot-only REST client wrapper.

    Rules:
    - PAPER mode: never connects, never sends orders.
    - LIVE mode: uses REST only.
    - All bot orders have clientOrderId prefix: BADR_BOT_<uuid>
    - Safe retries, never crashes the app.
    """

    BOT_ORDER_PREFIX = "BADR_BOT_"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        use_testnet: bool = False,
        recv_window_ms: int = 5000,
        timeout_sec: int = 10,
        logger: Optional[Logger] = None,
    ) -> None:
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.use_testnet = bool(use_testnet)
        self.recv_window_ms = int(recv_window_ms)
        self.timeout_sec = int(timeout_sec)
        self.logger = logger or Logger()
        self._client = None

        self.readonly = not (self.api_key and self.api_secret)

        if Client is None:
            self.logger.error("python-binance library not available. LIVE mode disabled.")
            self.readonly = True
            return

        if not self.readonly:
            try:
                self._client = Client(self.api_key, self.api_secret)
                if self.use_testnet:
                    # spot testnet base urls (python-binance supports these attrs)
                    self._client.API_URL = "https://testnet.binance.vision/api"
                    self._client.WSS_URL = "wss://testnet.binance.vision/ws"
            except Exception as e:
                self.logger.error(f"Failed to init Binance client: {e}")
                self._client = None
                self.readonly = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def test_connection(self) -> BinanceResult:
        """
        Validates:
        - library available
        - internet / binance reachable
        - keys valid if provided
        """
        if Client is None or self._client is None:
            return BinanceResult(False, error="BINANCE_CLIENT_NOT_READY")

        try:
            # ping public first
            self._client.ping()

            # if keys, test signed endpoint
            if not self.readonly:
                self._client.get_account(recvWindow=self.recv_window_ms)
            return BinanceResult(True, data={"readonly": self.readonly})

        except BinanceAPIException as e:
            return BinanceResult(False, error=f"BINANCE_API_ERROR:{getattr(e, 'message', str(e))}")
        except BinanceRequestException as e:
            return BinanceResult(False, error=f"BINANCE_REQUEST_ERROR:{str(e)}")
        except Exception as e:
            return BinanceResult(False, error=f"UNKNOWN_ERROR:{str(e)}")

    def get_balance_usdt(self) -> BinanceResult:
        """
        Returns free USDT in LIVE mode.
        If readonly/no keys -> returns error.
        """
        if Client is None or self._client is None:
            return BinanceResult(False, error="BINANCE_CLIENT_NOT_READY")
        if self.readonly:
            return BinanceResult(False, error="NO_API_KEYS")

        def _call():
            acct = self._client.get_account(recvWindow=self.recv_window_ms)
            balances = acct.get("balances", [])
            for b in balances:
                if b.get("asset") == "USDT":
                    free = float(b.get("free", 0.0))
                    return {"free_usdt": free}
            return {"free_usdt": 0.0}

        return self._safe_retry(_call, op="get_balance_usdt")

    def create_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        order_type: str = "MARKET",
    ) -> BinanceResult:
        """
        Creates a spot order (MARKET by default).
        side: "BUY" or "SELL"
        qty: base asset quantity (already formatted by engine)
        client_order_id: MUST include BOT_ORDER_PREFIX
        """
        if Client is None or self._client is None:
            return BinanceResult(False, error="BINANCE_CLIENT_NOT_READY")
        if self.readonly:
            return BinanceResult(False, error="NO_API_KEYS")

        sym = symbol.upper().strip()
        sd = side.upper().strip()
        if sd not in {"BUY", "SELL"}:
            return BinanceResult(False, error="INVALID_SIDE")
        if qty <= 0:
            return BinanceResult(False, error="INVALID_QTY")

        cid = client_order_id
        if not cid.startswith(self.BOT_ORDER_PREFIX):
            cid = self.BOT_ORDER_PREFIX + cid

        def _call():
            resp = self._client.create_order(
                symbol=sym,
                side=sd,
                type=order_type,
                quantity=qty,
                newClientOrderId=cid,
                recvWindow=self.recv_window_ms,
            )
            return {
                "order_id": resp.get("orderId"),
                "client_order_id": resp.get("clientOrderId"),
                "status": resp.get("status"),
                "executed_qty": resp.get("executedQty"),
                "cummulative_quote_qty": resp.get("cummulativeQuoteQty"),
                "fills": resp.get("fills", []),
            }

        return self._safe_retry(_call, op=f"create_order {sym} {sd}")

    def close_position(
        self,
        symbol: str,
        qty: float,
        client_order_id: str,
    ) -> BinanceResult:
        """
        Close position by selling same qty (spot).
        TradingEngine guarantees source="bot" before calling.
        """
        return self.create_order(
            symbol=symbol,
            side="SELL",
            qty=qty,
            client_order_id=client_order_id,
            order_type="MARKET",
        )

    def get_open_orders(self, symbol: Optional[str] = None) -> BinanceResult:
        """
        Lists open orders. If symbol None => all symbols.
        """
        if Client is None or self._client is None:
            return BinanceResult(False, error="BINANCE_CLIENT_NOT_READY")
        if self.readonly:
            return BinanceResult(False, error="NO_API_KEYS")

        def _call():
            if symbol:
                orders = self._client.get_open_orders(symbol=symbol.upper(), recvWindow=self.recv_window_ms)
            else:
                orders = self._client.get_open_orders(recvWindow=self.recv_window_ms)
            return {"open_orders": orders}

        return self._safe_retry(_call, op="get_open_orders")

    # ------------------------------------------------------------------
    # Internal safe retry wrapper
    # ------------------------------------------------------------------

    def _safe_retry(self, fn, op: str, retries: int = 3) -> BinanceResult:
        delay_schedule = [1, 3, 5]
        last_err = None

        for i in range(retries):
            try:
                data = fn()
                return BinanceResult(True, data=data)
            except BinanceAPIException as e:
                last_err = getattr(e, "message", str(e))
                self.logger.error(f"Binance API error during {op}: {last_err}")
                break  # API error usually not retryable
            except BinanceRequestException as e:
                last_err = str(e)
                self.logger.warning(f"Binance request error during {op}: {last_err}")
            except Exception as e:
                last_err = str(e)
                self.logger.warning(f"Unknown error during {op}: {last_err}")

            if i < retries - 1:
                time.sleep(delay_schedule[min(i, len(delay_schedule) - 1)])

        return BinanceResult(False, error=last_err or "FAILED")
