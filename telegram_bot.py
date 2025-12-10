# core/telegram_bot.py
from __future__ import annotations

import requests
from typing import Optional, Any, Dict, List, Callable
import time
import threading
from datetime import datetime, timezone


class TelegramBot:
    """
    Telegram Bot API helper + Command system + Polling
    بدون أي استيراد من ui لتجنب circular imports.

    الأوامر:
    /help
    /status
    /startbot
    /stopbot
    /pnl
    /mode
    /open
    /capital
    /summary
    /debug

    إدارة قائمة المراقبة:
    /watchlist
    /watchadd BTCUSDT
    /watchdel BTCUSDT

    أمان:
    - إذا كان الأمر حساس في الوضع الحقيقي:
      سيطلب تأكيد: "... confirm"
    """

    def __init__(
        self,
        token: str,
        chat_id: Optional[Any] = None,
        engine: Optional[Any] = None,
        settings: Optional[Any] = None,
        state: Optional[Any] = None,
        logger: Optional[Any] = None,
    ) -> None:
        self.token = (token or "").strip()
        self.chat_id = str(chat_id).strip() if chat_id else None
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.last_error: Optional[str] = None

        self.engine = engine
        self.settings = settings
        self.state = state
        self.logger = logger

        # polling
        self._polling_thread: Optional[threading.Thread] = None
        self._polling_running: bool = False
        self._update_offset: Optional[int] = None

        # commands registry
        self._commands: Dict[str, Callable[[Dict[str, Any]], str]] = {}

        # confirmations: {"startbot": expires_ts, "mode_live": expires_ts, ...}
        self._pending_confirm: Dict[str, float] = {}
        self._confirm_window_sec: float = 30.0

        # auto trade notifications
        self._trade_notifications_enabled: bool = True
        self._positions_listener_attached: bool = False

        self.register_default_commands()

        # attach listeners إن أمكن
        self.attach_engine_listeners()

    # =========================================================
    # Logging helper
    # =========================================================
    def _log(self, msg: str, level: str = "INFO"):
        try:
            if self.logger:
                if level == "ERROR" and hasattr(self.logger, "error"):
                    self.logger.error(msg)
                elif hasattr(self.logger, "info"):
                    self.logger.info(msg)
                elif hasattr(self.logger, "log"):
                    self.logger.log(msg, level=level)
            else:
                print(f"[TelegramBot:{level}] {msg}")
        except Exception:
            pass

    # =========================================================
    # Basic send/test methods
    # =========================================================
    def send_message(self, text: str, max_retries: int = 2) -> bool:
        if not self.token or not self.chat_id:
            self.last_error = "Token or Chat ID missing"
            return False

        if not text or not text.strip():
            self.last_error = "Empty message text"
            return False

        for attempt in range(max_retries + 1):
            try:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }

                response = requests.post(url, json=payload, timeout=15)

                if response.status_code == 200:
                    result = response.json()
                    if result.get("ok"):
                        self.last_error = None
                        return True
                    else:
                        self.last_error = f"API Error: {result.get('description', 'Unknown error')}"
                else:
                    self.last_error = f"HTTP {response.status_code}: {response.text}"

                if attempt < max_retries:
                    time.sleep(1)

            except requests.exceptions.Timeout:
                self.last_error = f"Request timeout (attempt {attempt + 1})"
                if attempt < max_retries:
                    time.sleep(1)
            except requests.exceptions.ConnectionError:
                self.last_error = f"Connection error (attempt {attempt + 1})"
                if attempt < max_retries:
                    time.sleep(2)
            except Exception as e:
                self.last_error = f"Unexpected error: {e}"
                if attempt < max_retries:
                    time.sleep(1)

        self._log(f"فشل إرسال الرسالة: {self.last_error}", level="ERROR")
        return False

    def test_connection(self) -> bool:
        if not self.token:
            self.last_error = "No bot token provided"
            return False

        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    bot_info = result["result"]
                    self._log(f"البوت نشط: {bot_info.get('first_name')} (@{bot_info.get('username')})")
                    return True
                else:
                    self.last_error = "Invalid bot token"
            else:
                self.last_error = f"HTTP {response.status_code}"

        except Exception as e:
            self.last_error = f"Connection test failed: {e}"

        self._log(f"فشل اختبار الاتصال: {self.last_error}", level="ERROR")
        return False

    def verify_chat_id(self) -> bool:
        if not self.token or not self.chat_id:
            self.last_error = "Token or Chat ID missing"
            return False
        return self.send_message("🔒 رسالة اختبار - البوت جاهز للعمل")

    def fetch_last_chat_id(self) -> Optional[str]:
        if not self.token:
            self.last_error = "No bot token provided"
            return None

        try:
            url = f"{self.base_url}/getUpdates"
            params = {"limit": 1, "offset": -1}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if result.get("ok") and result.get("result"):
                    last_update = result["result"][-1]
                    msg = last_update.get("message")
                    if msg:
                        chat_id = str(msg["chat"]["id"])
                        self.chat_id = chat_id
                        self._log(f"تم جلب Chat ID: {chat_id}")
                        return chat_id
                    self.last_error = "No messages found in updates"
                else:
                    self.last_error = "No updates available"
            else:
                self.last_error = f"HTTP {response.status_code}"

        except Exception as e:
            self.last_error = f"Failed to fetch chat ID: {e}"

        self._log(f"فشل جلب Chat ID: {self.last_error}", level="ERROR")
        return None

    def get_bot_info(self) -> Dict[str, Any]:
        return {
            "token_provided": bool(self.token),
            "chat_id_provided": bool(self.chat_id),
            "last_error": self.last_error,
            "base_url": self.base_url if self.token else "Not configured",
            "polling_running": self._polling_running,
            "trade_notifications_enabled": self._trade_notifications_enabled,
        }

    # =========================================================
    # Command registration
    # =========================================================
    def register_command(self, name: str, handler: Callable[[Dict[str, Any]], str]):
        self._commands[name.lower().strip("/")] = handler

    def register_default_commands(self):
        self.register_command("help", self._cmd_help)
        self.register_command("status", self._cmd_status)
        self.register_command("startbot", self._cmd_startbot)
        self.register_command("stopbot", self._cmd_stopbot)
        self.register_command("pnl", self._cmd_pnl)
        self.register_command("mode", self._cmd_mode)
        self.register_command("open", self._cmd_open)
        self.register_command("capital", self._cmd_capital)
        self.register_command("summary", self._cmd_summary)
        self.register_command("debug", self._cmd_debug)  # 🔥 أمر جديد للتصحيح

        # watchlist commands
        self.register_command("watchlist", self._cmd_watchlist)
        self.register_command("watchadd", self._cmd_watchadd)
        self.register_command("watchdel", self._cmd_watchdel)

    # =========================================================
    # Polling
    # =========================================================
    def start_polling(self, interval_sec: float = 1.5, allowed_chat_only: bool = True) -> bool:
        if not self.token:
            self.last_error = "No bot token provided"
            return False
        if allowed_chat_only and not self.chat_id:
            self.last_error = "Chat ID missing (required for secure polling)"
            return False
        if self._polling_running:
            return True

        self._polling_running = True

        def _loop():
            self._log("Telegram polling started.")
            while self._polling_running:
                try:
                    self._poll_once(allowed_chat_only=allowed_chat_only)
                except Exception as e:
                    self._log(f"Polling error: {e}", level="ERROR")
                time.sleep(max(0.5, float(interval_sec)))
            self._log("Telegram polling stopped.")

        self._polling_thread = threading.Thread(target=_loop, daemon=True)
        self._polling_thread.start()
        return True

    def stop_polling(self):
        self._polling_running = False

    def _poll_once(self, allowed_chat_only: bool = True):
        url = f"{self.base_url}/getUpdates"
        params: Dict[str, Any] = {"timeout": 10}

        if self._update_offset is not None:
            params["offset"] = self._update_offset

        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            self.last_error = f"HTTP {resp.status_code}: {resp.text}"
            return

        data = resp.json()
        if not data.get("ok"):
            self.last_error = f"API Error: {data.get('description', 'Unknown error')}"
            return

        updates = data.get("result") or []
        if not updates:
            return

        for upd in updates:
            upd_id = upd.get("update_id")
            if isinstance(upd_id, int):
                self._update_offset = upd_id + 1

            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue

            text = (msg.get("text") or "").strip()
            if not text.startswith("/"):
                continue

            chat_id = str((msg.get("chat") or {}).get("id", "") or "")
            if allowed_chat_only and self.chat_id and chat_id != str(self.chat_id):
                continue

            if not self.chat_id:
                self.chat_id = chat_id

            reply = self.process_command(text)
            if reply:
                self.send_message(reply)

    # =========================================================
    # Command processing
    # =========================================================
    def process_command(self, text: str) -> str:
        parts = text.strip().split()
        cmd = parts[0].lower().lstrip("/")
        args = parts[1:]

        handler = self._commands.get(cmd)
        if not handler:
            return "⚠️ أمر غير معروف. اكتب /help"

        ctx = {"raw": text, "args": args, "cmd": cmd}
        try:
            return handler(ctx)
        except Exception as e:
            self._log(f"Command '{cmd}' error: {e}", level="ERROR")
            return f"❌ خطأ أثناء تنفيذ الأمر {cmd}: {e}"

    # =========================================================
    # Engine safe access - 🔥 دالات محسنة
    # =========================================================
    def _get_engine_snapshot(self) -> Dict[str, Any]:
        """الحصول على بيانات snapshot من الـ engine بأمان"""
        if not self.engine:
            return {}
        
        try:
            # استخدم الدوال المساعدة الموجودة في TradingEngine
            if hasattr(self.engine, 'get_runtime_snapshot'):
                return self.engine.get_runtime_snapshot()
            
            # أو قم ببناء البيانات يدوياً
            paper_mode = getattr(self.engine, 'paper_mode', True)
            
            return {
                "status": getattr(self.engine, 'bot_status', 'STOPPED'),
                "paper_mode": paper_mode,
                "equity": getattr(self.engine, 'equity', 0.0),
                "daily_pnl_usdt": getattr(self.engine, 'daily_pnl_usdt', 0.0),
                "daily_pnl_pct": getattr(self.engine, 'daily_pnl_pct', 0.0),
            }
        except Exception:
            return {}

    def _engine_running(self) -> bool:
        snap = self._get_engine_snapshot()
        return snap.get('status') == 'RUNNING'

    def _engine_paper_mode(self) -> bool:
        snap = self._get_engine_snapshot()
        return snap.get('paper_mode', True)

    def _calc_today_pnl(self) -> float:
        snap = self._get_engine_snapshot()
        return snap.get('daily_pnl_usdt', 0.0)

    def _open_positions(self) -> List[Dict[str, Any]]:
        if not self.engine:
            return []
        try:
            # استخدم الطريقة من الـ engine إذا كانت موجودة
            if hasattr(self.engine, 'positions'):
                return self.engine.positions.get_open_positions()
        except Exception:
            return []
        return []

    def _capital_snapshot(self) -> Dict[str, float]:
        pnl_today = self._calc_today_pnl()

        max_bot = 0.0
        paper_init = 0.0

        try:
            if self.settings:
                max_bot = float(self.settings.get("risk_limits.max_bot_balance", 0.0) or 0.0)
                paper_init = float(self.settings.get("paper.initial_balance", max_bot) or max_bot)
        except Exception:
            pass

        paper_mode = self._engine_paper_mode()

        paper_balance_engine = paper_init
        try:
            paper_balance_engine = float(getattr(self.engine, "paper_balance_usdt", paper_init) or paper_init)
        except Exception:
            pass

        base = paper_balance_engine if paper_mode else max_bot

        used = 0.0
        for p in self._open_positions():
            try:
                used += float(p.get("value_usdt", 0.0) or 0.0)
            except Exception:
                pass

        remaining = (base + pnl_today) - used

        return {
            "base": base,
            "used": used,
            "remaining": remaining,
            "pnl_today": pnl_today,
        }

    # =========================================================
    # Confirmations
    # =========================================================
    def _needs_confirm(self, key: str) -> bool:
        now = time.time()
        exp = self._pending_confirm.get(key)
        return not exp or exp < now

    def _arm_confirm(self, key: str):
        self._pending_confirm[key] = time.time() + self._confirm_window_sec

    def _consume_confirm(self, key: str) -> bool:
        now = time.time()
        exp = self._pending_confirm.get(key)
        if exp and exp >= now:
            self._pending_confirm.pop(key, None)
            return True
        return False

    # =========================================================
    # Watchlist helpers
    # =========================================================
    def _get_watchlist(self) -> List[str]:
        try:
            if self.state:
                st = self.state.get_state() or {}
                wl = st.get("watchlist", [])
                return [str(x).upper() for x in (wl or [])]
        except Exception:
            pass
        return []

    def _set_watchlist(self, wl: List[str]) -> bool:
        try:
            if not self.state:
                return False
            wl = [s.upper() for s in wl if s and isinstance(s, str)]
            if hasattr(self.state, "set_watchlist"):
                self.state.set_watchlist(wl)
                return True
            # fallback لو فيه set_state
            if hasattr(self.state, "set_state"):
                st = self.state.get_state() or {}
                st["watchlist"] = wl
                self.state.set_state(st)
                return True
        except Exception:
            return False
        return False

    # =========================================================
    # Auto trade notifications
    # =========================================================
    def attach_engine_listeners(self):
        """
        يحاول ربط لسنر الصفقات تلقائياً إن توفر positions.add_listener
        """
        if self._positions_listener_attached:
            return
        if not self.engine:
            return

        try:
            positions = getattr(self.engine, "positions", None)
            if positions and hasattr(positions, "add_listener"):
                positions.add_listener(self._on_position_event)
                self._positions_listener_attached = True
                self._log("Positions listener attached for Telegram notifications.")
        except Exception:
            pass

    def _on_position_event(self, evt: Any):
        if not self._trade_notifications_enabled:
            return

        try:
            kind = str(getattr(evt, "kind", "") or "")
            pos = getattr(evt, "position", None) or {}

            sym = str(pos.get("symbol", "?"))
            pnl = float(pos.get("pnl_usdt", 0.0) or 0.0)
            qty = float(pos.get("qty", 0.0) or 0.0)
            entry = float(pos.get("entry_price", 0.0) or 0.0)
            last = float(pos.get("current_price", 0.0) or 0.0)

            if kind == "OPENED":
                msg = (
                    "🟢 صفقة جديدة\n"
                    f"{sym}\n"
                    f"qty: {qty:.6f}\n"
                    f"entry: {entry:.6f}"
                )
                self.send_message(msg)

            elif kind == "UPDATED":
                # تحديث خفيف بدون إزعاج: ممكن تفعيلها لاحقاً
                return

            elif kind == "CLOSED":
                icon = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪️")
                msg = (
                    f"{icon} تم إغلاق صفقة\n"
                    f"{sym}\n"
                    f"qty: {qty:.6f}\n"
                    f"last: {last:.6f}\n"
                    f"PnL: {pnl:.2f} USDT"
                )
                self.send_message(msg)

        except Exception:
            pass

    # =========================================================
    # Command handlers - 🔥 معدلة ومحسنة
    # =========================================================
    def _cmd_help(self, ctx: Dict[str, Any]) -> str:
        return (
            "📌 أوامر البوت:\n"
            "/status - حالة البوت\n"
            "/startbot - تشغيل البوت\n"
            "/stopbot - إيقاف البوت\n"
            "/pnl - الربح والخسارة اليوم\n"
            "/mode - تبديل تجريبي/حقيقي\n"
            "/open - الصفقات المفتوحة و PnL\n"
            "/capital - الرصيد المستخدم والمتبقي\n"
            "/summary - تقرير شامل\n"
            "/debug - معلومات تصحيح\n\n"
            "📌 قائمة المراقبة:\n"
            "/watchlist\n"
            "/watchadd BTCUSDT\n"
            "/watchdel BTCUSDT\n\n"
            "🔐 ملاحظة أمان:\n"
            "في الوضع الحقيقي قد يطلب تأكيد:\n"
            "/startbot confirm\n"
            "/mode confirm"
        )

    def _cmd_status(self, ctx: Dict[str, Any]) -> str:
        snap = self._get_engine_snapshot()
        status = snap.get('status', 'STOPPED')
        paper_mode = snap.get('paper_mode', True)
        
        status_txt = "🟢 يعمل" if status == 'RUNNING' else "🔴 متوقف"
        mode_txt = "🧪 تجريبي" if paper_mode else "💰 حقيقي"
        
        return f"الحالة: {status_txt}\nالوضع: {mode_txt}"

    def _cmd_startbot(self, ctx: Dict[str, Any]) -> str:
        if not self.engine:
            return "❌ لم يتم ربط TradingEngine مع TelegramBot."

        args = ctx.get("args") or []
        paper = self._engine_paper_mode()

        # أمان إضافي: لو الوضع حقيقي اطلب confirm
        if not paper:
            if "confirm" not in [a.lower() for a in args]:
                key = "startbot_live"
                if self._needs_confirm(key):
                    self._arm_confirm(key)
                    return "⚠️ أنت في الوضع الحقيقي.\nأرسل: /startbot confirm خلال 30 ثانية للتأكيد."
            else:
                if not self._consume_confirm("startbot_live"):
                    # حتى لو انتهت المهلة، نسمح بالتأكيد النصي المباشر
                    pass

        if self._engine_running():
            return "البوت يعمل بالفعل ✅"

        try:
            # تحديث رموز السوق من watchlist لو متوفر
            try:
                if self.state and hasattr(self.engine, "market"):
                    wl = self._get_watchlist()
                    if wl:
                        try:
                            self.engine.market.update_symbols(wl)
                        except Exception:
                            pass
            except Exception:
                pass

            self.engine.start_trading()
            self._log("Telegram command: startbot")
            return "✅ تم تشغيل البوت"
        except Exception as e:
            return f"❌ فشل تشغيل البوت: {e}"

    def _cmd_stopbot(self, ctx: Dict[str, Any]) -> str:
        if not self.engine:
            return "❌ لم يتم ربط TradingEngine مع TelegramBot."

        if not self._engine_running():
            return "البوت متوقف بالفعل ✅"

        try:
            self.engine.stop_trading()
            self._log("Telegram command: stopbot")
            return "✅ تم إوقف البوت"
        except Exception as e:
            return f"❌ فشل إيقاف البوت: {e}"

    def _cmd_pnl(self, ctx: Dict[str, Any]) -> str:
        pnl_today = self._calc_today_pnl()
        icon = "🟢" if pnl_today > 0 else ("🔴" if pnl_today < 0 else "⚪️")
        return f"{icon} PnL اليوم: {pnl_today:.2f} USDT"

    def _cmd_mode(self, ctx: Dict[str, Any]) -> str:
        if not self.engine:
            return "❌ لم يتم ربط TradingEngine مع TelegramBot."

        args = ctx.get("args") or []
        current_paper = self._engine_paper_mode()
        will_go_live = current_paper  # لأننا سنقلبه

        # لو التحويل إلى Live اطلب confirm
        if will_go_live:
            if "confirm" not in [a.lower() for a in args]:
                key = "mode_live"
                if self._needs_confirm(key):
                    self._arm_confirm(key)
                    return "⚠️ سيتم التحويل إلى <b>الوضع الحقيقي</b>.\nأرسل: /mode confirm خلال 30 ثانية للتأكيد."
            else:
                if not self._consume_confirm("mode_live"):
                    pass

        try:
            self.engine.set_paper_mode(not current_paper)

            # حفظ اختياري في settings
            try:
                if self.settings:
                    self.settings.set("trading.mode", "paper" if not current_paper else "live", auto_save=False)
                    self.settings.save_settings()
            except Exception:
                pass

            new_paper = self._engine_paper_mode()
            return "✅ تم التحويل إلى " + ("تجريبي 🧪" if new_paper else "حقيقي 💰")
        except Exception as e:
            return f"❌ فشل تبديل الوضع: {e}"

    def _cmd_open(self, ctx: Dict[str, Any]) -> str:
        opens = self._open_positions()
        if not opens:
            return "لا توجد صفقات مفتوحة حالياً."

        lines: List[str] = ["📌 الصفقات المفتوحة:"]
        total_pnl = 0.0

        for p in opens[:30]:
            sym = p.get("symbol", "?")
            qty = float(p.get("qty", 0.0) or 0.0)
            entry = float(p.get("entry_price", 0.0) or 0.0)
            last = float(p.get("current_price", 0.0) or 0.0)
            pnl = float(p.get("pnl_usdt", 0.0) or 0.0)
            total_pnl += pnl

            lines.append(
                f"- {sym} | qty {qty:.6f} | entry {entry:.6f} | last {last:.6f} | pnl {pnl:.2f}"
            )

        lines.append(f"\nالإجمالي PnL: {total_pnl:.2f} USDT")
        return "\n".join(lines)

    def _cmd_capital(self, ctx: Dict[str, Any]) -> str:
        snap = self._capital_snapshot()
        base = snap["base"]
        used = snap["used"]
        remaining = snap["remaining"]
        pnl_today = snap["pnl_today"]

        mode_txt = "تجريبي 🧪" if self._engine_paper_mode() else "حقيقي 💰"

        return (
            f"💼 رأس المال ({mode_txt})\n"
            f"- الرصيد الأساسي: {base:.2f} USDT\n"
            f"- PnL اليوم: {pnl_today:.2f} USDT\n"
            f"- المستخدم في صفقات مفتوحة: {used:.2f} USDT\n"
            f"- المتبقي المتاح: {remaining:.2f} USDT"
        )

    def _cmd_summary(self, ctx: Dict[str, Any]) -> str:
        snap = self._get_engine_snapshot()
        
        status = snap.get('status', 'STOPPED')
        paper_mode = snap.get('paper_mode', True)
        pnl_today = snap.get('daily_pnl_usdt', 0.0)
        
        status_txt = "🟢 يعمل" if status == 'RUNNING' else "🔴 متوقف"
        mode_txt = "🧪 تجريبي" if paper_mode else "💰 حقيقي"
        icon = "🟢" if pnl_today > 0 else ("🔴" if pnl_today < 0 else "⚪️")
        
        opens = self._open_positions()
        wl = self._get_watchlist()
        wl_txt = ", ".join(wl[:10]) if wl else "—"
        
        return (
            "📊 <b>ملخص سريع</b>\n"
            f"الحالة: {status_txt}\n"
            f"الوضع: {mode_txt}\n"
            f"{icon} PnL اليوم: {pnl_today:.2f} USDT\n"
            f"الصفقات المفتوحة: {len(opens)}\n"
            f"📌 Watchlist: {wl_txt}"
        )

    # 🔥 أمر جديد للتصحيح
    def _cmd_debug(self, ctx: Dict[str, Any]) -> str:
        info = self.get_bot_info()
        polling = "🟢 Polling يعمل" if self._polling_running else "🔴 Polling متوقف"
        engine = "✅ مربوط" if self.engine else "❌ غير مربوط"
        
        return (
            f"🔧 معلومات تصحيح البوت:\n"
            f"Token: {'✅ موجود' if info['token_provided'] else '❌ مفقود'}\n"
            f"Chat ID: {'✅ ' + str(self.chat_id) if info['chat_id_provided'] else '❌ مفقود'}\n"
            f"{polling}\n"
            f"Engine: {engine}\n"
            f"الأوامر المسجلة: {len(self._commands)}\n"
            f"آخر خطأ: {self.last_error or 'لا يوجد'}"
        )

    # ---------------- Watchlist commands ----------------
    def _cmd_watchlist(self, ctx: Dict[str, Any]) -> str:
        wl = self._get_watchlist()
        if not wl:
            return "📌 قائمة المراقبة فارغة."
        return "📌 قائمة المراقبة:\n" + "\n".join([f"- {s}" for s in wl])

    def _cmd_watchadd(self, ctx: Dict[str, Any]) -> str:
        args = ctx.get("args") or []
        if not args:
            return "اكتب مثلاً: /watchadd BTCUSDT"

        sym = str(args[0]).upper().strip()
        if not sym:
            return "رمز غير صالح."

        wl = self._get_watchlist()
        if sym in wl:
            return f"{sym} موجود بالفعل ✅"

        wl.append(sym)
        ok = self._set_watchlist(wl)
        if not ok:
            return "❌ فشل تحديث قائمة المراقبة."

        # تحديث السوق إن أمكن
        try:
            if self.engine and hasattr(self.engine, "market"):
                self.engine.market.update_symbols(wl)
        except Exception:
            pass

        return f"✅ تمت إضافة {sym} إلى قائمة المراقبة"

    def _cmd_watchdel(self, ctx: Dict[str, Any]) -> str:
        args = ctx.get("args") or []
        if not args:
            return "اكتب مثلاً: /watchdel BTCUSDT"

        sym = str(args[0]).upper().strip()
        wl = self._get_watchlist()
        if sym not in wl:
            return f"{sym} غير موجود في القائمة."

        wl = [s for s in wl if s != sym]
        ok = self._set_watchlist(wl)
        if not ok:
            return "❌ فشل تحديث قائمة المراقبة."

        try:
            if self.engine and hasattr(self.engine, "market"):
                self.engine.market.update_symbols(wl)
        except Exception:
            pass

        return f"✅ تم حذف {sym} من قائمة المراقبة"