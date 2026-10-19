# -*- coding: utf-8 -*-
"""
3DGS 快速管线 GUI（纯 PySide6，无第三方 UI 库）
管线逻辑在 pipeline_core.PipelineCore，界面外观在 qt_theme（QSS）。

运行：python quick_gui.py
页面：训练 / 历史模型 / 设置 / 日志
"""
import os
import sys
import logging
import subprocess
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QUrl
from PySide6.QtGui import QFont, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QButtonGroup,
    QFileDialog, QDialog, QAbstractItemView, QListWidget, QStackedWidget,
    QLabel, QPushButton, QLineEdit, QCheckBox, QRadioButton, QComboBox,
    QSpinBox, QProgressBar, QTableWidget, QTableWidgetItem, QTextEdit,
    QMessageBox,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from pipeline_core import (  # noqa: E402
    PROJECT_ROOT, DEFAULT_COLMAP, DEFAULT_VKGS, DEFAULT_VKSPLAT_PY,
    QUALITY_PRESETS, RES_AUTO, RES_DIR_MAP,
    _cfg_int, _cfg_choice, load_config, save_config,
    resolve_path, relativize_path,
    scan_history_models, delete_history_model, judge_eval_metrics,
    capture_report_text, CAPTURE_ASK_TIMEOUT,
    blur_scores, pick_blurry, photo_precheck_text, IMAGE_EXTS,
    PipelineCore,
)
import syscheck  # noqa: E402
import qt_theme  # noqa: E402
from qt_theme import (  # noqa: E402
    apply_theme, make_label, Card, PrimaryButton, Toast, confirm,
)


# 内置示例数据集：安装包「示例数据集」组件会把它放到 <安装目录>/sample 下。
SAMPLE_SUBDIR = os.path.join("sample", "south-building", "images")
SAMPLE_DATASET_NAME = "south-building"
# 少于这个张数 COLMAP 基本定位不出来，不配当新手的「第一次成功体验」。
SAMPLE_MIN_IMAGES = 20

# 任务栏/窗口图标候选路径（装机版把 app.ico 放到 gui/ 下，开发树在 installer/ 下）
ICON_CANDIDATES = (os.path.join("gui", "app.ico"),
                   os.path.join("installer", "app.ico"), "app.ico")


# --------------------------------------------------------------- Var 适配 ----
class Var:
    """Tk Var 风格的 get/set 适配对象，供 PipelineCore 无差别读取。"""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Signals(QObject):
    """工作线程 → UI 线程的信号（Qt 自动使用队列连接封送）。"""
    status = Signal(str)
    step = Signal(int)
    workspace = Signal(str)
    progress = Signal(float, str)        # frac(-1 表示只更新文字), detail
    running = Signal(bool, bool)         # 是否运行中, 不确定进度条
    eval_ready = Signal(object)
    failure = Signal(str, str)          # 原因, 建议
    capture = Signal(object)            # 采集质量报告（工作线程发，等 UI 回答）
    precheck = Signal(str, str, int)    # 结论, 级别, 序号（旧的序号直接丢弃）
    log = Signal(str, str)               # 文本, 级别(info/warn/fail/ok)
    diag_done = Signal(str, object)      # 目标路径, 异常或 None
    share_done = Signal(str, str)        # .splat 路径, 错误信息（空串表示成功）


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


