from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    from PyQt5.QtCore import QUrl
    from PyQt5.QtMultimedia import QSoundEffect
    QT_SOUND_AVAILABLE = True
except Exception:
    QSoundEffect = None
    QUrl = None
    QT_SOUND_AVAILABLE = False

try:
    import winsound
    WINSOUND_AVAILABLE = True
except Exception:
    winsound = None
    WINSOUND_AVAILABLE = False


@dataclass
class SoundConfig:
    enabled: bool = False
    # حقل إضافي للتوافق مع استدعاء SoundConfig(sound_file=...)
    sound_file: Optional[str] = None

    # هذه الحقول الثلاثة يستخدمها كلاس SoundAlerts فعليًا
    notify_file: str = "data/sounds/notify.wav"
    entry_file: str = "data/sounds/entry.wav"
    exit_file: str = "data/sounds/exit.wav"

    volume: float = 0.9

    def __post_init__(self):
        """
        لو المشروع مرر sound_file فقط (زي ما يصير في main_window.py)
        نستخدمه كـ notify_file كصوت افتراضي.
        """
        if self.sound_file and self.notify_file == "data/sounds/notify.wav":
            self.notify_file = self.sound_file


class SoundAlerts:
    def __init__(self, config: Optional[SoundConfig] = None):
        self.config = config or SoundConfig()
        self._effect = None
        self._init_qt_effect()

    def _init_qt_effect(self):
        if not QT_SOUND_AVAILABLE:
            self._effect = None
            return
        try:
            self._effect = QSoundEffect()
            self._effect.setLoopCount(1)
            self._effect.setVolume(self.config.volume)
        except Exception as e:
            print(f"Failed to initialize QSoundEffect: {e}")
            self._effect = None

    def _play_file(self, file_path: str):
        if not self.config.enabled:
            return
        
        # Ensure the file exists
        if not os.path.exists(file_path):
            print(f"Sound file not found: {file_path}")
            return
            
        if QT_SOUND_AVAILABLE and self._effect:
            try:
                self._effect.setSource(QUrl.fromLocalFile(os.path.abspath(file_path)))
                self._effect.play()
            except Exception as e:
                print(f"Failed to play sound with Qt: {e}")
        elif WINSOUND_AVAILABLE and winsound:
            try:
                winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:
                print(f"Failed to play sound with winsound: {e}")

    def play_notify(self):
        self._play_file(self.config.notify_file)

    def play_entry(self):
        self._play_file(self.config.entry_file)

    def play_exit(self):
        self._play_file(self.config.exit_file)

    def apply_config(self, config: SoundConfig):
        self.config = config
        if QT_SOUND_AVAILABLE and self._effect:
            try:
                self._effect.setVolume(self.config.volume)
            except Exception as e:
                print(f"Failed to set volume: {e}")