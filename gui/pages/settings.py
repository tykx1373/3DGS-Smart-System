# -*- coding: utf-8 -*-
"""设置页：工具路径。"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
)

from qt_theme import Card, make_label
from ui_helpers import _path_row


class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("settingsPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(make_label("设置", "title"))
        root.addWidget(make_label("只在工具路径变动时需要来这一页；训练参数在「训练设置」页。",
                                  "caption"))

        card = Card("工具路径")
        win.colmap_edit = _path_row(
            self, card.body_layout, "COLMAP:", win.colmap_var,
            file=True, tip="COLMAP.bat 或 colmap.exe，留空则自动选择。")
        win.vkpy_edit = _path_row(
            self, card.body_layout, "VkSplat Python:", win.vksplat_py_var,
            file=True, tip="运行训练的 Python，通常为 env/vksplat/python.exe。")
        win.vkgs_edit = _path_row(
            self, card.body_layout, "VKGS 查看器:", win.vkgs_var,
            file=True, tip="vk_gaussian_splatting.exe，缺失不影响训练。")
        root.addWidget(card)

        card = Card("保存")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        b = QPushButton("保存设置")
        b.clicked.connect(win.save_options)
        rl.addWidget(b)
        rl.addStretch(1)
        card.body_layout.addWidget(row)
        root.addWidget(card)
        root.addStretch(1)