# ================================================================== 训练页 ====
class TrainPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("trainPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(make_label("3D 照片重建", "title"))
        root.addWidget(make_label("把你拍的一组照片变成可旋转、可缩放的 3D 模型。", "caption"))

        # 步骤指示
        steps = QWidget()
        sl = QHBoxLayout(steps)
        sl.setContentsMargins(2, 6, 0, 2)
        self.step_labels = []
        for num, title, sub in (("1", "选择照片", "选一个装照片的文件夹"),
                                ("2", "生成 3D 模型", "电脑自动计算（几分钟~几十分钟）"),
                                ("3", "查看结果", "自动打开 3D 查看器")):
            c = QWidget()
            cl = QHBoxLayout(c)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(9)
            n = QLabel(num)
            n.setFixedSize(30, 30)
            n.setAlignment(Qt.AlignCenter)
            t = QWidget()
            tl = QVBoxLayout(t)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(1)
            t1, t2 = QLabel(title), make_label(sub, "caption")
            tl.addWidget(t1)
            tl.addWidget(t2)
            cl.addWidget(n)
            cl.addWidget(t)
            sl.addWidget(c)
            self.step_labels.append((n, t1, t2))
        sl.addStretch(1)
        root.addWidget(steps)
        self.set_step_color(0)

        # 照片选择卡
        card = Card("选择照片")
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

        # 参数卡
        card = Card("质量与训练参数")
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

        optrow = QWidget()
        ol = QHBoxLayout(optrow)
        ol.setContentsMargins(0, 0, 0, 0)
        win.eval_chk = QCheckBox("训练后质量评估（PSNR/SSIM/LPIPS）")
        win.eval_chk.setChecked(True)
        win.eval_chk.setToolTip("训完留出几张照片考试并打分；CPU 版 PyTorch 约几十秒。")
        ol.addWidget(win.eval_chk)
        win.lpips_chk = QCheckBox("允许联网下载 LPIPS 权重（约 760 MB）")
        win.lpips_chk.setToolTip("不勾：没有权重时只输出 PSNR/SSIM，不会卡住。")
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

        # 操作按钮
        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        win.run_btn = PrimaryButton("开始生成 3D 模型")
        win.run_btn.setFixedHeight(40)
        win.run_btn.setMinimumWidth(180)
        win.run_btn.clicked.connect(win.start_pipeline)
        bl.addWidget(win.run_btn)
        win.stop_btn = QPushButton("停止")
        win.stop_btn.setFixedHeight(40)
        win.stop_btn.setEnabled(False)
        win.stop_btn.clicked.connect(win.stop_pipeline)
        bl.addWidget(win.stop_btn)
        win.view_btn = QPushButton("查看 3D 模型")
        win.view_btn.setFixedHeight(40)
        win.view_btn.clicked.connect(win.open_viewer)
        bl.addWidget(win.view_btn)
        win.check_btn = QPushButton("环境自检")
        win.check_btn.setFixedHeight(40)
        win.check_btn.clicked.connect(win.open_syscheck)
        bl.addWidget(win.check_btn)
        bl.addStretch(1)
        root.addWidget(brow)

        # 进度
        win.ind_bar = QProgressBar()
        win.ind_bar.setRange(0, 0)  # 忙碌动画
        win.ind_bar.setVisible(False)
        root.addWidget(win.ind_bar)
        win.det_bar = QProgressBar()
        win.det_bar.setRange(0, 100)
        win.det_bar.setVisible(False)
        root.addWidget(win.det_bar)
        win.status_lab = make_label("就绪。请先选择照片文件夹。", "caption")
        root.addWidget(win.status_lab)

        # 出错时把「原因 / 怎么办」直接放到主面板：日志默认折叠，
        # 而新手出错时的第一反应从来不是翻日志。
        self.fail_card = Card("这一步没成功")
        self.fail_cause = QLabel("")
        self.fail_cause.setWordWrap(True)
        self.fail_cause.setStyleSheet(f"color:{qt_theme.RED}; font-weight:600;"
                                      "background:transparent;")
        self.fail_advice = QLabel("")
        self.fail_advice.setWordWrap(True)
        frow = QHBoxLayout()
        frow.setContentsMargins(0, 0, 0, 0)
        win.diag_btn = QPushButton("导出诊断包")
        win.diag_btn.setToolTip("把最近日志、环境自检和配置打成一个 zip，发给开发者即可。")
        win.diag_btn.clicked.connect(win.export_diagnostics)
        win.fail_log_btn = QPushButton("看日志")
        win.fail_log_btn.clicked.connect(win.show_log_page)
        frow.addWidget(win.diag_btn)
        frow.addWidget(win.fail_log_btn)
        frow.addStretch(1)
        self.fail_card.body_layout.addWidget(self.fail_cause)
        self.fail_card.body_layout.addWidget(self.fail_advice)
        self.fail_card.body_layout.addLayout(frow)
        self.fail_card.setVisible(False)
        root.addWidget(self.fail_card)

        # 卡片里的按钮是「出错后才出现」的求助入口，不能像参数控件那样在
        # 运行中被禁用（否则自动续训时用户点不到）；_apply_running 按此跳过。
        self._runtime_exempt_widgets = (win.diag_btn, win.fail_log_btn)
        root.addStretch(1)

    def set_failure(self, cause, advice):
        """出错卡片：一句「为什么」+ 一句「现在怎么办」，摆在主面板上。"""
        self.fail_cause.setText(cause)
        self.fail_advice.setText("怎么办：" + advice)
        self.fail_card.setVisible(True)

    def set_step_color(self, n):
        """圆形步骤徽章：未开始灰边 / 当前蓝底白字 / 完成绿底白勾。"""
        sub = qt_theme._PALETTES[qt_theme.current_scheme()]["subtext"]
        styles = {
            "pending": "border:2px solid #8a8a8a; border-radius:15px; color:#8a8a8a;",
            "active": f"background:{qt_theme.ACCENT}; border-radius:15px; color:#ffffff; font-weight:700;",
            "done": f"background:{qt_theme.GREEN_BRIGHT}; border-radius:15px; color:#ffffff;",
        }
        for i, (badge, t1, t2) in enumerate(self.step_labels):
            state = "pending" if i + 1 > n else ("active" if i + 1 == n else "done")
            badge.setStyleSheet(styles[state])
            badge.setFont(QFont("Segoe UI Symbol", 11, QFont.Bold))
            badge.setText("✓" if state == "done" else str(i + 1))
            text_color = {"pending": "#8a8a8a", "active": qt_theme.ACCENT,
                          "done": qt_theme.GREEN_BRIGHT}[state]
            t1.setStyleSheet(f"color:{text_color}; font-weight:600; background:transparent;")
            t2.setStyleSheet(f"color:{sub}; background:transparent;")


# ============================================================== 历史模型页 ====
class HistoryPage(QWidget):
    COLS = ["时间", "模型", "档位", "步数", "PSNR", "SSIM", "LPIPS", "大小(MB)", "分享版(MB)"]

    def __init__(self, win):
        super().__init__()
        self.setObjectName("historyPage")
        self.win = win
        self.items = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(make_label("历史模型", "title"))
        head.addStretch(1)
        refresh, open_btn, share_btn, folder_btn, del_btn = (
            QPushButton("刷新"), QPushButton("打开模型"), QPushButton("发给别人"),
            QPushButton("打开目录"), QPushButton("删除"))
        refresh.clicked.connect(self.reload)
        open_btn.clicked.connect(self.open_selected)
        share_btn.clicked.connect(self.share_selected)
        folder_btn.clicked.connect(self.open_folder)
        del_btn.clicked.connect(self.delete_selected)
        for b in (refresh, open_btn, share_btn, folder_btn, del_btn):
            b.setFixedHeight(34)
            head.addWidget(b)
        root.addLayout(head)
        root.addWidget(make_label(
            "outputs/ 目录下所有训练成功的模型；双击行可用 VKGS 打开，"
            "「发给别人」准备一个体积更小的 .splat 文件，可以直接把文件发出去。"
            "指标来自该模型的 eval.json。",
            "caption"))

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        root.addWidget(self.table, 1)
        self.empty_lab = make_label("还没有训练成功的模型。", "caption")
        self.empty_lab.setVisible(False)
        root.addWidget(self.empty_lab)

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        outputs = os.path.join(PROJECT_ROOT, "outputs")
        self.items = scan_history_models(outputs)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            m = it["metrics"] or {}
            vals = [
                datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d %H:%M"),
                it["name"],
                it["quality"] or "—",
                str(it["steps"]) if it["steps"] else "—",
                f"{m['psnr']:.2f}" if "psnr" in m else "—",
                f"{m['ssim']:.3f}" if "ssim" in m else "—",
                f"{m.get('lpips_vgg', 0):.3f}" if m.get("lpips_vgg") is not None else "—",
                f"{it['size_mb']:.1f}",
                self._splat_mb(it),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c >= 4:  # 指标与大小列右对齐
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 1:  # 模型名可能被截断，悬浮显示全名
                    item.setToolTip(it["name"])
                self.table.setItem(r, c, item)
        # 列宽：时间/档位/步数/指标/大小固定，模型名列吃剩余空间
        from PySide6.QtWidgets import QHeaderView
        header = self.table.horizontalHeader()
        fixed = {0: 146, 2: 72, 3: 74, 4: 86, 5: 80, 6: 92, 7: 92, 8: 96}
        for c, w in fixed.items():
            header.resizeSection(c, w)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in fixed:
            header.setSectionResizeMode(c, QHeaderView.Fixed)
        self.empty_lab.setVisible(not self.items)

    def _selected_item(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.items[rows[0].row()]

    def open_selected(self):
        it = self._selected_item()
        if not it:
            Toast.show_toast(self, "未选择", "请先在列表里选一个模型。", "warning", 2500)
            return
        self.win.run_viewer(it["ply"])

    @staticmethod
    def _splat_mb(it):
        """分享版大小；没有就显示「—」，点「发给别人」时会自动转一份。"""
        p = it.get("splat")
        if not p:
            return "—"
        try:
            return f"{os.path.getsize(p) / 2**20:.1f}"
        except OSError:
            return "—"

    def share_selected(self):
        it = self._selected_item()
        if not it:
            Toast.show_toast(self, "未选择", "请先在列表里选一个模型。", "warning", 2500)
            return
        # 老模型可能没转过：按目录名命名，免得 splat.ply 转成 "splat.splat"
        target = it.get("splat") or os.path.join(it["dir"], it["name"] + ".splat")
        self.win.share_splat(it["ply"], splat_path=target)

    def open_folder(self):
        it = self._selected_item()
        if not it:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(it["dir"]))

    def delete_selected(self):
        it = self._selected_item()
        if not it:
            return
        if not confirm(self, "删除模型",
                       f"确定删除「{it['name']}」吗？\n该操作不可恢复。",
                       "删除", "取消"):
            return
        outputs = os.path.join(PROJECT_ROOT, "outputs")
        ok, err = delete_history_model(it["dir"], outputs)
        if ok:
            Toast.show_toast(self, "已删除", it["name"], "success", 2500)
            self.reload()
        else:
            Toast.show_toast(self, "删除失败", err or "未知错误", "error", 3500)


# ================================================================== 设置页 ====
class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("settingsPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(make_label("设置", "title"))

        card = Card("工具路径")
        win.colmap_edit = self._path_row(card.body_layout, "COLMAP:", win.colmap_var,
                                         file=True, tip="COLMAP.bat 或 colmap.exe，留空则自动选择。")
        win.vkpy_edit = self._path_row(card.body_layout, "VkSplat Python:", win.vksplat_py_var,
                                       file=True, tip="运行训练的 Python，通常为 env/vksplat/python.exe。")
        win.vkgs_edit = self._path_row(card.body_layout, "VKGS 查看器:", win.vkgs_var,
                                       file=True, tip="vk_gaussian_splatting.exe，缺失不影响训练。")
        root.addWidget(card)

        card = Card("项目工作区")
        win.ws_edit = self._path_row(card.body_layout, "工作区文件夹:", win.ws_var, file=False,
                                     tip="留空时自动在 workspaces/ 下按照片文件夹名生成。")
        root.addWidget(card)

        card = Card("VkSplat 训练参数")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._lab("图片缓存："))
        win.cache_combo = QComboBox()
        win.cache_combo.addItems(["cpu", "gpu"])
        win.cache_combo.setCurrentText("cpu")
        win.cache_combo.setToolTip("gpu 更快但占显存；核显或显存紧张选 cpu。")
        rl.addWidget(win.cache_combo)
        rl.addSpacing(16)
        rl.addWidget(self._lab("图像分辨率："))
        win.res_combo = QComboBox()
        win.res_combo.addItems([RES_AUTO] + list(RES_DIR_MAP))
        win.res_combo.setToolTip("训练图像尺寸；跟随档位＝快速 1/4、标准 1/2、高质量原图，\n"
                                 "并按显存自动降档（核显/不足 8GB 的独显最高 1/2，防显存溢出）。")
        rl.addWidget(win.res_combo)
        rl.addStretch(1)
        card.body_layout.addWidget(row)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._lab("最大图片尺寸："))
        win.maximg_spin = QSpinBox()
        win.maximg_spin.setRange(256, 20000)
        win.maximg_spin.setValue(1600)
        win.maximg_spin.setToolTip("COLMAP 特征提取时图片长边的上限（默认 1600）。")
        rl.addWidget(win.maximg_spin)
        rl.addStretch(1)
        card.body_layout.addWidget(row)

        win.mask_edit = self._path_row(card.body_layout, "Mask 文件夹:", win.mask_var,
                                       file=False,
                                       tip="遮罩图须与照片同名（IMG_001.jpg → IMG_001.jpg.png），"
                                           "黑色区域训练时忽略；留空不使用。")
        root.addWidget(card)

        card = Card("分步操作")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        b1 = QPushButton("只用 COLMAP（空间定位）")
        b1.setToolTip("只跑稀疏重建，不训练。")
        b1.clicked.connect(win.start_colmap_only)
        b2 = QPushButton("只用训练（生成模型）")
        b2.setToolTip("复用已有 sparse/0，不重跑 COLMAP。")
        b2.clicked.connect(win.start_train_only)
        b3 = QPushButton("保存设置")
        b3.clicked.connect(win.save_options)
        for b in (b1, b2, b3):
            rl.addWidget(b)
        rl.addStretch(1)
        card.body_layout.addWidget(row)
        root.addWidget(card)
        root.addStretch(1)

    @staticmethod
    def _lab(text):
        lab = QLabel(text)
        lab.setFixedWidth(110)
        return lab

    def _path_row(self, lay, label, var, file=True, tip=None):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._lab(label))
        edit = QLineEdit()
        edit.setText(var.get())
        if tip:
            edit.setToolTip(tip)
        btn = QPushButton("浏览")

        def pick():
            if file:
                p, _ = QFileDialog.getOpenFileName(self, label)
            else:
                p = QFileDialog.getExistingDirectory(self, label)
            if p:
                edit.setText(relativize_path(p))

        btn.clicked.connect(pick)
        h.addWidget(edit, 1)
        h.addWidget(btn)
        lay.addWidget(w)
        return edit


