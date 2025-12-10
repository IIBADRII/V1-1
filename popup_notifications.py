# ui/notifications.py
from __future__ import annotations

from typing import Optional, List

from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QApplication
)


class NotificationWidget(QFrame):
    """
    مربع تنبيه صغير (Toast) يُعرض لفترة قصيرة ثم يختفي تلقائيًا.
    لا يعتمد على أي كلاس خارجي — مجرد QWidget بسيط.
    """

    def __init__(self, title: str, message: str, level: str = "info", parent: Optional[QWidget] = None):
        super().__init__(parent, flags=Qt.ToolTip)
        self.setObjectName("Toast")
        self.setWindowFlags(
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)

        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)

        frame = QFrame()
        frame.setObjectName("ToastFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(12, 8, 12, 10)
        frame_layout.setSpacing(6)

        # العنوان + لون حسب المستوى
        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Roboto", 11, QFont.Bold))

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setFont(QFont("Roboto", 10))

        frame_layout.addWidget(title_lbl)
        frame_layout.addWidget(msg_lbl)
        main.addWidget(frame)

        # ألوان حسب level
        if level == "success":
            frame.setStyleSheet("""
            QFrame#ToastFrame {
                background: #123722;
                color: #e9ffe9;
                border-radius: 10px;
                border: 1px solid #1f7a3c;
            }""")
        elif level == "warning":
            frame.setStyleSheet("""
            QFrame#ToastFrame {
                background: #3c2d12;
                color: #fff6e0;
                border-radius: 10px;
                border: 1px solid #c28b23;
            }""")
        elif level == "error":
            frame.setStyleSheet("""
            QFrame#ToastFrame {
                background: #3c1414;
                color: #ffeaea;
                border-radius: 10px;
                border: 1px solid #c24343;
            }""")
        else:  # info
            frame.setStyleSheet("""
            QFrame#ToastFrame {
                background: #1b2433;
                color: #e6ecff;
                border-radius: 10px;
                border: 1px solid #34425c;
            }""")

        # إغلاق تلقائي بعد مدة
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.close)

    def show_for(self, ms: int):
        self._auto_close_timer.start(ms)
        self.show()


class NotificationManager:
    """
    مدير التنبيهات:
    - يعرض Toast أعلى يمين نافذة الـ MainWindow
    - يكدّس التنبيهات تحت بعض
    - دوال جاهزة:
        show_info / show_success / show_warning / show_error
    """

    def __init__(self, parent_window: QWidget):
        self.parent = parent_window
        self._active: List[NotificationWidget] = []
        self.margin = 16
        self.spacing = 8
        self.duration_ms = 3500  # مدة ظهور التنبيه

    # ------------ واجهة عامة ------------

    def show_info(self, title: str, message: str):
        self._show(title, message, "info")

    def show_success(self, title: str, message: str):
        self._show(title, message, "success")

    def show_warning(self, title: str, message: str):
        self._show(title, message, "warning")

    def show_error(self, title: str, message: str):
        self._show(title, message, "error")

    # ------------ داخلي ------------

    def _show(self, title: str, message: str, level: str):
        toast = NotificationWidget(title, message, level, parent=self.parent)
        toast.destroyed.connect(self._on_toast_destroyed)
        self._active.append(toast)
        self._reposition()
        toast.show_for(self.duration_ms)

    def _on_toast_destroyed(self, obj):
        # تنظيف القائمة عند الإغلاق
        self._active = [t for t in self._active if not sip_is(obj, t)]
        self._reposition()

    def _reposition(self):
        if not self.parent.isVisible():
            return

        # نحسب زاوية أعلى يمين النافذة
        parent_geo = self.parent.geometry()
        x_right = parent_geo.x() + parent_geo.width() - self.margin

        y = parent_geo.y() + self.margin
        for toast in self._active:
            toast.adjustSize()
            tw = toast.width()
            th = toast.height()
            tx = x_right - tw
            toast.move(QPoint(tx, y))
            y += th + self.spacing


def sip_is(obj, widget):
    """
    مقارنة آمنة بين QObject.destroyed signal parameter و widget.
    بعض الإصدارات ترسل sip.wrapper مختلف، فنستخدم id().
    """
    try:
        return int(obj) == int(widget)
    except Exception:
        return obj is widget


# اختبار يدوي سريع
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QMainWindow, QPushButton

    app = QApplication(sys.argv)
    win = QMainWindow()
    win.resize(800, 600)
    win.show()

    mgr = NotificationManager(win)

    btn = QPushButton("Test Notifications", win)
    btn.move(50, 50)

    def on_click():
        mgr.show_info("معلومة", "هذا تنبيه معلوماتي.")
        mgr.show_success("نجاح", "تم فتح صفقة جديدة ✅")
        mgr.show_warning("تحذير", "اقتربت من حد الخسارة اليومي.")
        mgr.show_error("خطأ", "فشل الاتصال بـ Binance.")

    btn.clicked.connect(on_click)

    sys.exit(app.exec_())
