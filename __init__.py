# ui/__init__.py
from __future__ import annotations

"""
حزمة واجهة المستخدم (UI) الخاصة ببوت التداول.

هذا الملف يجمع أهم الكلاسات التي نحتاجها من الواجهات المختلفة
لتسهيل استيرادها في باقي أجزاء المشروع.
"""

from ui.home_page import HomePage
from ui.strategies_page import StrategiesPage

from ui.coin_details_dialog import CoinDetailsDialog
from ui.manual_close_dialog import ManualCloseDialog

from ui.notifications import NotificationManager
from ui.watchlist_integrations import WatchlistDetailsController, attach_watchlist_details

from ui.sound_alerts import SoundAlerts, SoundConfig

__all__ = [
    "HomePage",
    "StrategiesPage",
    "CoinDetailsDialog",
    "ManualCloseDialog",
    "NotificationManager",
    "WatchlistDetailsController",
    "attach_watchlist_details",
    "SoundAlerts",
    "SoundConfig",
]

__version__ = "7.0.0"