# ==================================================================== 日志页 ====
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
        lay.addWidget(self.view, 1)

    def append_line(self, text, level):
        import html
        color = self.COLORS.get(level, "#c8c8c8")
        self.view.append(f'<span style="color:{color}">{html.escape(text)}</span>')
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


# ============================================================== 评估结果弹窗 ====
class EvalDialog(QDialog):
    def __init__(self, mean, on_view, on_share=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("训练完成 · 质量评估")
        self.setMinimumWidth(430)
        verdict, level, rows = judge_eval_metrics(mean)
        color = {"good": "#16a34a", "mid": "#d97706",
                 "bad": "#dc2626", "none": "#888888"}[level]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(8)
        lay.addWidget(make_label("训练完成", "title"))
        v = QLabel(verdict)
        v.setStyleSheet(f"color: {color}; font-weight: 600;")
        v.setWordWrap(True)
        lay.addWidget(v)
        for name, value, hint in rows:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 2, 0, 2)
            a, b, c = QLabel(name), QLabel(value), make_label(hint, "caption")
            a.setFixedWidth(100)
            b.setFixedWidth(110)
            c.setWordWrap(True)
            rl.addWidget(a)
            rl.addWidget(b)
            rl.addWidget(c, 1)
            lay.addWidget(row)
        lay.addWidget(make_label("逐图明细见模型输出目录里的 eval.json", "caption"))
        lay.addWidget(make_label(
            "在本机看选「查看 3D 模型」（最清晰）；要把模型发给别人，"
            "选「准备分享文件」。", "caption"))
        btns = QHBoxLayout()
        view = PrimaryButton("查看 3D 模型")
        view.clicked.connect(lambda: (on_view(), self.accept()))
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        btns.addStretch(1)
        if on_share is not None:
            share = QPushButton("准备分享文件")
            share.setToolTip(
                "在 PLY 旁边准备一个体积小得多的 .splat 文件，可以直接把文件发出去。\n"
                "对方用支持 .splat 的查看器打开（本软件就能直接打开它）。\n"
                "分享版是固定光照，颜色会比本机预览平淡一些。")
            share.clicked.connect(lambda: (on_share(), self.accept()))
            btns.addWidget(share)
        btns.addWidget(view)
        btns.addWidget(close)
        lay.addLayout(btns)


