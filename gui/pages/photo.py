# -*- coding: utf-8 -*-
"""第 1 步：选择照片（含本地预检与环境自检入口）。"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from qt_theme import Card, PrimaryButton, make_label


class PhotoPage(QWidget):
    """只管一件事：把照片选对。选完就地预检，不合格当场说。"""

    def __init__(self, win):
        super().__init__()
        self.setObjectName("photoPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(make_label("1 · 选择照片", "title"))
        root.addWidget(make_label("把你拍的一组照片变成可旋转、可缩放的 3D 模型。", "caption"))

        # 环境自检是「开跑之前」的预备动作，属于第一步；放在运行页会和
        # 重新生成/停止这些跑起来后才用的按钮混在一起。
        pre = QWidget()
        pl = QHBoxLayout(pre)
        pl.setContentsMargins(0, 0, 0, 0)
        win.check_btn = QPushButton("环境自检")
        win.check_btn.setFixedHeight(36)
        win.check_btn.setToolTip(
            "检查显卡、COLMAP 与训练环境，并给出本次的耗时预估。\n"
            "第一次使用、或换了新电脑时先点一次，能避免跑到一半才发现跑不动。")
        win.check_btn.clicked.connect(lambda: win.open_syscheck())
        pl.addWidget(win.check_btn)
        pl.addWidget(make_label(
            "第一次使用、或换了新电脑，建议先点一次：确认这台机器能跑，并看看大概要等多久。",
            "caption"), 1)
        root.addWidget(pre)

        card = Card("照片文件夹")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("照片文件夹："))
        win.img_edit = QLineEdit()
        win.img_edit.setPlaceholderText("点击右侧选择存放照片的文件夹")
        win.img_edit.setToolTip("支持 jpg/jpeg/png/bmp/tif/tiff；建议 30~200 张，每张重叠 60% 以上。")
        rl.addWidget(win.img_edit, 1)
        b = QPushButton("浏览…")
        b.clicked.connect(win.browse_img)
        rl.addWidget(b)
        card.body_layout.addWidget(row)
        card.body_layout.addWidget(
            make_label("拍照小技巧：绕物体一圈拍，每张重叠 60% 以上，建议 30~200 张。", "caption"))
        # 手边没有适合的照片时，第一次不应该拿自己的照片去冒险失败。
        win.sample_btn = QPushButton("手边没合适的照片？用内置示例照片试跑一次")
        win.sample_btn.setToolTip(
            "用随安装包附带的示例照片完整跑一遍：\n"
            "先确认这台机器能出模型，再决定用自己的照片认真拍。")
        win.sample_btn.clicked.connect(win.use_sample)
        win.sample_btn.setVisible(win.sample_ready())
        card.body_layout.addWidget(win.sample_btn)
        # 选完照片就地给一句本地检查结论，不用等 COLMAP 跑完才回头说照片不行
        win.photo_note = make_label("", "caption")
        win.photo_note.setVisible(False)
        card.body_layout.addWidget(win.photo_note)
        root.addWidget(card)

        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        win.next_btn = PrimaryButton("下一步：训练设置 →")
        win.next_btn.setFixedHeight(40)
        win.next_btn.setMinimumWidth(180)
        win.next_btn.setToolTip("先选好照片，再进入训练设置。")
        win.next_btn.clicked.connect(
            lambda: win.nav.setCurrentRow(win.NAV.index("训练设置")))
        bl.addWidget(win.next_btn)
        bl.addStretch(1)
        root.addWidget(brow)
        root.addStretch(1)
