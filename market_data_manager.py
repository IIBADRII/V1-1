# core/market_data_manager.py
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests
from websocket import WebSocketApp  # websocket-client

from core.logger import Logger
from core.settings_manager import SettingsManager
from core.state_manager import StateManager

BINANCE_WSS_BASE = "wss://stream.binance.com:9443/stream?streams="
BINANCE_REST_KLINES = "https://api.binance.com/api/v3/klines"


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    is_closed: bool


class MarketDataManager:
    """
    WebSocket market data manager for Spot:
    - Combined stream: !ticker@arr + <symbol>@kline_<interval>
    - Preloads REST history on start (IMPORTANT for indicators)
    - Dynamic symbol update (reconnect combined stream)
    - Safe reconnect with backoff
    - In-memory store: prices, change_24h, klines
    - Listener callbacks for UI / engines
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

        md_settings = self.settings_manager.get("market_data", {})
        self.kline_intervals: List[str] = md_settings.get("kline_intervals", ["15m", "1h"])
        self.history_limit: int = int(md_settings.get("history_candles_limit", 120))
        self.data_timeout_sec: int = int(md_settings.get("data_timeout_sec", 60))
        self.ws_backoff_sec: List[int] = list(md_settings.get("ws_backoff_sec", [2, 5, 10, 15]))

        self._lock = threading.Lock()
        self._running = False
        self._ws_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._ws: Optional[WebSocketApp] = None

        self._symbols: List[str] = []
        self._streams_url: str = ""
        self._reconnect_index = 0
        self._force_reconnect_event = threading.Event()

        self.last_data_time = 0.0

        # ✅ preload control (avoid overlap)
        self._preload_lock = threading.Lock()
        self._preload_inflight = False

        # Stores
        self.prices: Dict[str, float] = {}
        self.change_24h: Dict[str, float] = {}
        self.klines: Dict[str, Dict[str, List[Candle]]] = {}  # symbol -> interval -> candles

        # Listeners
        self._price_listeners: List[Callable[[str, float, float], None]] = []
        self._kline_listeners: List[Callable[[str, str, List[Candle]], None]] = []
        self._conn_listeners: List[Callable[[str], None]] = []

        state = self.state_manager.get_state() or {}
        self._symbols = [s.upper() for s in state.get("watchlist", ["BTCUSDT"])]

    # ---------------------------
    # Public listener API
    # ---------------------------

    def add_price_listener(self, fn: Callable[[str, float, float], None]) -> None:
        if fn not in self._price_listeners:
            self._price_listeners.append(fn)

    def add_kline_listener(self, fn: Callable[[str, str, List[Candle]], None]) -> None:
        if fn not in self._kline_listeners:
            self._kline_listeners.append(fn)

    def add_connection_listener(self, fn: Callable[[str], None]) -> None:
        if fn not in self._conn_listeners:
            self._conn_listeners.append(fn)

    # ---------------------------
    # Lifecycle
    # ---------------------------

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._force_reconnect_event.clear()
        self._reconnect_index = 0

        # ✅ شغل start بالخلفية عشان ما يعلق UI
        threading.Thread(target=self._start_async, daemon=True).start()
        self.logger.info("MarketDataManager starting async...")

    def _start_async(self) -> None:
        # ✅ IMPORTANT: preload REST history before WS starts (async)
        self._preload_history()

        self._rebuild_streams_url()

        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()

        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

        self.logger.info("MarketDataManager started (WebSocket, async).")

    def stop(self) -> None:
        self._running = False
        self._force_reconnect_event.set()

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

        self._emit_connection("disconnected")
        self.logger.info("MarketDataManager stopped (WebSocket closed).")

    def update_symbols(self, symbols: List[str]) -> None:
        new_syms = [s.upper().strip() for s in symbols if s and isinstance(s, str)]
        new_syms = list(dict.fromkeys(new_syms))

        with self._lock:
            if new_syms == self._symbols:
                return
            self._symbols = new_syms
            self._rebuild_streams_url()

        # ✅ preload history for new symbols too (async)
        threading.Thread(target=self._preload_history, daemon=True).start()

        self.logger.info(f"Watchlist updated. Reconnecting WS with {len(new_syms)} symbols.")
        self._force_reconnect_event.set()

    def get_symbols(self) -> List[str]:
        with self._lock:
            return list(self._symbols)

    # ---------------------------
    # Preload REST history
    # ---------------------------

    def _preload_history(self) -> None:
        """
        Binance WS doesn't provide historical candles.
        We must fetch REST klines to seed indicators.
        Runs async and guarded to avoid overlaps.
        """
        if not self._running:
            return

        with self._preload_lock:
            if self._preload_inflight:
                return
            self._preload_inflight = True

        try:
            with self._lock:
                symbols = list(self._symbols)
                intervals = list(self.kline_intervals)
                limit = int(self.history_limit)

            for sym in symbols:
                if not self._running:
                    break

                self.klines.setdefault(sym, {})
                for iv in intervals:
                    if not self._running:
                        break
                    try:
                        r = requests.get(
                            BINANCE_REST_KLINES,
                            params={"symbol": sym, "interval": iv, "limit": limit},
                            timeout=10,
                        )
                        r.raise_for_status()
                        raw = r.json()

                        candles: List[Candle] = []
                        for k in raw:
                            candles.append(Candle(
                                open_time=int(k[0]),
                                open=float(k[1]),
                                high=float(k[2]),
                                low=float(k[3]),
                                close=float(k[4]),
                                volume=float(k[5]),
                                close_time=int(k[6]),
                                is_closed=True,  # REST candles are closed
                            ))

                        with self._lock:
                            self.klines[sym][iv] = candles

                        # ✅ push to listeners once - FIXED: Use the correct method
                        self._emit_kline(sym, iv, candles)

                    except Exception as e:
                        self.logger.warning(f"REST preload klines failed {sym} {iv}: {e}")

        finally:
            with self._preload_lock:
                self._preload_inflight = False

    # ---------------------------
    # Internal WS loop
    # ---------------------------

    def _ws_loop(self) -> None:
        while self._running:
            try:
                url = self._streams_url
                self._emit_connection("reconnecting" if self._reconnect_index > 0 else "connected")
                self._connect_and_run(url)
            except Exception as e:
                self.logger.error(f"WebSocket fatal error: {e}")

            if not self._running:
                break

            if self._force_reconnect_event.is_set():
                self._force_reconnect_event.clear()
                self._reconnect_index = 0
                continue

            delay = self.ws_backoff_sec[min(self._reconnect_index, len(self.ws_backoff_sec) - 1)]
            self._reconnect_index += 1
            self.logger.warning(f"WebSocket disconnected. Reconnecting in {delay}s...")
            self._emit_connection("reconnecting")
            time.sleep(delay)

        self._emit_connection("disconnected")

    def _connect_and_run(self, url: str) -> None:
        self._ws = WebSocketApp(
            url,
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10, ping_payload="ping")

    # ---------------------------
    # WS callbacks
    # ---------------------------

    def _on_open(self, ws: WebSocketApp) -> None:
        self.last_data_time = time.time()
        self.logger.info("WebSocket connected.")
        self._emit_connection("connected")
        self._reconnect_index = 0

    def _on_close(self, ws: WebSocketApp, code: Any, msg: Any) -> None:
        self.logger.warning(f"WebSocket closed: code={code} msg={msg}")

    def _on_error(self, ws: WebSocketApp, error: Any) -> None:
        self.logger.error(f"WebSocket error: {error}")

    def _on_message(self, ws: WebSocketApp, message: str) -> None:
        self.last_data_time = time.time()
        try:
            payload = json.loads(message)
        except Exception:
            return

        stream = payload.get("stream", "")
        data = payload.get("data")

        if not stream or data is None:
            return

        if stream == "!ticker@arr":
            self._handle_ticker_array(data)
        elif "@kline_" in stream:
            self._handle_kline(stream, data)

    # ---------------------------
    # Handlers
    # ---------------------------

    def _handle_ticker_array(self, arr: List[Dict[str, Any]]) -> None:
        with self._lock:
            watchset = set(self._symbols)

        for t in arr:
            sym = t.get("s")
            if not sym or sym not in watchset:
                continue
            try:
                last_price = float(t.get("c", 0.0))
                change_pct = float(t.get("P", 0.0))
            except Exception:
                continue

            with self._lock:
                self.prices[sym] = last_price
                self.change_24h[sym] = change_pct
                if sym not in self.klines:
                    self.klines[sym] = {iv: [] for iv in self.kline_intervals}

            self._emit_price(sym, last_price, change_pct)

    def _handle_kline(self, stream: str, data: Dict[str, Any]) -> None:
        try:
            sym_part, kline_part = stream.split("@kline_")
            symbol = sym_part.upper()
            interval = kline_part
        except Exception:
            return

        k = data.get("k", {})
        if not k:
            return

        try:
            candle = Candle(
                open_time=int(k["t"]),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
                close_time=int(k["T"]),
                is_closed=bool(k["x"]),
            )
        except Exception:
            return

        with self._lock:
            if symbol not in self.klines:
                self.klines[symbol] = {iv: [] for iv in self.kline_intervals}
            if interval not in self.klines[symbol]:
                self.klines[symbol][interval] = []

            candles = self.klines[symbol][interval]

            if candles and candles[-1].open_time == candle.open_time:
                candles[-1] = candle
            else:
                candles.append(candle)

            if len(candles) > self.history_limit:
                self.klines[symbol][interval] = candles[-self.history_limit:]
                candles = self.klines[symbol][interval]

        # ✅ FIXED: Emit ALL kline updates (not just closed ones) so StrategyEngine gets real-time data
        self._emit_kline(symbol, interval, candles)
        
        # Log the kline update for debugging
        self.logger.debug(f"Kline update: {symbol} {interval} - Close: {candle.close}, IsClosed: {candle.is_closed}")

    # ---------------------------
    # Watchdog
    # ---------------------------

    def _watchdog_loop(self) -> None:
        while self._running:
            now = time.time()
            if self.last_data_time > 0 and (now - self.last_data_time) > self.data_timeout_sec:
                self.logger.critical(
                    f"No market data for {self.data_timeout_sec}s — suspend new entries until data returns."
                )
                self._emit_connection("disconnected")

                while self._running and (time.time() - self.last_data_time) > 1:
                    time.sleep(1)

                if self._running:
                    self.logger.info("Market data restored — resume trading decisions.")
                    self._emit_connection("connected")

            time.sleep(2)

    # ---------------------------
    # Stream URL builder
    # ---------------------------

    def _rebuild_streams_url(self) -> None:
        with self._lock:
            symbols = list(self._symbols)

        streams = ["!ticker@arr"]
        for sym in symbols:
            s = sym.lower()
            for iv in self.kline_intervals:
                streams.append(f"{s}@kline_{iv}")

        self._streams_url = BINANCE_WSS_BASE + "/".join(streams)

    # ---------------------------
    # Emitters - ADDED MISSING _emit_kline METHOD
    # ---------------------------

    def _emit_price(self, symbol: str, price: float, change_pct: float) -> None:
        for fn in list(self._price_listeners):
            try:
                fn(symbol, price, change_pct)
            except Exception:
                pass

    def _emit_kline(self, symbol: str, interval: str, candles: List[Candle]) -> None:
        """Emit kline data to all registered kline listeners"""
        for fn in list(self._kline_listeners):
            try:
                fn(symbol, interval, candles)
            except Exception:
                pass

    def _emit_connection(self, status: str) -> None:
        for fn in list(self._conn_listeners):
            try:
                fn(status)
            except Exception:
                pass

    # ---------------------------
    # Debug methods
    # ---------------------------

    def get_candles(self, symbol: str, interval: str) -> Optional[List[Candle]]:
        """Get stored candles for a symbol and interval"""
        symbol = symbol.upper()
        with self._lock:
            if symbol in self.klines and interval in self.klines[symbol]:
                return self.klines[symbol][interval].copy()
        return None

    def debug_status(self) -> Dict[str, Any]:
        """Return debug information about current data state"""
        with self._lock:
            symbols = list(self._symbols)
            
        status = {
            "symbols": symbols,
            "intervals": self.kline_intervals,
            "prices": {},
            "candle_counts": {},
            "websocket_connected": self.last_data_time > (time.time() - 30)
        }
        
        for symbol in symbols:
            status["prices"][symbol] = self.prices.get(symbol, 0.0)
            status["candle_counts"][symbol] = {}
            
            for interval in self.kline_intervals:
                candles = self.get_candles(symbol, interval)
                if candles:
                    status["candle_counts"][symbol][interval] = len(candles)
                else:
                    status["candle_counts"][symbol][interval] = 0
                    
        return status