# ================================================================== 自检弹窗 ====
class _SyscheckSignals(QObject):
    done = Signal(object)


class SyscheckDialog(QDialog):
    """环境自检：逐项展示检查结果。"""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._sig = _SyscheckSignals()
        self._sig.done.connect(self._render)
        self.setWindowTitle("环境自检")
        self.setMinimumSize(680, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(8)
        lay.addWidget(make_label("环境自检", "title"))
        lay.addWidget(make_label(
            "检查这台机器能不能跑（Vulkan 能力 / 依赖 / 工具 / 耗时预估）", "caption"))
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 10))
        lay.addWidget(self.view, 1)
        self.conclusion = QLabel("正在检测…")
        self.conclusion.setWordWrap(True)
        lay.addWidget(self.conclusion)
        btns = QHBoxLayout()
        self.recheck = QPushButton("重新检测")
        self.recheck.clicked.connect(self.detect)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        btns.addWidget(self.recheck)
        btns.addStretch(1)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.detect()

    def detect(self):
        self.recheck.setEnabled(False)
        self.conclusion.setText("正在检测…")
        self.view.setPlainText("正在检测，请稍候…")

        def work():
            summary = syscheck.summarize(
                colmap_path=resolve_path(self.win.colmap_var.get().strip()),
                vkgs_exe=resolve_path(self.win.vkgs_var.get().strip()),
                quality=self.win.quality_var.get(),
                steps=int(self.win.vs_steps_var.get()))
            syscheck.record_check()
            self._sig.done.emit(summary)

        threading.Thread(target=work, daemon=True).start()

    def _render(self, s):
        import html
        colors = {"ok": "#16a34a", "warn": "#d97706", "fail": "#dc2626"}
        marks = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
        rows_html = []
        for r in s["results"]:
            c = colors.get(r.status, "#888")
            line = (f'<span style="color:{c};font-weight:600">[{marks.get(r.status, "?")}]</span> '
                    f'<b>{html.escape(r.name)}</b>: {html.escape(r.detail)}')
            rows_html.append(line)
            if r.hint:
                rows_html.append(f'<span style="color:#d97706">    → {html.escape(r.hint)}</span>')
        self.view.setHtml("<br>".join(rows_html))

        if s["can_run"]:
            dev = s["device"]
            kind = "核显" if s["is_integrated"] else "独显"
            txt = f"结论：你的机器可以跑。{dev['name']}（{kind}）"
            if s["laptop"]:
                txt += f"。笔记本：耗时估算已按 {syscheck.LAPTOP_PENALTY}x 保守放大"
            est = s["est_total_sec"]
            if est is not None:
                note = "基于上次实测速度" if s["measured"] else "首次估算，跑过一次后会用实测修正"
                txt += f"。预计耗时 {syscheck.format_duration(est)}（{note}）"
            self.conclusion.setStyleSheet("color:#16a34a;")
            self.conclusion.setText(txt)
            if all(r.status == syscheck.OK for r in s["results"]):
                # 全部通过：1.8 秒后自动关闭，不打断首次运行
                QTimer.singleShot(1800, self.accept)
        else:
            blockers = s["blockers"] or ["无可用 Vulkan 设备"]
            self.conclusion.setStyleSheet("color:#dc2626;")
            self.conclusion.setText("结论：跑不动。原因：" + "、".join(blockers))
        self.recheck.setEnabled(True)


