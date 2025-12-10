# core/logger.py
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Union


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    timestamp: datetime
    level: Union[LogLevel, str]
    message: str

    def format(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        lvl = getattr(self.level, "value", str(self.level))
        return f"[{ts}] [{lvl}] {self.message}"


class Logger:
    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_in_memory: int = 1000,
        write_to_file: bool = True,
        min_level: str = "INFO",
    ) -> None:
        self.entries: List[LogEntry] = []
        self.max_in_memory = max_in_memory
        self.write_to_file = write_to_file
        self.min_level = self._normalize_level(min_level)
        self.log_dir = log_dir or Path("data") / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._listeners: List[Callable[[LogEntry], None]] = []
        self._lock = threading.RLock()

    def add_listener(self, fn: Callable[[LogEntry], None]) -> None:
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[LogEntry], None]) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def _emit(self, entry: LogEntry) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(entry)
            except Exception:
                pass

    def _normalize_level(self, level: Union[LogLevel, str, None]) -> LogLevel:
        if isinstance(level, LogLevel):
            return level
        if isinstance(level, str):
            try:
                return LogLevel[level]
            except KeyError:
                for m in LogLevel:
                    if m.value == level:
                        return m
        return LogLevel.INFO

    def _should_log(self, level: LogLevel) -> bool:
        """تحقق إذا كان المستوى مهم بما يكفي للتسجيل"""
        level_priority = {
            LogLevel.CRITICAL: 5,
            LogLevel.ERROR: 4,
            LogLevel.WARNING: 3,
            LogLevel.INFO: 2,
            LogLevel.DEBUG: 1,
        }
        min_priority = level_priority.get(self.min_level, 2)
        current_priority = level_priority.get(level, 1)
        return current_priority >= min_priority

    def log(self, message: str, level: Union[LogLevel, str] = LogLevel.INFO) -> None:
        lvl = self._normalize_level(level)
        
        # ✅ فقط سجّل إذا كان المستوى مهم
        if not self._should_log(lvl):
            return
            
        entry = LogEntry(timestamp=datetime.now(), level=lvl, message=message)

        with self._lock:
            self.entries.append(entry)
            if len(self.entries) > self.max_in_memory:
                self.entries = self.entries[-self.max_in_memory:]

        # ✅ اطبع فقط الأشياء المهمة
        if lvl in [LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.INFO]:
            try:
                print(entry.format())
            except Exception:
                pass

        if self.write_to_file:
            self._write_daily(entry)

        self._emit(entry)

    def debug(self, message: str) -> None:
        self.log(message, LogLevel.DEBUG)

    def info(self, message: str) -> None:
        self.log(message, LogLevel.INFO)

    def warning(self, message: str) -> None:
        self.log(message, LogLevel.WARNING)

    def error(self, message: str) -> None:
        self.log(message, LogLevel.ERROR)

    def critical(self, message: str) -> None:
        self.log(message, LogLevel.CRITICAL)

    def clear_memory(self) -> None:
        with self._lock:
            self.entries.clear()

    def export_memory_text(self) -> str:
        with self._lock:
            return "\n".join(e.format() for e in self.entries)

    def _write_daily(self, entry: LogEntry) -> None:
        date_str = entry.timestamp.strftime("%Y-%m-%d")
        path = self.log_dir / f"{date_str}.txt"
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(entry.format() + "\n")
        except Exception:
            pass