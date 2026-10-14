# -*- coding: utf-8 -*-
"""纯 PySide6 的界面主题与轻量组件（无第三方 UI 库依赖）。

只用 Qt 自带控件 + QSS 实现 Win11 Fluent 风格外观，避免引入 GPLv3 的
PySide6-Fluent-Widgets。PySide6 本身为 LGPLv3，动态链接可自由分发。

勾选/箭头等小图标在首次应用主题时用 QPainter 自绘到临时目录（本项目原创
资源），QSS 通过文件 URL 引用。

本模块全部为本项目原创代码，随项目以 Apache-2.0 许可发布。
"""
import os
import tempfile

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QFont, QColor, QPainter, QPixmap, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QPushButton, QMessageBox,
    QGraphicsDropShadowEffect, QVBoxLayout,
)

FONT_FAMILY = "Microsoft YaHei UI"
ACCENT = "#0078d4"          # Win11 Fluent 蓝
ACCENT_HOVER = "#1984d9"
ACCENT_PRESSED = "#0067b8"
GREEN = "#0f7b0f"           # 深色系文字用的低饱和绿
GREEN_BRIGHT = "#16a34a"
ORANGE = "#ca8a04"
RED = "#c42b1c"

_PALETTES = {
    "light": {
        "window": "#f3f3f3", "sidebar": "#fafafa", "card": "#ffffff",
        "card_border": "#e4e4e4", "text": "#1a1a1a", "subtext": "#6b6b6b",
        "border": "#d1d1d1", "input_bg": "#ffffff", "hover": "#efefef",
        "pressed": "#e4e4e4", "selected": "#e8f1fb", "accent_text": "#0067b8",
        "log_bg": "#1b1b1b", "scroll": "#c6c6c6",
        "indicator_border": "#707070", "arrow": "#5b5b5b",
        "shadow": (0, 0, 0, 22),
    },
    "dark": {
        "window": "#1f1f1f", "sidebar": "#252525", "card": "#2b2b2b",
        "card_border": "#3d3d3d", "text": "#f3f3f3", "subtext": "#a0a0a0",
        "border": "#434343", "input_bg": "#313131", "hover": "#363636",
        "pressed": "#3f3f3f", "selected": "#0e3a5c", "accent_text": "#4cc2ff",
        "log_bg": "#181818", "scroll": "#555555",
        "indicator_border": "#8a8a8a", "arrow": "#c8c8c8",
        "shadow": (0, 0, 0, 90),
    },
}

# 自绘图标缓存：scheme -> {name: path}
_asset_dir = None
_asset_cache = {}


def _ensure_asset_dir():
    global _asset_dir
    if _asset_dir is None:
        _asset_dir = tempfile.mkdtemp(prefix="3dgs_icons_")
    return _asset_dir


def _save_icon(name, draw, size=32):
    """在透明画布上自绘一个图标，返回文件 URL 友好路径（正斜杠）。"""
    d = _ensure_asset_dir()
    path = os.path.join(d, name).replace("\\", "/")
    if not os.path.exists(path):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        draw(p, size)
        p.end()
        pm.save(path, "PNG")
    return path


def _check_icon(color):
    def draw(p, s):
        pen = QPen(QColor(color))
        pen.setWidth(3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.22, s * 0.52)
        path.lineTo(s * 0.42, s * 0.72)
        path.lineTo(s * 0.78, s * 0.28)
        p.drawPath(path)
    return _save_icon(f"check_{_hex(color)}.png", draw)


def _dot_icon(color):
    def draw(p, s):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40))
    return _save_icon(f"dot_{_hex(color)}.png", draw)