# ==================================================================== 主窗口 ====
class MainWindow(QMainWindow, PipelineCore):
    NAV = ("训练", "历史模型", "设置", "日志")

    def __init__(self):
        PipelineCore.init_core(self)
        super().__init__()
        self.setWindowTitle("3DGS 快速管线 - COLMAP + VkSplat(Vulkan) + VKGS")
        self.resize(1020, 700)

        self.cfg = load_config()
        self._init_vars()
        self.sig = _Signals()
        self._setup_logger()

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # 侧栏：品牌区 + 导航
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(12, 18, 12, 12)
        sb.setSpacing(6)
        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(6, 0, 0, 0)
        bl.setSpacing(10)
        logo = QLabel("3D")
        logo.setObjectName("logo")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignCenter)
        bl.addWidget(logo)
        bt = QWidget()
        btl = QVBoxLayout(bt)
        btl.setContentsMargins(0, 0, 0, 0)
        btl.setSpacing(1)
        bn = QLabel("3DGS 快速管线")
        bn.setObjectName("brandName")
        bs = make_label("照片 → 3D 模型", "caption")
        bs.setObjectName("brandSub")
        btl.addWidget(bn)
        btl.addWidget(bs)
        bl.addWidget(bt, 1)
        sb.addWidget(brand)
        sb.addSpacing(10)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.addItems(self.NAV)
        self.nav.setCurrentRow(0)
        sb.addWidget(self.nav, 1)

        self.stack = QStackedWidget()

        self.train_page = TrainPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        self.log_page = LogPage(self)
        for p in (self.train_page, self.history_page, self.settings_page, self.log_page):
            self.stack.addWidget(p)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        h.addWidget(sidebar)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._load_cfg_to_widgets()
        self._connect_signals()
        self._wire_change_tracking()

        if syscheck.is_first_run():
            QTimer.singleShot(400, self.open_syscheck)

    # ------------------------------------------------ vars / config ----
    def _init_vars(self):
        self.img_var = Var("")
        self.ws_var = Var("")
        self.quality_var = Var(_cfg_choice(self.cfg, "quality", QUALITY_PRESETS, "标准"))
        self.res_var = Var(self.cfg.get("res_choice", RES_AUTO))
        self.max_img_var = Var(_cfg_int(self.cfg, "max_image_size", 1600, 256, 20000))
        self.vs_steps_var = Var(_cfg_int(self.cfg, "train_steps", 15000, 100, 10 ** 7))
        self.vs_cache_var = Var(self.cfg.get("image_cache", "cpu"))
        self.vs_mcmc_var = Var(bool(self.cfg.get("vs_mcmc", True)))
        self.run_eval_var = Var(bool(self.cfg.get("run_eval", True)))
        self.mask_var = Var(str(self.cfg.get("mask_dir", "") or ""))
        self.lpips_dl_var = Var(bool(self.cfg.get("lpips_download", False)))
        self.exposure_fix_var = Var(bool(self.cfg.get("exposure_fix", False)))
        self.colmap_var = Var(self.cfg.get("colmap_path", DEFAULT_COLMAP))
        self.vkgs_var = Var(self.cfg.get("vkgs_exe", DEFAULT_VKGS))
        self.vksplat_py_var = Var(self.cfg.get("vksplat_python", DEFAULT_VKSPLAT_PY))

    def _load_cfg_to_widgets(self):
        for rb in self.quality_group.buttons():
            if rb.text() == self.quality_var.get():
                rb.setChecked(True)
        self.steps_spin.setValue(int(self.vs_steps_var.get()))
        self.mcmc_chk.setChecked(bool(self.vs_mcmc_var.get()))
        self.eval_chk.setChecked(bool(self.run_eval_var.get()))
        self.lpips_chk.setChecked(bool(self.lpips_dl_var.get()))
        self.exposure_chk.setChecked(bool(self.exposure_fix_var.get()))
        self.cache_combo.setCurrentText(str(self.vs_cache_var.get()))
        idx = self.res_combo.findText(str(self.res_var.get()))
        self.res_combo.setCurrentIndex(max(0, idx))
        self.maximg_spin.setValue(int(self.max_img_var.get()))
        self.colmap_edit.setText(str(self.colmap_var.get()))
        self.vkpy_edit.setText(str(self.vksplat_py_var.get()))
        self.vkgs_edit.setText(str(self.vkgs_var.get()))
        self.mask_edit.setText(str(self.mask_var.get()))
        self._refresh_quality_hint()

    def _wire_change_tracking(self):
        self.img_edit.textChanged.connect(self.img_var.set)
        self.ws_edit.textChanged.connect(self.ws_var.set)
        self.colmap_edit.textChanged.connect(self.colmap_var.set)
        self.vkpy_edit.textChanged.connect(self.vksplat_py_var.set)
        self.vkgs_edit.textChanged.connect(self.vkgs_var.set)
        self.mask_edit.textChanged.connect(self.mask_var.set)
        self.steps_spin.valueChanged.connect(lambda v: (self.vs_steps_var.set(v), self.save_options()))
        self.maximg_spin.valueChanged.connect(lambda v: (self.max_img_var.set(v), self.save_options()))
        self.mcmc_chk.toggled.connect(lambda v: (self.vs_mcmc_var.set(v), self.save_options()))
        self.eval_chk.toggled.connect(lambda v: (self.run_eval_var.set(v), self.save_options()))
        self.lpips_chk.toggled.connect(lambda v: (self.lpips_dl_var.set(v), self.save_options()))
        self.exposure_chk.toggled.connect(
            lambda v: (self.exposure_fix_var.set(v), self.save_options()))
        self.cache_combo.currentTextChanged.connect(
            lambda v: (self.vs_cache_var.set(v), self.save_options()))
        self.res_combo.currentTextChanged.connect(
            lambda v: (self.res_var.set(v), self.save_options()))
        for rb in self.quality_group.buttons():
            rb.toggled.connect(lambda _checked, b=rb: self._on_quality_changed(b))

    def _on_quality_changed(self, rb):
        if not rb.isChecked():
            return
        name = rb.text()
        self.quality_var.set(name)
        steps, _hint = QUALITY_PRESETS.get(name, (15000, ""))
        self.steps_spin.setValue(steps)   # 触发保存
        self._refresh_quality_hint()
        self.save_options()

    def _refresh_quality_hint(self):
        name = self.quality_var.get()
        steps, hint = QUALITY_PRESETS.get(name, (15000, ""))
        self.quality_hint.setText(f"→ {hint}（训练步数 {steps}）")

    def save_options(self):
        self.cfg.update({
            "quality": self.quality_var.get(),
            "res_choice": self.res_var.get(),
            "lpips_download": bool(self.lpips_dl_var.get()),
            "exposure_fix": bool(self.exposure_fix_var.get()),
            "train_steps": int(self.vs_steps_var.get()),
            "max_image_size": int(self.max_img_var.get()),
            "vs_mcmc": bool(self.vs_mcmc_var.get()),
            "run_eval": bool(self.run_eval_var.get()),
            "mask_dir": self.mask_var.get().strip(),
            "image_cache": self.vs_cache_var.get(),
            "colmap_path": self.colmap_var.get(),
            "vkgs_exe": self.vkgs_var.get(),
            "vksplat_python": self.vksplat_py_var.get(),
        })
        save_config(self.cfg)

    # ------------------------------------------------ logging ----
    def _setup_logger(self):
        logs_dir = os.path.join(PROJECT_ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        logger = logging.getLogger("quick_gui")
        logger.setLevel(logging.DEBUG)
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
        logger.handlers.clear()
        fh = RotatingFileHandler(
            os.path.join(logs_dir, datetime.now().strftime("%Y%m%d") + ".log"),
            maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                                          datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
        self.logger = logger

    def _log(self, text):
        """核心在工作线程调用：文件日志 + 信号刷新界面，并解析进度。"""
        from pipeline_core import _PROGRESS_RE, _TQDM_RE
        marks = _PROGRESS_RE.findall(text)
        if marks:
            try:
                s, t, el, eta, n = marks[-1]
                step, total, num = int(s), int(t), int(n)
                elapsed, eta = float(el), float(eta)
                pct = step / total if total else 0.0
                overall = self.map_progress(pct)
                detail = f"训练 {pct*100:.0f}%"
                if self._train_span != (0.0, 1.0):
                    # 与 COLMAP 同跑时前 30% 归重建，这里补一句整条管线走到哪
                    detail += f" · 总进度 {overall*100:.0f}%"
                detail += (f" · {step}/{total} 步 · 已用 {elapsed/60:.1f} 分钟")
                if eta > 0:
                    detail += f" · 剩余 {eta/60:.1f} 分钟"
                detail += f" · {num} 个高斯"
                self.sig.progress.emit(overall, detail)
                # 约 30% 处记录一次累计平均 it/s，供下次耗时估算（每次运行仅一次）
                if not self._ips_recorded and pct >= 0.3 and elapsed > 5:
                    self._ips_recorded = True
                    try:
                        syscheck.record_measured_ips(self.quality_var.get(), step / elapsed)
                    except Exception:
                        pass
            except Exception:
                pass
            # 进度行进文件日志，界面不刷屏
            self.logger.info(text.strip())
            return
        if "%|" in text:
            m = _TQDM_RE.search(text)
            # Training 由上面的 PROGRESS 标记驱动，跳过以免文案互相覆盖
            if m and m.group("label").strip() != "Training":
                d = f"{m.group('label').strip()}：{m.group('n')}/{m.group('total')}"
                if m.group("elapsed"):
                    d += f" · 已用 {m.group('elapsed')}"
                if m.group("eta") and m.group("eta") != "?":
                    d += f" · 剩余 {m.group('eta')}"
                self.sig.progress.emit(-1.0, d)
            self.logger.info(text.strip())
            return
        level = "info"
        if text.startswith("[FAIL]"):
            level = "fail"
        elif text.startswith("[WARN]"):
            level = "warn"
        elif text.startswith("[OK]"):
            level = "ok"
        self.logger.info(text)
        self.sig.log.emit(text, level)

    # ------------------------------------------------ signals ----
    def _connect_signals(self):
        self.sig.status.connect(lambda t: self.status_lab.setText(t))
        self.sig.step.connect(self.train_page.set_step_color)
        self.sig.workspace.connect(self.ws_edit.setText)
        self.sig.progress.connect(self._on_progress)
        self.sig.running.connect(self._apply_running)
        self.sig.eval_ready.connect(self._show_eval)
        self.sig.failure.connect(self.train_page.set_failure)
        self.sig.capture.connect(self._on_capture_report)
        self.sig.precheck.connect(self._on_precheck)
        self.sig.log.connect(self.log_page.append_line)
        self.sig.diag_done.connect(self._diagnostics_done)
        self.sig.share_done.connect(self._on_share_done)

    def _on_progress(self, frac, detail):
        if frac >= 0:
            self.det_bar.setVisible(True)
            self.ind_bar.setVisible(False)
            self.det_bar.setValue(int(frac * 100))
        if detail:
            self.status_lab.setText(detail)

    def _apply_running(self, running, indeterminate):
        self.ind_bar.setVisible(running and indeterminate)
        self.det_bar.setVisible(running and not indeterminate)
        if running:
            self.det_bar.setValue(0)
            self.train_page.fail_card.setVisible(False)   # 新一轮开始：收起上一次的报错
        # 运行中禁用参数（训练页 + 设置页），避免中途改设置。
        # 先统一处理，再单独设置开始/停止按钮，避免被循环覆盖。
        for page in (self.train_page, self.settings_page):
            exempt = getattr(page, "_runtime_exempt_widgets", ())
            for typ in (QLineEdit, QSpinBox, QComboBox, QRadioButton,
                        QCheckBox, QPushButton):
                for w in page.findChildren(typ):
                    if w in exempt:
                        continue
                    w.setEnabled(not running)
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    # ------------------------------------------------ PipelineCore 宿主 ----
    def set_status(self, text):
        self.sig.status.emit(text)

    def set_step(self, n):
        self.sig.step.emit(n)

    def set_workspace(self, path):
        self.sig.workspace.emit(path)

    def show_eval(self, mean):
        self.sig.eval_ready.emit(mean)

    def show_failure(self, cause, advice):
        """核心在工作线程调用：把「原因 / 怎么办」送到训练页卡片。"""
        self.sig.failure.emit(cause, advice)

    def show_log_page(self):
        self.nav.setCurrentRow(self.NAV.index("日志"))

    def set_progress(self, frac, detail):
        self.sig.progress.emit(-1.0 if frac is None else float(frac), detail or "")

    def set_running(self, running, indeterminate=True):
        self.sig.running.emit(running, indeterminate)

    def ask_capture_report(self, report):
        """工作线程调用：让 UI 弹一次采集质量提示，并等用户回答。

        信号是队列连接，弹窗一定落在 UI 线程；这里只等结果。超过
        CAPTURE_ASK_TIMEOUT 秒没人回答就照常训练——提醒不该变成拦路。
        """
        ev = threading.Event()
        box = {"go": True}
        self._capture_wait = (ev, box)
        self.sig.capture.emit(report)
        ev.wait(CAPTURE_ASK_TIMEOUT)
        return bool(box["go"])

    def _on_capture_report(self, report):
        """UI 线程：显示报告，把用户的选择写回等待中的工作线程。"""
        wait = getattr(self, "_capture_wait", None)
        if not wait:
            return
        ev, box = wait
        try:
            box["go"] = confirm(
                self, "照片检查结果",
                capture_report_text(report) + "\n\n现在就去补拍，还是先训练看看效果？",
                "先训练看看", "去补拍")
        finally:
            ev.set()

    def ask_continue(self, do_colmap):
        try:
            quality = self.quality_var.get()
            steps = int(self.vs_steps_var.get())
            devices, _ = syscheck.enumerate_vulkan_devices()
            best = syscheck.pick_device(devices)
            laptop = syscheck.detect_laptop(devices)
            measured = (syscheck.load_cache().get("measured_ips") or {}).get(quality)
            est_train = syscheck.estimate_train_seconds(
                best, quality, steps, measured_ips=measured, laptop=laptop) if best else None
            if est_train is None:
                return True
            n = self._count_selected_images()
            est_colmap = syscheck.estimate_colmap_seconds(n, laptop=laptop) if do_colmap and n else None
            est = est_train + (est_colmap or 0)
            lines = [f"预计耗时：{syscheck.format_duration(est)}"]
            lines.append(f"  其中 COLMAP 约 {syscheck.format_duration(est_colmap)}，"
                         f"训练约 {syscheck.format_duration(est_train)}" if est_colmap
                         else f"  训练 {steps} 步（{quality}档）")
            lines.append("是否继续？")
            return confirm(self, "耗时预估", "\n".join(lines), "继续", "取消")
        except Exception:
            return True

    def ask_resume(self):
        ws = resolve_path(self.ws_var.get().strip() or "")
        if not ws or not os.path.isdir(ws):
            return
        step_p, ply_p = os.path.join(ws, "checkpoint.ply.step"), os.path.join(ws, "checkpoint.ply")
        if not (os.path.isfile(ply_p) and os.path.isfile(step_p)):
            return
        try:
            step = int(open(step_p, encoding="utf-8").read().strip())
        except Exception:
            return
        keep = confirm(self, "检测到上次未完成的训练",
                       f"发现恢复点（step={step}）。\n\n"
                       f"点「继续」从 step {step} 接着训；\n"
                       f"点「从头开始」则删除恢复点。",
                       "继续", "从头开始")
        if not keep:
            for p in (ply_p, step_p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ------------------------------------------------ UI 动作 ----
    # ------------------------------------------------ 示例数据（P8）----
    def sample_dir(self):
        """内置示例照片目录（安装时勾选「示例数据集」才会有）。"""
        return resolve_path(SAMPLE_SUBDIR)

    def sample_ready(self):
        n = self._count_images(self.sample_dir())
        return n >= SAMPLE_MIN_IMAGES

    def use_sample(self):
        """选中示例照片并直接开跑：让新手第一次就在确定能跑通的数据上。

        耗时确认仍走原有的 ask_continue，不会闷头开始一个几十分钟的任务。
        """
        d = self.sample_dir()
        n = self._count_images(d)
        if n < SAMPLE_MIN_IMAGES:
            Toast.show_toast(self, "示例照片不可用",
                             "安装时没有勾选「示例数据集」。重新运行安装程序并勾上它，"
                             "或者点「浏览…」选自己的照片。", "warning", 6000)
            self.sample_btn.setVisible(False)
            return
        self.img_edit.setText(d)
        self._fill_workspace_from_images(d, n, name=SAMPLE_DATASET_NAME)
        self.start_photo_precheck(d, n)
        self._from_sample = True
        self.start_pipeline()

    def browse_img(self):
        p = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if not p:
            return
        self.img_edit.setText(p)
        n = self._count_images(p)
        if n == 0:
            Toast.show_toast(self, "没有图片", "该文件夹里没有支持的图片。", "warning", 3000)
            return
        self._from_sample = False     # 用户换成自己的照片了，别再按「第一次」来说话
        self.status_lab.setText(f"已选择 {n} 张照片。")
        self._fill_workspace_from_images(p, n)
        self.start_photo_precheck(p, n)

    def start_photo_precheck(self, folder, n_imgs):
        """后台做一次本地照片检查（张数 + 清晰度），结论写在照片卡片下方。

        不等 COLMAP 才开口：新手最不该付出的代价是白等二十分钟才听说照片不行。
        """
        self._precheck_seq = getattr(self, "_precheck_seq", 0) + 1
        seq = self._precheck_seq
        self.photo_note.setText("正在检查照片…")
        self.photo_note.setVisible(True)

        def work():
            try:
                names = sorted(f for f in os.listdir(folder)
                               if f.lower().endswith(IMAGE_EXTS))
                blurry = pick_blurry(blur_scores(folder, names))
                text, level = photo_precheck_text(n_imgs, blurry)
            except Exception as e:
                self._log(f"[WARN] 照片预检失败（不影响使用）: {e}")
                text, level = "", "ok"
            self.sig.precheck.emit(text, level, seq)

        threading.Thread(target=work, daemon=True).start()

    def _on_precheck(self, text, level, seq):
        if seq != getattr(self, "_precheck_seq", 0):
            return        # 用户已经换了文件夹，旧结论作废
        self.photo_note.setText(text)
        self.photo_note.setVisible(bool(text))
        color = {"ok": qt_theme.GREEN_BRIGHT, "warn": "#d97706"}.get(level, "")
        self.photo_note.setStyleSheet(f"color:{color}; background:transparent;" if color else "")

    def _fill_workspace_from_images(self, p, n_imgs, name=None):
        """选好照片后预填工作区名；图片数与旧工作区不符时让用户选择，
        防止把新数据集的 COLMAP 结果覆盖到旧工作区。

        name 由示例入口传入：示例照片放在 .../south-building/images 下，
        照目录名取到的工作区会叫「images」，对新手毫无意义。
        """
        name = name or os.path.basename(p.rstrip("/\\")) or "project"
        ws_rel = os.path.join("workspaces", f"{name}_{n_imgs}imgs_gs")
        ws_abs = resolve_path(ws_rel)
        if os.path.isdir(ws_abs):
            ws_images = os.path.join(ws_abs, "images")
            ws_n = self._count_images(ws_images) if os.path.isdir(ws_images) else 0
            if ws_n and ws_n != n_imgs:
                box = QMessageBox(self)
                box.setWindowTitle("数据集与工作区不匹配")
                box.setText(f"该工作区之前是基于 {ws_n} 张图重建的，\n"
                            f"但你选的文件夹有 {n_imgs} 张图。")
                box.setInformativeText("「仍使用当前工作区」会重新跑 COLMAP 覆盖旧数据；\n"
                                       "「生成新工作区」另建一个目录。")
                yes, no, cancel = (QMessageBox.StandardButton.Yes,
                                   QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.Cancel)
                box.setStandardButtons(yes | no | cancel)
                box.setDefaultButton(no)
                box.button(yes).setText("仍使用当前工作区")
                box.button(no).setText("生成新工作区")
                box.button(cancel).setText("取消")
                choice = box.exec()
                if choice == cancel:
                    return
                if choice == no:
                    i = 2
                    while True:
                        ws_rel = os.path.join("workspaces",
                                              f"{name}_{n_imgs}imgs_{i}_gs")
                        if not os.path.isdir(resolve_path(ws_rel)):
                            break
                        i += 1
                    ws_abs = resolve_path(ws_rel)
        self.ws_edit.setText(relativize_path(ws_rel))
        self.set_step(2)
        if self._find_latest_ply(ws_abs):
            self.status_lab.setText("检测到已有 3D 模型，可直接点「查看 3D 模型」预览，或重新生成。")
        else:
            self.status_lab.setText("照片已选好。选个质量档位，然后点「开始生成 3D 模型」。")

    def run_viewer(self, ply):
        vkgs = resolve_path(self.vkgs_var.get().strip())
        if vkgs and os.path.exists(vkgs):
            try:
                subprocess.Popen([vkgs, ply])
                self._log("[OK] 查看器已启动。")
            except OSError as e:
                self._log(f"[FAIL] 无法启动查看器: {e}")
        else:
            self._log(f"[WARN] VKGS 查看器未配置。输出 PLY: {ply}")

    def open_viewer(self):
        ws = resolve_path(self.ws_var.get().strip())
        ply = self._find_latest_ply(ws) if ws else None
        if ply:
            self.run_viewer(ply)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "选择要查看的 .ply 模型",
                                                os.path.join(PROJECT_ROOT, "workspaces"),
                                                "PLY 模型 (*.ply)")
            if p:
                self.run_viewer(p)

    def share_splat(self, ply_path, splat_path=None):
        """准备 .splat 分享文件，完成后打开所在文件夹并选中它。

        转换放到后台线程：读上百 MB 的 PLY 会卡 UI 好几秒。
        """
        if not ply_path or not os.path.isfile(ply_path):
            Toast.show_toast(self, "还没有可分享的模型",
                             "先完成一次训练，再点这个按钮。", "warning", 3500)
            return
        target = splat_path or os.path.splitext(ply_path)[0] + ".splat"

        def work():
            try:
                # 不给 target 赋值：那会让它变成 work() 的局部变量，
                # 上面那行 isfile(target) 直接 UnboundLocalError。
                # _export_splat 就是写到 dest=target，无需再取返回值。
                if not os.path.isfile(target):
                    made = self._export_splat(ply_path, dest=target)
                    if not made or not os.path.isfile(made):
                        self.sig.share_done.emit("", "分享版生成失败，详见日志。")
                        return
                self.sig.share_done.emit(target, "")
            except Exception as e:
                self.sig.share_done.emit("", f"分享版生成失败: {e}")

        self.set_status("正在生成分享用的 .splat 文件...")
        threading.Thread(target=work, daemon=True).start()

    def _on_share_done(self, splat_path, error):
        if error:
            self.set_status(error)
            Toast.show_toast(self, "分享失败", error, "error", 4500)
            return
        try:
            mb = os.path.getsize(splat_path) / 2**20
        except OSError:
            mb = 0.0
        self.set_status("分享文件已就绪。")
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(splat_path)])
        except OSError as e:
            self._log(f"[WARN] 无法打开文件夹: {e}")
        confirm(self, "分享文件已准备好",
                f"已在文件夹里选中：\n{os.path.basename(splat_path)}（{mb:.1f} MB）\n\n"
                f"把这个文件发给对方即可，它比 .ply 小得多。\n"
                f"对方那边用支持 .splat 的查看器打开——本软件「查看 3D 模型」"
                f"里选这个文件也能直接打开。\n\n"
                f"注意：分享版是固定光照，颜色比本机预览平淡一些，\n"
                f"这是正常的；模型本体仍是旁边的 .ply。",
                "知道了", "关闭")

    def share_latest_splat(self):
        """分享最近一次训练结果；工作区里没有模型时让用户自己挑一个 PLY。"""
        ws = resolve_path(self.ws_var.get().strip())
        ply = self._find_latest_ply(ws) if ws else None
        if not ply:
            p, _ = QFileDialog.getOpenFileName(self, "选择要分享的 .ply 模型",
                                               os.path.join(PROJECT_ROOT, "outputs"),
                                               "PLY 模型 (*.ply)")
            ply = p or None
        if ply:
            self.share_splat(ply)

    def open_syscheck(self):
        SyscheckDialog(self).exec()

    def export_diagnostics(self):
        """收集日志/自检/配置打成 zip（后台线程，避免卡住 UI）。"""
        import diagnostics
        dest = diagnostics.default_dest(PROJECT_ROOT)
        self.set_status("正在收集诊断信息...")
        self._log(f"[INFO] 正在导出诊断包: {dest}")
        # GUI 可能由 pythonw（无控制台）启动，但 doctor.py 是被 PIPE 捕获的
        # 子进程；优先用同名 python.exe，避免个别环境下 pythonw 行为差异。
        doctor_py = sys.executable
        if doctor_py.lower().endswith("pythonw.exe"):
            cand = doctor_py[: -len("pythonw.exe")] + "python.exe"
            if os.path.exists(cand):
                doctor_py = cand

        def work():
            error = None
            try:
                diagnostics.build_zip(dest, PROJECT_ROOT, python_exe=doctor_py)
            except Exception as e:
                error = e
            self.sig.diag_done.emit(dest, error)

        threading.Thread(target=work, daemon=True).start()

    def _diagnostics_done(self, dest, error):
        if error is not None:
            self.set_status(f"导出诊断包失败: {error}")
            self._log(f"[FAIL] 导出诊断包失败: {error}")
            Toast.show_toast(self, "导出失败", str(error), "error", 4000)
            return
        self.set_status("诊断包已导出，把它发给开发者即可。")
        self._log(f"[OK] 诊断包已导出: {dest}")
        if confirm(self, "诊断包已导出",
                   f"已生成：\n{dest}\n\n"
                   f"内含最近日志、环境自检结果和配置（用户名路径已隐去）。\n\n"
                   f"要现在打开所在文件夹吗？",
                   "打开文件夹", "关闭"):
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(dest)])
            except OSError as e:
                self._log(f"[WARN] 无法打开文件夹: {e}")

    def _show_eval(self, mean):
        dlg = EvalDialog(mean, on_view=self.open_viewer,
                         on_share=self.share_latest_splat, parent=self)
        dlg.exec()

    # 三个开始入口（按钮绑定）
    def start_pipeline(self):
        self._sync_edits_to_vars()
        self.start(True, True)

    def start_colmap_only(self):
        self._sync_edits_to_vars()
        self.start(True, False)

    def start_train_only(self):
        self._sync_edits_to_vars()
        self.start(False, True)

    def _sync_edits_to_vars(self):
        # 部分输入只在焦点离开时才提交，开始前强制同步一次并保存
        self.img_var.set(self.img_edit.text())
        self.ws_var.set(self.ws_edit.text())
        self.colmap_var.set(self.colmap_edit.text())
        self.vksplat_py_var.set(self.vkpy_edit.text())
        self.vkgs_var.set(self.vkgs_edit.text())
        self.mask_var.set(self.mask_edit.text())
        self.save_options()


def find_app_icon(root=None):
    """找应用图标文件；开发树在 installer/，装机后随包放到 gui/ 下。"""
    root = root or PROJECT_ROOT
    for rel in ICON_CANDIDATES:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p
    return None


def apply_app_identity(app):
    """设置窗口图标与 AppUserModelID。

    快捷方式的图标来自 EXE 的内嵌资源，但任务栏上的按钮只看**窗口图标**和
    **AppUserModelID**：两者都不设时，Windows 把窗口算到宿主 pythonw.exe 头上，
    显示成默认方框——装机后"有图标却不在任务栏显示"就是这么来的。
    """
    icon = find_app_icon()
    if icon:
        app.setWindowIcon(QIcon(icon))
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("3DGS.Studio")
        except Exception:
            pass   # 拿不到就退回默认行为，不该因此启动失败


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("3DGS 快速管线")
    apply_app_identity(app)
    apply_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

