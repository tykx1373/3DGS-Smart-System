# -*- coding: utf-8 -*-
"""纯 PySide6 的界面主题与轻量组件（无第三方 UI 库依赖）。

只用 Qt 自带控件 + QSS 实现 Win11 风格外观，避免引入 GPLv3 的
PySide6-Fluent-Widgets。PySide6 本身为 LGPLv3，动态链接可自由分发。

本模块全部为本项目原创代码，随项目以 Apache-2.0 许可发布。
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QPushButton, QMessageBox, QGraphicsDropShadowEffect,
)

FONT_FAMILY = "Microsoft YaHei UI"
ACCENT = "#0f6cbd"          # Win11 蓝
ACCENT_HOVER = "#2b88d6"
ACCENT_PRESSED = "#0d5fa6"
ACCENT_SOFT_LIGHT = "#e3f0fb"
ACCENT_SOFT_DARK = "#1c3a52"

_PALETTES = {
    "light": {
        "window": "#f3f3f3", "sidebar": "#eaeaea", "card": "#ffffff",
        "text": "#1f1f1f", "subtext": "#6b6b6b", "border": "#d4d4d4",
        "input_bg": "#ffffff", "hover": "#ececec", "selected": "#dcebf8",
        "log_bg": "#1e1e1e", "tooltip_bg": "#2b2b2b", "tooltip_fg": "#f0f0f0",
        "accent_soft": ACCENT_SOFT_LIGHT,
    },
    "dark": {
        "window": "#1f1f1f", "sidebar": "#262626", "card": "#2b2b2b",
        "text": "#e8e8e8", "subtext": "#9a9a9a", "border": "#3f3f3f",
        "input_bg": "#262626", "hover": "#333333", "selected": "#1c3a52",
        "log_bg": "#181818", "tooltip_bg": "#f0f0f0", "tooltip_fg": "#1f1f1f",
        "accent_soft": ACCENT_SOFT_DARK,
    },
}

_QSS = """
* {{ font-family: "{family}"; font-size: 13px; }}
QMainWindow, QDialog {{ background: {window}; }}
QLabel {{ background: transparent; color: {text}; }}
QLabel#caption {{ color: {subtext}; font-size: 12px; }}
QLabel#title {{ font-size: 22px; font-weight: 700; }}
QLabel#subtitle {{ font-size: 14px; font-weight: 600; }}

QFrame#card {{ background: {card}; border: 1px solid {border};
              border-radius: 8px; }}

QListWidget#nav {{ background: {sidebar}; border: none; font-size: 14px;
                  padding: 8px 6px; }}
QListWidget#nav::item {{ padding: 10px 14px; border-radius: 6px; margin: 2px 4px;
                         color: {text}; }}
QListWidget#nav::item:hover {{ background: {hover}; }}
QListWidget#nav::item:selected {{ background: {accent_soft};
                                  color: {accent}; font-weight: 600; }}

QPushButton {{ background: {card}; color: {text};
              border: 1px solid {border}; border-radius: 6px;
              padding: 7px 16px; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {subtext}; border-color: {border}; }}
QPushButton#primary {{ background: {accent}; color: #ffffff; border: none;
                       font-weight: 600; padding: 8px 18px; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#primary:pressed {{ background: {accent_pressed}; }}
QPushButton#primary:disabled {{ background: {border}; color: {subtext}; }}

QLineEdit, QComboBox, QSpinBox {{ background: {input_bg}; color: {text};
    border: 1px solid {border}; border-radius: 5px; padding: 6px 8px;
    selection-background-color: {accent}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {card}; color: {text};
                               border: 1px solid {border}; selection-background-color: {selected}; }}

QProgressBar {{ background: {border}; border: none; border-radius: 3px;
                height: 6px; text-align: center; color: {subtext}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

QTableWidget {{ background: {card}; color: {text}; gridline-color: {border};
                border: 1px solid {border}; border-radius: 6px; }}
QTableWidget::item {{ padding: 4px; }}
QTableWidget::item:selected {{ background: {selected}; color: {text}; }}
QHeaderView::section {{ background: {sidebar}; color: {text};
                        border: none; border-bottom: 1px solid {border};
                        padding: 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {sidebar}; border: none; }}

QTextEdit, QPlainTextEdit {{ background: {log_bg}; color: #d4d4d4;
    border: 1px solid {border}; border-radius: 6px; }}

QToolTip {{ background: {tooltip_bg}; color: {tooltip_fg};
            border: none; padding: 5px 8px; }}

QFrame#toast {{ border-radius: 8px; }}
QFrame#toast_info {{ background: {card}; border: 1px solid {border};
                    border-left: 4px solid {accent}; }}