def _chevron(color, up=False, down=True):
    def draw(p, s):
        pen = QPen(QColor(color))
        pen.setWidth(2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        if up:
            a, b, c = (s * 0.30, s * 0.62), (s * 0.5, s * 0.40), (s * 0.70, s * 0.62)
        else:
            a, b, c = (s * 0.30, s * 0.40), (s * 0.5, s * 0.62), (s * 0.70, s * 0.40)
        path = QPainterPath(QPointF(*a))
        path.lineTo(*b)
        path.lineTo(*c)
        p.drawPath(path)
    n = "up" if up else "down"
    return _save_icon(f"chev_{n}_{_hex(color)}.png", draw, 20)


def _hex(c):
    return c.replace("#", "")


def _icons(scheme):
    key = ("icons", scheme)
    if key in _asset_cache:
        return _asset_cache[key]
    check = _check_icon("#ffffff")
    dot = _dot_icon("#ffffff")
    arrow = _chevron(_PALETTES[scheme]["arrow"])
    up = _chevron(_PALETTES[scheme]["arrow"], up=True)
    _asset_cache[key] = dict(check=check, dot=dot, arrow=arrow, up=up)
    return _asset_cache[key]


def _qss(scheme, ic):
    p = _PALETTES[scheme]
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: 13px; color: {p['text']}; }}
QMainWindow, QDialog {{ background: {p['window']}; }}
QToolTip {{ background: #2b2b2b; color: #ffffff; border: none;
            padding: 6px 9px; border-radius: 5px; }}

/* -------- 侧栏 -------- */
QWidget#sidebar {{ background: {p['sidebar']};
                   border-right: 1px solid {p['card_border']}; }}
QLabel#brandName {{ font-size: 14px; font-weight: 700; }}
QLabel#brandSub {{ color: {p['subtext']}; font-size: 11px; }}
QLabel#logo {{ background: {ACCENT}; border-radius: 8px; color: #ffffff;
               font-size: 15px; font-weight: 800; }}
QListWidget#nav {{ background: transparent; border: none;
                  padding: 6px 10px; font-size: 14px; outline: none; }}
QListWidget#nav::item {{ height: 40px; padding-left: 14px;
                         border-radius: 7px; margin: 2px 0px; color: {p['text']}; }}
QListWidget#nav::item:hover {{ background: {p['hover']}; }}
QListWidget#nav::item:selected {{ background: {p['selected']};
                                   color: {p['accent_text']}; font-weight: 600; }}

/* -------- 文字层级 -------- */
QLabel#caption {{ color: {p['subtext']}; font-size: 12px; }}
QLabel#title {{ font-size: 23px; font-weight: 700; }}
QLabel#subtitle {{ font-size: 15px; font-weight: 600; }}

/* -------- 卡片 -------- */
QFrame#card {{ background: {p['card']};
               border: 1px solid {p['card_border']}; border-radius: 10px; }}

/* -------- 按钮 -------- */
QPushButton {{ background: {p['card']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 6px;
               padding: 8px 18px; min-height: 18px; }}
QPushButton:hover {{ background: {p['hover']}; border-color: {p['accent_text']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton:disabled {{ color: {p['subtext']}; background: {p['card']};
                         border-color: {p['card_border']}; }}
QPushButton#primary {{ background: {ACCENT}; color: #ffffff; border: none;
                       font-weight: 600; padding: 9px 22px; border-radius: 6px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: {p['pressed']}; color: {p['subtext']}; }}

/* -------- 输入控件 -------- */
QLineEdit, QComboBox, QSpinBox {{ background: {p['input_bg']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 6px;
    padding: 7px 10px; min-height: 18px;
    selection-background-color: {ACCENT}; selection-color: #fff; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {p['accent_text']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1.5px solid {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {p['subtext']}; background: {p['hover']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{ic['arrow']}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {p['card']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 6px;
    selection-background-color: {p['selected']}; selection-color: {p['accent_text']};
    outline: none; padding: 4px; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
                       width: 22px; border: none; border-left: 1px solid {p['card_border']}; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
                         width: 22px; border: none; border-left: 1px solid {p['card_border']}; }}
QSpinBox::up-arrow {{ image: url("{ic['up']}"); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url("{ic['arrow']}"); width: 9px; height: 9px; }}

/* -------- 复选 / 单选 -------- */
QCheckBox, QRadioButton {{ background: transparent; spacing: 9px; padding: 3px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px;
    border: 1.5px solid {p['indicator_border']}; background: transparent; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1.5px solid {ACCENT};
                                 image: url("{ic['check']}"); }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 1.5px solid {ACCENT};
                                    image: url("{ic['dot']}"); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {p['border']}; }}

/* -------- 进度条 -------- */
QProgressBar {{ background: {p['pressed']}; border: none; border-radius: 4px;
                height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

/* -------- 表格 -------- */
QTableWidget {{ background: {p['card']}; color: {p['text']};
                 gridline-color: {p['card_border']}; alternate-background-color: {p['hover']};
                 border: 1px solid {p['card_border']}; border-radius: 8px;
                 outline: none; }}
QTableWidget::item {{ padding: 5px 8px; border: none; }}
QTableWidget::item:hover {{ background: {p['hover']}; }}
QTableWidget::item:selected {{ background: {p['selected']}; color: {p['accent_text']}; }}
QHeaderView::section {{ background: {p['sidebar']}; color: {p['text']};
                         border: none; border-bottom: 1px solid {p['card_border']};
                         border-right: 1px solid {p['card_border']};
                         padding: 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {p['sidebar']}; border: none; }}

/* -------- 日志 -------- */
QTextEdit, QPlainTextEdit {{ background: {p['log_bg']}; color: #d8d8d8;
    border: 1px solid {p['card_border']}; border-radius: 8px; padding: 4px; }}

/* -------- 滚动条 -------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['scroll']}; border-radius: 4px;
                                min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {p['accent_text']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['scroll']}; border-radius: 4px;
                                  min-width: 36px; }}
QScrollBar::handle:horizontal:hover {{ background: {p['accent_text']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* -------- 菜单 -------- */
QMenu {{ background: {p['card']}; border: 1px solid {p['border']};
          border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p['selected']}; color: {p['accent_text']}; }}

/* -------- Toast -------- */
QFrame#toast {{ border-radius: 9px; }}
QFrame#toast_info {{ background: {p['card']}; border: 1px solid {p['card_border']};
                     border-left: 4px solid {ACCENT}; }}
QFrame#toast_success {{ background: {p['card']}; border: 1px solid {p['card_border']};
                         border-left: 4px solid {GREEN_BRIGHT}; }}
