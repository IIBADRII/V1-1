# core/state_manager.py
from __future__ import annotations

import json
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# =========================
# Project Paths
# =========================
CORE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CORE_DIR.parent

STATE_DIR = PROJECT_ROOT / "state"
DEFAULT_STATE_PATH = STATE_DIR / "bot_state.json"
DEFAULT_STATE_BACKUP_PATH = Path(str(DEFAULT_STATE_PATH) + ".bak")


# =========================
# DEFAULT STATE
# =========================
DEFAULT_STATE: Dict[str, Any] = {
    "open_positions": [],     # list of position dicts
    "closed_positions": [],   # list of position dicts
    "watchlist": ["BTCUSDT"],
    "daily_start_equity": 0.0,
    "daily_date": None,       # "YYYY-MM-DD"
    "last_run_time": None,    # "YYYY-MM-DD HH:MM:SS"
    "bot_status": "STOPPED",

    # ✅ AI meta store
    "ai_meta": {},

    # ✅ risk meta store (used by RiskManager)
    "risk_meta": {
        "last_loss_time": 0.0,
        "last_closed_time_per_symbol": {},
    },
}


class StateManager:
    """
    Handles bot_state.json:
    - safe load with backup fallback
    - atomic save + optional backup
    - daily equity reset support
    - AI meta storage

    Default path:
        PROJECT_ROOT/state/bot_state.json
    """

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        backup_enabled: bool = True
    ) -> None:
        self.state_path = self._resolve_path(path)
        self.backup_path = Path(str(self.state_path) + ".bak")
        self.backup_enabled = bool(backup_enabled)

        self.state: Dict[str, Any] = self._deep_copy(DEFAULT_STATE)

        # Ensure directory exists early
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Migrate legacy files if needed
        self._migrate_legacy_root_state()

    # ---------- paths ----------

    def _resolve_path(self, path: Optional[Union[str, Path]]) -> Path:
        if path is None:
            return DEFAULT_STATE_PATH

        p = Path(path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    def _migrate_legacy_root_state(self) -> None:
        """
        If legacy state files exist in PROJECT_ROOT:
            bot_state.json
            bot_state.json.bak
        and new files don't exist in state/,
        move them.
        """
        # لو المستخدم مرر مسار مخصص مختلف، لا نتدخل
        if self.state_path != DEFAULT_STATE_PATH:
            return

        legacy_state = PROJECT_ROOT / "bot_state.json"
        legacy_bak = PROJECT_ROOT / "bot_state.json.bak"

        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Move main state
        if legacy_state.exists() and not self.state_path.exists():
            try:
                legacy_state.rename(self.state_path)
            except Exception:
                try:
                    self.state_path.write_text(legacy_state.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass

        # Move backup
        if legacy_bak.exists() and not self.backup_path.exists():
            try:
                legacy_bak.rename(self.backup_path)
            except Exception:
                try:
                    self.backup_path.write_text(legacy_bak.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass

    # ---------- public API ----------

    def load_state(self) -> Dict[str, Any]:
        """
        Load state from disk safely.
        If corrupted, tries backup, else defaults.
        """
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        loaded: Dict[str, Any] = {}

        if self.state_path.exists():
            try:
                loaded = self._read_json(self.state_path)
            except Exception:
                loaded = {}

        # fallback to backup
        if (not isinstance(loaded, dict) or not loaded) and self.backup_enabled and self.backup_path.exists():
            try:
                loaded = self._read_json(self.backup_path)
            except Exception:
                loaded = {}

        if not isinstance(loaded, dict):
            loaded = {}

        self.state = self._deep_merge(self._deep_copy(DEFAULT_STATE), loaded)

        # always update last_run_time
        self.state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ensure daily date exists
        if self.state.get("daily_date") is None:
            self.state["daily_date"] = date.today().isoformat()

        # ensure ai_meta dict
        if not isinstance(self.state.get("ai_meta"), dict):
            self.state["ai_meta"] = {}

        # ensure risk_meta dict
        if not isinstance(self.state.get("risk_meta"), dict):
            self.state["risk_meta"] = self._deep_copy(DEFAULT_STATE["risk_meta"])

        self.save_state()
        return self.state

    def save_state(self) -> None:
        """
        Atomic save, with optional backup of previous state.
        """
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Backup current state
        if self.backup_enabled and self.state_path.exists():
            try:
                shutil.copy2(self.state_path, self.backup_path)
            except Exception:
                pass

        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")

        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=4, ensure_ascii=False)

        tmp_path.replace(self.state_path)

    def get_state(self) -> Dict[str, Any]:
        return self.state

    def update(self, **kwargs: Any) -> None:
        self.state.update(kwargs)
        self.save_state()

    # ---------- Watchlist ----------

    def set_watchlist(self, symbols: List[str]) -> None:
        wl = [s.upper().strip() for s in symbols if s and isinstance(s, str)]
        self.state["watchlist"] = list(dict.fromkeys(wl))
        self.save_state()

    def add_symbol(self, symbol: str) -> None:
        s = str(symbol or "").upper().strip()
        if not s:
            return
        wl = self.state.get("watchlist", [])
        if not isinstance(wl, list):
            wl = []
        if s not in wl:
            wl.append(s)
            self.state["watchlist"] = wl
            self.save_state()

    def remove_symbol(self, symbol: str) -> None:
        s = str(symbol or "").upper().strip()
        wl = self.state.get("watchlist", [])
        if isinstance(wl, list) and s in wl:
            wl.remove(s)
            self.state["watchlist"] = wl
            self.save_state()

    # ---------- Positions ----------

    def set_open_positions(self, positions: List[Dict[str, Any]]) -> None:
        self.state["open_positions"] = positions if isinstance(positions, list) else []
        self.save_state()

    def set_closed_positions(self, positions: List[Dict[str, Any]]) -> None:
        self.state["closed_positions"] = positions if isinstance(positions, list) else []
        self.save_state()

    def get_open_positions(self) -> List[Dict[str, Any]]:
        ops = self.state.get("open_positions", [])
        return ops if isinstance(ops, list) else []

    def get_closed_positions(self) -> List[Dict[str, Any]]:
        cls = self.state.get("closed_positions", [])
        return cls if isinstance(cls, list) else []

    # ---------- Daily reset ----------

    def mark_new_day(self, daily_start_equity: float) -> None:
        self.state["daily_start_equity"] = float(daily_start_equity or 0.0)
        self.state["daily_date"] = date.today().isoformat()
        self.save_state()

    # ---------- AI Meta ----------

    def get_ai_meta(self) -> Dict[str, Any]:
        meta = self.state.get("ai_meta", {})
        return meta if isinstance(meta, dict) else {}

    def set_ai_meta(self, meta: Dict[str, Any], auto_save: bool = True) -> None:
        if not isinstance(meta, dict):
            meta = {}
        self.state["ai_meta"] = meta
        if auto_save:
            self.save_state()

    def update_ai_meta(self, **kwargs: Any) -> None:
        meta = self.get_ai_meta()
        meta.update(kwargs)
        self.state["ai_meta"] = meta
        self.save_state()

    # ---------- Risk Meta (اختياري لكن مفيد) ----------

    def get_risk_meta(self) -> Dict[str, Any]:
        rm = self.state.get("risk_meta", {})
        return rm if isinstance(rm, dict) else {}

    def set_risk_meta(self, meta: Dict[str, Any], auto_save: bool = True) -> None:
        if not isinstance(meta, dict):
            meta = {}
        self.state["risk_meta"] = meta
        if auto_save:
            self.save_state()

    # ---------- Manual reset ----------

    def clear_state(self) -> None:
        self.state = self._deep_copy(DEFAULT_STATE)
        self.save_state()

    # ---------- helpers ----------

    def _read_json(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in (override or {}).items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    def _deep_copy(self, d: Dict[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(d))
