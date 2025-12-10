# run.py
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

# ✅ تأكد أن جذر المشروع موجود في sys.path لتفادي مشاكل الاستيراد
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ✅ المسارات الجديدة حسب تنظيم المشروع
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = PROJECT_ROOT / "state"

SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = STATE_DIR / "bot_state.json"


# -------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------
# ملاحظة:
# نخلي DEFAULT_SETTINGS و DEFAULT_STATE هنا كما هي في ملفك
# لضمان عدم كسر أي شيء الآن.
# لاحقًا إذا رغبت، ننقلها لتكون مستوردة من core.* كمرجع واحد.
DEFAULT_SETTINGS = {
    "binance": {
        "api_key": "",
        "api_secret": "",
        "use_testnet": False,
        "recv_window_ms": 5000,
        "timeout_sec": 10
    },

    "trading": {
        "mode": "paper",
        "cooldown_on_restart_min": 3,
        # ✅ مستخدمة في الواجهة
        "manage_only_bot_positions": True,
        "close_positions_on_stop": False
    },

    "paper": {
        # ✅ مستخدمة في Settings UI
        "initial_balance": 1000.0
    },

    "market_data": {
        "kline_intervals": ["15m", "1h"],
        "history_candles_limit": 50,
        "data_timeout_sec": 60,
        "ws_backoff_sec": [2, 5, 10, 15]
    },

    # ملاحظة: هذه القيم الافتراضية لا تمنعك من استخدام StrategyEngine الحالي
    "strategy": {
        "enabled": True,
        "entry_score_threshold": 70,
        "exit_score_threshold": 40,
        "smart_exit": True,
        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "ema_fast": 20,
        "ema_slow": 50,
        "bb_period": 20,
        "bb_stddev": 2,
        # ✅ لو نسخة الاستراتيجية الجديدة تعتمد weights مختلفة
        "weights": {
            "momentum": 30,
            "trend": 30,
            "volatility": 20,
            "liquidity": 20
        },
        "base_interval": "15m"
    },

    "risk_limits": {
        # ✅ هذا هو المدخل المالي الرئيسي للمستخدم
        "max_bot_balance": 1000.0,

        "max_open_trades": 3,
        "max_trades_per_symbol": 1,
        "trade_risk_pct": 2.0,

        "daily_max_loss_pct": 5.0,
        "daily_take_profit_pct": 4.0,

        "take_profit_pct": 1.5,
        "stop_loss_pct": 1.0,

        "use_trailing": True,
        "trailing_sl_pct": 1.0,

        "loss_cooldown_min": 10,
        "reentry_delay_min": 15
    },

    "telegram": {
        # ✅ تبويب Telegram في الواجهة يعتمد هذه المفاتيح
        "enabled": False,
        "bot_token": "",
        "chat_id": None,
        "status_interval_sec": 60
    },

    "alerts": {
        "sound_enabled": False,
        "sound_file": "",
        "desktop_notifications": False
    },

    "sound": {
        "enabled": True,
        "volume": 0.9,
        "file": "data/sounds/notify.wav",
        "entry_file": "data/sounds/entry.wav",
        "exit_file": "data/sounds/exit.wav",
        "notify_file": "data/sounds/notify.wav"
    },

    "appearance": {
        "theme": "dark",
        "font_family": "IBM Plex Sans Arabic",
        "font_size_base": 14
    },

    "system": {
        "auto_restart_on_error": True,
        # ✅ مستخدمة في Settings UI
        "state_backup_enabled": True
    }
}


DEFAULT_STATE = {
    "watchlist": ["BTCUSDT"],
    "open_positions": [],
    "closed_positions": [],

    "bot_status": "STOPPED",
    "protected_reason": None,

    "realized_pnl_today": 0.0,
    "daily_start_equity": 0.0,
    "daily_date": None,

    # ✅ رصيد البوت التجريبي (قد يتزامن لاحقاً مع paper.initial_balance)
    "paper_balance_usdt": 1000.0,

    "risk_meta": {
        "last_loss_time": 0.0,
        "last_closed_time_per_symbol": {}
    }
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def ensure_file(path: Path, default_data: dict):
    # ✅ تأكد من وجود المجلد
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(
            json.dumps(default_data, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"[INIT] Created {path}")
        return

    # لو الملف موجود لكن فاضي/تالف نحاول إصلاحه
    try:
        with path.open("r", encoding="utf-8") as f:
            json.load(f)
    except Exception:
        backup = path.with_suffix(path.suffix + ".bak")

        # ✅ backup سيذهب لنفس مجلد الملف (data أو state)
        try:
            path.rename(backup)
        except Exception:
            pass

        path.write_text(
            json.dumps(default_data, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"[FIX] Replaced corrupted {path.name}, backup saved as {backup.name}")


def main():
    os.chdir(PROJECT_ROOT)

    # ✅ تأكد من وجود ملفات الإعداد/الحالة في المسارات الجديدة
    ensure_file(SETTINGS_FILE, DEFAULT_SETTINGS)
    ensure_file(STATE_FILE, DEFAULT_STATE)

    # تشغيل الواجهة
    try:
        from ui.app import main as ui_main
    except Exception as e:
        print("[ERROR] Failed to import UI. Check your project structure.")
        print("Reason:", e)
        sys.exit(1)

    ui_main()


if __name__ == "__main__":
    main()