QFrame#toast_success {{ background: {card}; border: 1px solid {border};
                        border-left: 4px solid #16a34a; }}
QFrame#toast_warning {{ background: {card}; border: 1px solid {border};
                        border-left: 4px solid #d97706; }}
QFrame#toast_error {{ background: {card}; border: 1px solid {border};
                      border-left: 4px solid #dc2626; }}
"""


def current_scheme():
    """跟随系统深浅色；未知时按浅色。"""
    app = QApplication.instance()
    if app is None:
        return "light"
    try:
        return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "light"


def build_qss(scheme=None):
    p = _PALETTES[scheme or current_scheme()]
    return _QSS.format(family=FONT_FAMILY, accent=ACCENT,
                       accent_hover=ACCENT_HOVER, accent_pressed=ACCENT_PRESSED, **p)


def apply_theme(app):
    """应用主题，并跟随系统深浅色自动切换。"""
    app.setStyleSheet(build_qss())
    try:
        app.styleHints().colorSchemeChanged.connect(lambda _s: app.setStyleSheet(build_qss()))
    except Exception:
        pass


# --------------------------------------------------------------- 组件工厂 ----
def make_label(text="", kind="body"):
    """kind: title / subtitle / body / caption。"""
    lab = QLabel(text)
    if kind == "title":
        lab.setObjectName("title")
        lab.setFont(QFont(FONT_FAMILY, 16, QFont.Bold))
    elif kind == "subtitle":
        lab.setObjectName("subtitle")
        lab.setFont(QFont(FONT_FAMILY, 12, QFont.DemiBold))
    elif kind == "caption":
        lab.setObjectName("caption")
        lab.setWordWrap(True)
    return lab


class Card(QFrame):
    """带标题的卡片容器，.body_layout 为内容区布局。"""

    def __init__(self, title=None):
        super().__init__()
        self.setObjectName("card")
        outer = __import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(8)
        if title:
            outer.addWidget(make_label(title, "subtitle"))
        self.body_layout = outer


class PrimaryButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("primary")
        self.setCursor(Qt.PointingHandCursor)


# ------------------------------------------------------------------ Toast ----
_TOAST_COLORS = {
    "info": ("#0f6cbd", "提示"),
    "success": ("#16a34a", "成功"),
    "warning": ("#d97706", "警告"),
    "error": ("#dc2626", "错误"),
}


class Toast(QFrame):
    """轻量顶部通知条（替代 InfoBar）：自动消失，不抢焦点。"""

    def __init__(self, parent, title, message, kind="info"):
        super().__init__(parent)
        self.setObjectName(f"toast_{kind}")
        lay = __import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(2)
        t = QLabel(title or _TOAST_COLORS.get(kind, ("", ""))[1])
        color = _TOAST_COLORS.get(kind, ("#0f6cbd",))[0]
        t.setStyleSheet(f"color:{color}; font-weight:600; background:transparent;")
        m = QLabel(message)
        m.setWordWrap(True)
        m.setStyleSheet("background:transparent;")
        lay.addWidget(t)
        lay.addWidget(m)
        self.setMaximumWidth(420)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

    @staticmethod
    def show_toast(parent, title, message, kind="info", duration=2800):
        host = parent.window() if parent is not None else QApplication.activeWindow()
        if host is None:
            return
        toast = Toast(host, title, message, kind)
        toast.adjustSize()
        x = (host.width() - toast.width()) // 2
        toast.move(max(12, x), 18)
        toast.show()
        toast.raise_()
        QTimer.singleShot(duration, toast.close)


# --------------------------------------------------------------- 对话框 ----
def confirm(parent, title, text, ok_text="确定", cancel_text="取消"):
    """是/否确认框，返回是否点了确定。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    ok = box.addButton(ok_text, QMessageBox.AcceptRole)
    box.addButton(cancel_text, QMessageBox.RejectRole)
    box.setDefaultButton(ok)
    return box.exec() == QMessageBox.AcceptRole and box.clickedButton() is ok
