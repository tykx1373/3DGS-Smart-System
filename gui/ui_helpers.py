# -*- coding: utf-8 -*-
"""界面小工具：标签行、路径选择行、时长格式化。

不依赖任何具体页面，页面与对话框共用。
"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
)

from pipeline_core import relativize_path


def _row(label, *widgets, tip=None, label_width=110):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label)
    lab.setFixedWidth(label_width)
    lay.addWidget(lab)
    for x in widgets:
        lay.addWidget(x)
    lay.addStretch(1)
    if tip:
        for t in (lab,) + widgets:
            t.setToolTip(tip)
    return w


def _path_row(parent, lay, label, var, file=True, tip=None, label_width=110):
    """一行「标签 + 路径输入框 + 浏览按钮」。设置页与训练设置页共用。"""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label)
    lab.setFixedWidth(label_width)
    h.addWidget(lab)
    edit = QLineEdit()
    edit.setText(var.get())
    if tip:
        edit.setToolTip(tip)
        lab.setToolTip(tip)
    btn = QPushButton("浏览")

    def pick():
        if file:
            p, _ = QFileDialog.getOpenFileName(parent, label)
        else:
            p = QFileDialog.getExistingDirectory(parent, label)
        if p:
            edit.setText(relativize_path(p))

    btn.clicked.connect(pick)
    h.addWidget(edit, 1)
    h.addWidget(btn)
    lay.addWidget(w)
    return edit


def _dur(sec):
    """人话时长：90 →「1 分 30 秒」。用于运行中的实时用时，秒级精度比「约 X 分钟」有用。"""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分"
    if m:
        return f"{m} 分 {s:02d} 秒"
    return f"{s} 秒"