QFrame#toast_warning {{ background: {p['card']}; border: 1px solid {p['card_border']};
                         border-left: 4px solid #f59e0b; }}
QFrame#toast_error {{ background: {p['card']}; border: 1px solid {p['card_border']};
                       border-left: 4px solid {RED}; }}
"""


def current_scheme():
    app = QApplication.instance()
    if app is None:
        return "light"
    try:
        return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "light"


def build_qss(scheme=None):
    scheme = scheme or current_scheme()
    return _qss(scheme, _icons(scheme))


def apply_theme(app):
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
    elif kind == "subtitle":
        lab.setObjectName("subtitle")
    elif kind == "caption":
        lab.setWordWrap(True)
        lab.setObjectName("caption")
    return lab


class Card(QFrame):
    """带标题的卡片容器；.body_layout 为内容区布局。"""

    def __init__(self, title=None):
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(10)
        if title:
            outer.addWidget(make_label(title, "subtitle"))
        self.body_layout = outer
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        scheme = current_scheme()
        r, g, b, a = _PALETTES[scheme]["shadow"]
        shadow.setColor(QColor(r, g, b, a))
        self.setGraphicsEffect(shadow)


class PrimaryButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("primary")
        self.setCursor(Qt.PointingHandCursor)


# ------------------------------------------------------------------ Toast ----
_TOAST_TITLE = {"info": "提示", "success": "成功", "warning": "警告", "error": "错误"}
_TOAST_COLOR = {"info": ACCENT, "success": GREEN_BRIGHT,
                "warning": "#f59e0b", "error": RED}


class Toast(QFrame):
    """轻量顶部通知条：自动消失，不抢焦点。"""

    def __init__(self, parent, title, message, kind="info"):
        super().__init__(parent)
        self.setObjectName(f"toast_{kind}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 10, 16, 10)
        lay.setSpacing(2)
        t = QLabel(title or _TOAST_TITLE.get(kind, "提示"))
        t.setStyleSheet(f"color:{_TOAST_COLOR.get(kind, ACCENT)};"
                        "font-weight:600; background:transparent; border:none;")
        m = QLabel(message)
        m.setWordWrap(True)
        m.setStyleSheet("background:transparent; border:none;")
        lay.addWidget(t)
        lay.addWidget(m)
        self.setMaximumWidth(420)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

    @staticmethod
    def show_toast(parent, title, message, kind="info", duration=2800):
        host = parent.window() if parent is not None else QApplication.activeWindow()
        if host is None:
            return
        toast = Toast(host, title, message, kind)
        toast.adjustSize()
        x = (host.width() - toast.width()) // 2
        toast.move(max(12, x), 20)
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
    box.exec()
    return box.clickedButton() is ok
