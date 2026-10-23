# -*- coding: utf-8 -*-
"""第 2 步：训练设置（质量档位、高级选项、图像与显存、输出位置）。"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QSpinBox, QCheckBox, QComboBox,
)

from pipeline_core import QUALITY_PRESETS, RES_AUTO, RES_DIR_MAP
from qt_theme import Card, PrimaryButton, make_label
from ui_helpers import _path_row, _row


class TrainSettingsPage(QWidget):
    """只管一件事：这次训练怎么跑。训练参数全部集中在这一页。"""

    def __init__(self, win):
        super().__init__()
        self.setObjectName("trainSettingsPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(make_label("2 · 训练设置", "title"))
        root.addWidget(make_label("只改这一页就能决定模型质量与耗时；不确定时保持默认即可。",
                                  "caption"))

        card = Card("质量档位")
        qrow = QWidget()
        ql = QHBoxLayout(qrow)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(QLabel("质量档位："))
        win.quality_group = QButtonGroup(self)
        for name in ("快速", "标准", "高质量"):
            rb = QRadioButton(name)
            rb.setToolTip(QUALITY_PRESETS[name][1])
            win.quality_group.addButton(rb)
            ql.addWidget(rb)
        ql.addStretch(1)
        card.body_layout.addWidget(qrow)
        win.quality_hint = make_label("", "caption")
        card.body_layout.addWidget(win.quality_hint)

        prow = QWidget()
        pl = QHBoxLayout(prow)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(QLabel("训练步数："))
        win.steps_spin = QSpinBox()
        win.steps_spin.setRange(100, 10_000_000)
        win.steps_spin.setToolTip("迭代次数，越多细节越好、越慢。档位切换会自动套用默认值。")
        pl.addWidget(win.steps_spin)
        pl.addSpacing(20)
        win.mcmc_chk = QCheckBox("MCMC 优化")
        win.mcmc_chk.setChecked(True)
        win.mcmc_chk.setToolTip("勾选：自动增删高斯点，多数场景质量更好；"
                                "照片很少/小场景训练失败时可取消。")
        pl.addWidget(win.mcmc_chk)
        pl.addStretch(1)
        card.body_layout.addWidget(prow)
        root.addWidget(card)

        # 高级选项：与日常参数分开，免得新手在选项堆里迷路
        card = Card("高级选项（一般不用动）")
        optrow = QWidget()
        ol = QHBoxLayout(optrow)
        ol.setContentsMargins(0, 0, 0, 0)
        win.eval_chk = QCheckBox("训练后质量评估（约 +1 分钟）")
        win.eval_chk.setChecked(True)
        win.eval_chk.setToolTip(
            "勾选：训完留出 16 张照片考试并打分（PSNR / SSIM / LPIPS）。\n"
            "实测 128 张、快速档下约 1 分 17 秒，比训练本身（约 40 秒）还久——\n"
            "其中一半时间花在加载 LPIPS 模型上。\n"
            "只想要模型、不在意分数就取消勾选，能明显更快看到结果；\n"
            "模型本身与勾选与否无关。")
        ol.addWidget(win.eval_chk)
        win.lpips_chk = QCheckBox("允许联网下载 LPIPS 权重（约 760 MB）")
        win.lpips_chk.setToolTip(
            "不勾：本机没有权重时只算 PSNR/SSIM，评估会快很多，也不会卡住。\n"
            "勾选：缺权重时联网下载（约 760 MB），之后每次评估都要加载这两个网络。")
        ol.addWidget(win.lpips_chk)
        ol.addStretch(1)
        card.body_layout.addWidget(optrow)

        optrow2 = QWidget()
        ol2 = QHBoxLayout(optrow2)
        ol2.setContentsMargins(0, 0, 0, 0)
        win.exposure_chk = QCheckBox("曝光校正（照片明暗不一时）")
        win.exposure_chk.setToolTip(
            "勾选：把所有照片的曝光统一匹配到中间值，\n"
            "减轻拍照时明暗不一致导致的重建色差/闪烁。\n"
            "曝光本来就一致的照片无需勾选；只处理训练副本，不动原图。")
        ol2.addWidget(win.exposure_chk)
        ol2.addStretch(1)
        card.body_layout.addWidget(optrow2)
        root.addWidget(card)

        card = Card("图像与显存")
        win.cache_combo = QComboBox()
        win.cache_combo.addItems(["cpu", "gpu"])
        win.cache_combo.setCurrentText("cpu")
        win.cache_combo.setToolTip("gpu 更快但占显存；核显或显存紧张选 cpu。")
        win.res_combo = QComboBox()
        win.res_combo.addItems([RES_AUTO] + list(RES_DIR_MAP))
        win.res_combo.setToolTip("训练图像尺寸；跟随档位＝快速 1/4、标准 1/2、高质量原图，\n"
                                 "并按显存自动降档（核显/不足 8GB 的独显最高 1/2，防显存溢出）。")
        card.body_layout.addWidget(_row("图片缓存：", win.cache_combo, label_width=110))
        card.body_layout.addWidget(_row("图像分辨率：", win.res_combo, label_width=110))
        win.maximg_spin = QSpinBox()
        win.maximg_spin.setRange(256, 20000)
        win.maximg_spin.setValue(1600)
        win.maximg_spin.setToolTip("COLMAP 特征提取时图片长边的上限（默认 1600）。")
        card.body_layout.addWidget(_row("最大图片尺寸：", win.maximg_spin, label_width=110))
        win.mask_edit = _path_row(
            self, card.body_layout, "Mask 文件夹:", win.mask_var, file=False,
            tip="遮罩图须与照片同名（IMG_001.jpg → IMG_001.jpg.png），"
                "黑色区域训练时忽略；留空不使用。")
        root.addWidget(card)

        card = Card("输出位置")
        win.ws_edit = _path_row(
            self, card.body_layout, "工作区文件夹:", win.ws_var, file=False,
            tip="留空时自动在 workspaces/ 下按照片文件夹名生成。")
        root.addWidget(card)

        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        win.run_btn = PrimaryButton("开始生成 3D 模型")
        win.run_btn.setFixedHeight(40)
        win.run_btn.setMinimumWidth(180)
        win.run_btn.clicked.connect(win.start_pipeline)
        bl.addWidget(win.run_btn)
        bl.addStretch(1)
        root.addWidget(brow)
        root.addStretch(1)
