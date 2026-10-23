# -*- coding: utf-8 -*-
"""运行日志页。"""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
)

from qt_theme import make_label


class LogPage(QWidget):
    COLORS = {"info": "#c8c8c8", "warn": "#f59e0b", "fail": "#ef4444",
              "ok": "#22c55e", "dbg": "#9ca3af"}

    def __init__(self, win):
        super().__init__()
        self.setObjectName("logPage")
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        head = QHBoxLayout()
        head.addWidget(make_label("运行日志", "title"))
        head.addStretch(1)
        diag = QPushButton("导出诊断包")
        diag.setToolTip("把最近日志、自检结果和配置打包（路径已隐去），发给开发者排查问题。")
        diag.clicked.connect(win.export_diagnostics)
        head.addWidget(diag)
        clear = QPushButton("清空")
        clear.clicked.connect(lambda: self.view.clear())
        head.addWidget(clear)
        lay.addLayout(head)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 10))
        # 长时间训练会累积上万行；超出后自动丢弃最早的，内存不会一直涨
        self.view.document().setMaximumBlockCount(5000)
        lay.addWidget(self.view, 1)

    def append_line(self, text, level):
        import html
        color = self.COLORS.get(level, "#c8c8c8")
        bar = self.view.verticalScrollBar()
        # 只有本来就停在底部才跟着滚。用户往上翻看历史时，
        # 继续强制滚动会把他不断拽回最新一行（长任务里非常恼人）。
        at_bottom = bar.value() >= bar.maximum() - 4
        self.view.append(f'<span style="color:{color}">{html.escape(text)}</span>')
        if at_bottom:
            bar.setValue(bar.maximum())
