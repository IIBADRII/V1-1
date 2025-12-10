# core/settings_manager.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union


# =========================
# Project Paths
# =========================
CORE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CORE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_SETTINGS_PATH = DATA_DIR / "settings.json"


# =========================
# DEFAULT SETTINGS - مرنة أكثر
# =========================
DEFAULT_SETTINGS: Dict[str, Any] = {
    "binance": {
        "api_key": "",
        "api_secret": "",
        "use_testnet": False,
        "recv_window_ms": 5000,
        "timeout_sec": 10,
        "account_refresh_sec": 150.0,
    },

    "trading": {
        "mode": "paper",
        "paper_mode": True,
        "manage_only_bot_positions": True,
        "close_positions_on_stop": False,
        "cooldown_on_restart_min": 3,
    },

    "market_data": {
        "kline_intervals": ["15m", "1h"],
        "history_candles_limit": 120,
        "data_timeout_sec": 60,
        "ws_backoff_sec": [2, 5, 10, 15],
    },

    "strategy": {
        "enabled": True,
        "entry_score_threshold": 60.0,
        "exit_score_threshold": 45.0,
        "smart_exit": True,

        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "ema_fast": 20,
        "ema_slow": 50,
        "bb_period": 20,
        "bb_stddev": 2.0,

        "base_interval": "15m",

        "weights": {
            "momentum": 30.0,
            "trend": 30.0,
            "volatility": 20.0,
            "liquidity": 20.0,
        },

        "legacy_weights": {
            "rsi": 30.0,
            "macd": 30.0,
            "ema_trend": 20.0,
            "bollinger": 20.0,
        },
    },

    # ✅ قسم AI مرن
    "ai": {
        "enabled": True,
        "min_score": 0.40,
        "min_valid_signals": 1,
        "eval_cooldown_sec": 2.0,
        "warmup_relax_sec": 300,
        "warmup_relax_score_delta": 0.10,
        "warmup_relax_signals_delta": 1,
        "require_mtf_ok": False,
        
        "default_sl_pct": 2.0,
        "default_tp_pct": 3.0,
        "default_trailing_sl_pct": 1.0,
        
        "trade_usdt": 10.0,
        "trade_usdt_min": 2.0,
        "trade_usdt_max": 30.0,
    },

    # ✅ Risk مرن أكثر
    "risk_limits": {
        "max_bot_balance": 1000.0,
        "max_open_trades": 5,
        "max_trades_per_symbol": 2,
        
        "trade_risk_pct": 1.0,
        "daily_max_loss_pct": 10.0,
        "daily_take_profit_pct": 10.0,
        
        "loss_cooldown_min": 5,
        "reentry_delay_min": 10,
        
        "min_trade_usdt": 2.0,
        
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "use_trailing": True,
        "trailing_sl_pct": 1.0,
    },

    "paper": {
        "enabled": True,
        "initial_balance": 1000.0,
    },

    "live": {
        "enabled": True,
        "max_capital": 1000.0,
        "max_open_positions": 5,
        "auto_position_sizing": True,
    },

    "symbols": {
        "watchlist": ["BTCUSDT", "ETHUSDT", "ADAUSDT"],
    },

    "appearance": {
        "theme": "dark",
        "font_family": "IBM Plex Sans Arabic",
        "font_size_base": 14,
    },

    "notifications": {
        "sound_enabled": True,
        "entry_sound": "data/sounds/entry.wav",
        "exit_sound": "data/sounds/exit.wav",
        "notify_sound": "data/sounds/notify.wav",
        "desktop_notifications": False,
    },

    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
        "status_interval_sec": 60.0,
    },

    # ✅ قسم Engine للتحكم بالسجلات
    "engine": {
        "poll_interval_sec": 2.0,
        "debug_entry_reasons": False,
        "debug_entry_reasons_level": "WARNING",
    },

    "system": {
        "auto_restart_on_error": True,
        "state_backup_enabled": True,
    },
}


class SettingsManager:
    """
    كلاس إدارة الإعدادات - مع إعدادات مرنة
    """

    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self.settings_path = self._resolve_path(path)
        self._migrate_legacy_root_settings()
        self.settings: Dict[str, Any] = self._load_or_init()

    # ------------ مسارات ------------

    def _resolve_path(self, path: Optional[Union[str, Path]]) -> Path:
        if path is None:
            return DEFAULT_SETTINGS_PATH

        p = Path(path)
        # لو مسار نسبي نخليه نسبة لجذر المشروع
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    def _migrate_legacy_root_settings(self) -> None:
        """
        إذا كان يوجد ملف قديم في جذر المشروع:
            PROJECT_ROOT/settings.json
        ولم يوجد الملف الجديد في data/
        نقوم بنقله تلقائياً لضمان عدم ضياع إعدادات المستخدم.
        """
        legacy = PROJECT_ROOT / "settings.json"

        # لو المستخدم مرر مسار مخصص مختلف، لا نتدخل
        if self.settings_path != DEFAULT_SETTINGS_PATH:
            return

        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        if legacy.exists() and not self.settings_path.exists():
            try:
                legacy.rename(self.settings_path)
            except Exception:
                # لو فشل النقل لأي سبب، نجرب نسخ المحتوى
                try:
                    data = legacy.read_text(encoding="utf-8")
                    self.settings_path.write_text(data, encoding="utf-8")
                except Exception:
                    pass

    # ------------ تهيئة وتحميل ------------

    def _load_or_init(self) -> Dict[str, Any]:
        """تحميل الإعدادات أو إنشاء ملف جديد بالقيم الافتراضية."""
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        if not self.settings_path.exists():
            data = self._deep_copy(DEFAULT_SETTINGS)
            self._save_to_disk(data)
            return data

        try:
            with self.settings_path.open("r", encoding="utf-8") as f:
                on_disk = json.load(f)
            if not isinstance(on_disk, dict):
                on_disk = {}
        except Exception:
            on_disk = {}

        merged = self._deep_merge(self._deep_copy(DEFAULT_SETTINGS), on_disk)
        self._save_to_disk(merged)
        return merged

    @classmethod
    def load(cls, path: Optional[Union[str, Path]] = None) -> "SettingsManager":
        return cls(path)

    # ------------ حفظ ------------

    def _save_to_disk(self, data: Dict[str, Any]) -> None:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        tmp_path = self.settings_path.with_suffix(".tmp")

        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        tmp_path.replace(self.settings_path)

    def save_settings(self) -> None:
        """حفظ الإعدادات الحالية في الملف."""
        self._save_to_disk(self.settings)

    # ------------ get / set ------------

    def get(self, key_path: str, default: Optional[Any] = None) -> Any:
        """
        قراءة قيمة من الإعدادات بطريقة المسار المنقّط:
            "risk_limits.max_bot_balance"
        أو قيمة مستوى أول:
            "risk_limits"
        """
        if not key_path:
            return default

        node: Any = self.settings
        for part in str(key_path).split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, key_path: str, value: Any, auto_save: bool = True) -> None:
        """
        كتابة قيمة في الإعدادات بطريقة المسار المنقّط:
            "risk_limits.max_bot_balance"
        """
        if not key_path:
            return

        parts = str(key_path).split(".")
        node: Any = self.settings

        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]

        node[parts[-1]] = value

        if auto_save:
            self.save_settings()

    # ------------ أدوات داخلية ------------

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in (override or {}).items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    def _deep_copy(self, d: Dict[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(d))