# -*- coding: utf-8 -*-
"""
3DGS 快速管线 GUI（PySide6 + Fluent）
管线逻辑在 pipeline_core.PipelineCore，本文件只负责界面。

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

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QButtonGroup,
    QFileDialog, QDialog, QAbstractItemView, QSizePolicy,
)
from qfluentwidgets import (
    FluentWindow, FluentIcon as FIF, Theme, setTheme,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, CheckBox, RadioButton,
    ComboBox, SpinBox, ProgressBar, IndeterminateProgressBar,
    TableWidget, TextEdit, CardWidget, InfoBar, InfoBarPosition, MessageBox,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from pipeline_core import (  # noqa: E402
    PROJECT_ROOT, DEFAULT_COLMAP, DEFAULT_VKGS, DEFAULT_VKSPLAT_PY,
    QUALITY_PRESETS, RES_AUTO, RES_DIR_MAP, IMAGE_EXTS,
    _cfg_int, _cfg_choice, load_config, save_config,
    resolve_path, relativize_path,
    scan_history_models, delete_history_model, judge_eval_metrics,
    PipelineCore,
)
import syscheck  # noqa: E402


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
    log = Signal(str, str)               # 文本, 级别(info/warn/fail/ok)
    diag_done = Signal(str, object)      # 目标路径, 异常或 None


# ---------------------------------------------------------------- 小部件 ----
def _card(title=None):
    card = CardWidget()
    outer = QVBoxLayout(card)
    outer.setContentsMargins(16, 12, 16, 14)
    outer.setSpacing(8)
    if title:
        lab = SubtitleLabel(title)
        lab.font = QFont("Microsoft YaHei UI", 12, QFont.DemiBold)
        outer.addWidget(lab)
    return card, outer


def _row(label, *widgets, tip=None):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lab = BodyLabel(label)
    lab.setFixedWidth(110)
    lay.addWidget(lab)
    for x in widgets:
        lay.addWidget(x)
    lay.addStretch(1)
    if tip:
        target = widgets[0] if widgets else lab
        target.setToolTip(tip)
        lab.setToolTip(tip)
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

        root.addWidget(TitleLabel("3D 照片重建"))
        root.addWidget(CaptionLabel("把你拍的一组照片变成可旋转、可缩放的 3D 模型。"))

        # 步骤指示
        steps = QWidget()
        sl = QHBoxLayout(steps)
        sl.setContentsMargins(0, 4, 0, 0)
        self.step_labels = []
        for num, title, sub in (("①", "选择照片", "选一个装照片的文件夹"),
                                ("②", "生成 3D 模型", "电脑自动计算（几分钟~几十分钟）"),
                                ("③", "查看结果", "自动打开 3D 查看器")):
            c = QWidget()
            cl = QHBoxLayout(c)
            n = BodyLabel(f"  {num}  ")
            t = QWidget()
            tl = QVBoxLayout(t)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(0)
            t1 = BodyLabel(title)
            t2 = CaptionLabel(sub)
            tl.addWidget(t1)
            tl.addWidget(t2)
            cl.addWidget(n)
            cl.addWidget(t)
            sl.addWidget(c)
            self.step_labels.append((n, t1, t2))
        sl.addStretch(1)
        root.addWidget(steps)

        # 照片选择卡
        card, lay = _card("选择照片")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(BodyLabel("照片文件夹："))
        win.img_edit = LineEdit()
        win.img_edit.setPlaceholderText("点击右侧选择存放照片的文件夹")
        win.img_edit.setToolTip("支持 jpg/jpeg/png/bmp/tif/tiff；建议 30~200 张，每张重叠 60% 以上。")
        rl.addWidget(win.img_edit, 1)
        b = PushButton("浏览…")
        b.clicked.connect(win.browse_img)
        rl.addWidget(b)
        lay.addWidget(row)
        tip = CaptionLabel("拍照小技巧：绕物体一圈拍，每张重叠 60% 以上，建议 30~200 张。")
        lay.addWidget(tip)
        root.addWidget(card)

        # 参数卡
        card, lay = _card("质量与训练参数")
        qrow = QWidget()
        ql = QHBoxLayout(qrow)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(BodyLabel("质量档位："))
        win.quality_group = QButtonGroup(self)
        for name in ("快速", "标准", "高质量"):
            rb = RadioButton(name)
            rb.setToolTip(QUALITY_PRESETS[name][1])
            win.quality_group.addButton(rb)
            ql.addWidget(rb)
        ql.addStretch(1)
        lay.addWidget(qrow)
        win.quality_hint = CaptionLabel("")
        lay.addWidget(win.quality_hint)

        prow = QWidget()
        pl = QHBoxLayout(prow)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(BodyLabel("训练步数："))
        win.steps_spin = SpinBox()
        win.steps_spin.setRange(100, 10_000_000)
        win.steps_spin.setToolTip("迭代次数，越多细节越好、越慢。档位切换会自动套用默认值。")
        pl.addWidget(win.steps_spin)
        pl.addSpacing(20)
        win.mcmc_chk = CheckBox("MCMC 优化")
        win.mcmc_chk.setChecked(True)
        win.mcmc_chk.setToolTip("勾选：自动增删高斯点，多数场景质量更好；"
                                "照片很少/小场景训练失败时可取消。")
        pl.addWidget(win.mcmc_chk)
        pl.addStretch(1)
        lay.addWidget(prow)

        optrow = QWidget()
        ol = QHBoxLayout(optrow)
        ol.setContentsMargins(0, 0, 0, 0)
        win.eval_chk = CheckBox("训练后质量评估（PSNR/SSIM/LPIPS）")
        win.eval_chk.setChecked(True)
        win.eval_chk.setToolTip("训完留出几张照片考试并打分；CPU 版 PyTorch 约几十秒。")
        ol.addWidget(win.eval_chk)
        win.lpips_chk = CheckBox("允许联网下载 LPIPS 权重（约 760 MB）")
        win.lpips_chk.setToolTip("不勾：没有权重时只输出 PSNR/SSIM，不会卡住。")
        ol.addWidget(win.lpips_chk)
        ol.addStretch(1)
        lay.addWidget(optrow)
        root.addWidget(card)

        # 操作按钮
        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        win.run_btn = PrimaryPushButton("开始生成 3D 模型")
        win.run_btn.setFixedHeight(40)
        win.run_btn.setMinimumWidth(180)
        win.run_btn.clicked.connect(win.start_pipeline)
        bl.addWidget(win.run_btn)
        win.stop_btn = PushButton("停止")
        win.stop_btn.setFixedHeight(40)
        win.stop_btn.setEnabled(False)
        win.stop_btn.clicked.connect(win.stop_pipeline)
        bl.addWidget(win.stop_btn)
        win.view_btn = PushButton("查看 3D 模型")
        win.view_btn.setFixedHeight(40)
        win.view_btn.clicked.connect(win.open_viewer)
        bl.addWidget(win.view_btn)
        win.check_btn = PushButton("环境自检")
        win.check_btn.setFixedHeight(40)
        win.check_btn.clicked.connect(win.open_syscheck)
        bl.addWidget(win.check_btn)
        bl.addStretch(1)
        root.addWidget(brow)

        # 进度
        win.ind_bar = IndeterminateProgressBar()
        win.ind_bar.setVisible(False)
        root.addWidget(win.ind_bar)
        win.det_bar = ProgressBar()
        win.det_bar.setVisible(False)
        root.addWidget(win.det_bar)
        win.status_lab = CaptionLabel("就绪。请先选择照片文件夹。")
        root.addWidget(win.status_lab)
        root.addStretch(1)

    def set_step_color(self, n):
        pending, active, done = "#9e9e9e", "#3b82f6", "#22c55e"
        for i, labels in enumerate(self.step_labels):
            color = pending if i + 1 > n else (active if i + 1 == n else done)
            for w in labels:
                w.setStyleSheet(f"color: {color};")


# ============================================================== 历史模型页 ====
class HistoryPage(QWidget):
    COLS = ["时间", "模型", "档位", "步数", "PSNR", "SSIM", "LPIPS", "大小(MB)"]

    def __init__(self, win):
        super().__init__()
        self.setObjectName("historyPage")
        self.win = win
        self.items = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(TitleLabel("历史模型"))
        head.addStretch(1)
        refresh = PushButton("刷新")
        refresh.clicked.connect(self.reload)
        open_btn = PushButton("打开模型")
        open_btn.clicked.connect(self.open_selected)
        folder_btn = PushButton("打开目录")
        folder_btn.clicked.connect(self.open_folder)
        del_btn = PushButton("删除")
        del_btn.clicked.connect(self.delete_selected)
        for b in (refresh, open_btn, folder_btn, del_btn):
            b.setFixedHeight(34)
            head.addWidget(b)
        root.addLayout(head)
        root.addWidget(CaptionLabel("outputs/ 目录下所有训练成功的模型；双击行可用 VKGS 打开。"
                                    "指标来自该模型的 eval.json。"))

        self.table = TableWidget()
        self.table.setColumnCount(len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        self.table.horizontalHeader().setStretchLastSection(False)
        root.addWidget(self.table, 1)
        self.empty_lab = CaptionLabel("还没有训练成功的模型。")
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
            ]
            for c, v in enumerate(vals):
                from PySide6.QtWidgets import QTableWidgetItem
                self.table.setItem(r, c, QTableWidgetItem(v))
        for c, w in enumerate((150, 300, 70, 80, 80, 80, 80, 90)):
            self.table.setColumnWidth(c, w)
        self.empty_lab.setVisible(not self.items)

    def _selected_item(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.items[rows[0].row()]

    def open_selected(self):
        it = self._selected_item()
        if not it:
            InfoBar.warning("未选择", "请先在列表里选一个模型。", duration=2500,
                            position=InfoBarPosition.TOP, parent=self)
            return
        self.win.run_viewer(it["ply"])

    def open_folder(self):
        it = self._selected_item()
        if not it:
            return
        QDesktopServices.openUrl(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl.fromLocalFile(it["dir"]))

    def delete_selected(self):
        it = self._selected_item()
        if not it:
            return
        box = MessageBox("删除模型", f"确定删除「{it['name']}」吗？\n该操作不可恢复。", self)
        if box.exec():
            outputs = os.path.join(PROJECT_ROOT, "outputs")
            ok, err = delete_history_model(it["dir"], outputs)
            if ok:
                InfoBar.success("已删除", it["name"], duration=2500,
                                position=InfoBarPosition.TOP, parent=self)
                self.reload()
            else:
                InfoBar.error("删除失败", err or "未知错误", duration=3500,
                              position=InfoBarPosition.TOP, parent=self)


# ================================================================== 设置页 ====
class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("settingsPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(TitleLabel("设置"))

        # 工具路径
        card, lay = _card("工具路径")
        win.colmap_edit = self._path_row(lay, "COLMAP:", win.colmap_var, file=True,
                                         tip="COLMAP.bat 或 colmap.exe，留空则自动选择。")
        win.vkpy_edit = self._path_row(lay, "VkSplat Python:", win.vksplat_py_var, file=True,
                                       tip="运行训练的 Python，通常为 env/vksplat/python.exe。")
        win.vkgs_edit = self._path_row(lay, "VKGS 查看器:", win.vkgs_var, file=True,
                                       tip="vk_gaussian_splatting.exe，缺失不影响训练。")
        root.addWidget(card)

        # 工作区
        card, lay = _card("项目工作区")
        win.ws_edit = self._path_row(lay, "工作区文件夹:", win.ws_var, file=False,
                                     tip="留空时自动在 workspaces/ 下按照片文件夹名生成。")
        root.addWidget(card)

        # 训练参数
        card, lay = _card("VkSplat 训练参数")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._lab("图片缓存："))
        win.cache_combo = ComboBox()
        win.cache_combo.addItems(["cpu", "gpu"])
        win.cache_combo.setCurrentText("cpu")
        win.cache_combo.setToolTip("gpu 更快但占显存；核显或显存紧张选 cpu。")
        rl.addWidget(win.cache_combo)
        rl.addSpacing(16)
        rl.addWidget(self._lab("图像分辨率："))
        win.res_combo = ComboBox()
        win.res_combo.addItems([RES_AUTO] + list(RES_DIR_MAP))
        win.res_combo.setToolTip("训练图像尺寸；跟随档位＝快速 1/4、标准 1/2、高质量原图。")
        rl.addWidget(win.res_combo)
        rl.addStretch(1)
        lay.addWidget(row)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._lab("最大图片尺寸："))
        win.maximg_spin = SpinBox()
        win.maximg_spin.setRange(256, 20000)
        win.maximg_spin.setValue(1600)
        win.maximg_spin.setToolTip("COLMAP 特征提取时图片长边的上限（默认 1600）。")
        rl.addWidget(win.maximg_spin)
        rl.addStretch(1)
        lay.addWidget(row)

        win.mask_edit = self._path_row(lay, "Mask 文件夹:", win.mask_var, file=False,
                                       tip="遮罩图须与照片同名（IMG_001.jpg → IMG_001.jpg.png），"
                                           "黑色区域训练时忽略；留空不使用。")
        root.addWidget(card)

        # 分步操作
        card, lay = _card("分步操作")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        b1 = PushButton("只用 COLMAP（空间定位）")
        b1.setToolTip("只跑稀疏重建，不训练。")
        b1.clicked.connect(win.start_colmap_only)
        b2 = PushButton("只用训练（生成模型）")
        b2.setToolTip("复用已有 sparse/0，不重跑 COLMAP。")
        b2.clicked.connect(win.start_train_only)
        b3 = PushButton("保存设置")
        b3.clicked.connect(win.save_options)
        for b in (b1, b2, b3):
            rl.addWidget(b)
        rl.addStretch(1)
        lay.addWidget(row)
        root.addWidget(card)
        root.addStretch(1)

    @staticmethod
    def _lab(text):
        lab = BodyLabel(text)
        lab.setFixedWidth(110)
        return lab

    def _path_row(self, lay, label, var, file=True, tip=None):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._lab(label))
        edit = LineEdit()
        edit.setText(var.get())
        if tip:
            edit.setToolTip(tip)
        btn = PushButton("浏览")

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
        head.addWidget(TitleLabel("运行日志"))
        head.addStretch(1)
        diag = PushButton("导出诊断包")
        diag.setToolTip("把最近日志、自检结果和配置打包（路径已隐去），发给开发者排查问题。")
        diag.clicked.connect(win.export_diagnostics)
        head.addWidget(diag)
        clear = PushButton("清空")
        clear.clicked.connect(lambda: self.view.clear())
        head.addWidget(clear)
        lay.addLayout(head)
        self.view = TextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 10))
        lay.addWidget(self.view, 1)

    def append_line(self, text, level):
        color = self.COLORS.get(level, "#c8c8c8")
        import html
        self.view.append(f'<span style="color:{color}">{html.escape(text)}</span>')
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


# ============================================================== 评估结果弹窗 ====
class EvalDialog(QDialog):
    def __init__(self, mean, on_view, parent=None):
        super().__init__(parent)
        self.setWindowTitle("训练完成 · 质量评估")
        self.setMinimumWidth(430)
        verdict, level, rows = judge_eval_metrics(mean)
        color = {"good": "#22c55e", "mid": "#f59e0b",
                 "bad": "#ef4444", "none": "#888888"}[level]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(8)
        lay.addWidget(TitleLabel("训练完成"))
        v = BodyLabel(verdict)
        v.setStyleSheet(f"color: {color}; font-weight: 600;")
        v.setWordWrap(True)
        lay.addWidget(v)
        for name, value, hint in rows:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 2, 0, 2)
            a, b, c = BodyLabel(name), BodyLabel(value), CaptionLabel(hint)
            a.setFixedWidth(100)
            b.setFixedWidth(110)
            c.setWordWrap(True)
            rl.addWidget(a)
            rl.addWidget(b)
            rl.addWidget(c, 1)
            lay.addWidget(row)
        lay.addWidget(CaptionLabel("逐图明细见模型输出目录里的 eval.json"))
        btns = QHBoxLayout()
        view = PrimaryPushButton("查看 3D 模型")
        view.clicked.connect(lambda: (on_view(), self.accept()))
        close = PushButton("关闭")
        close.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(view)
        btns.addWidget(close)
        lay.addLayout(btns)


# ================================================================== 自检弹窗 ====
class _SyscheckSignals(QObject):
    done = Signal(object)


class SyscheckDialog(QDialog):
    """环境自检：逐项展示检查结果（对应 Tk 版的自检窗口）。"""

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
        lay.addWidget(TitleLabel("环境自检"))
        lay.addWidget(CaptionLabel("检查这台机器能不能跑（Vulkan 能力 / 依赖 / 工具 / 耗时预估）"))
        self.view = TextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 10))
        lay.addWidget(self.view, 1)
        self.conclusion = BodyLabel("正在检测…")
        self.conclusion.setWordWrap(True)
        lay.addWidget(self.conclusion)
        btns = QHBoxLayout()
        self.recheck = PushButton("重新检测")
        self.recheck.clicked.connect(self.detect)
        close = PushButton("关闭")
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
        colors = {"ok": "#22c55e", "warn": "#f59e0b", "fail": "#ef4444"}
        marks = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
        rows_html = []
        for r in s["results"]:
            c = colors.get(r.status, "#888")
            line = (f'<span style="color:{c};font-weight:600">[{marks.get(r.status, "?")}]</span> '
                    f'<b>{html.escape(r.name)}</b>: {html.escape(r.detail)}')
            rows_html.append(line)
            if r.hint:
                rows_html.append(f'<span style="color:#f59e0b">    → {html.escape(r.hint)}</span>')
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
            self.conclusion.setStyleSheet("color:#22c55e;")
            self.conclusion.setText(txt)
            if all(r.status == syscheck.OK for r in s["results"]):
                # 全部通过：1.8 秒后自动关闭，不打断首次运行
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1800, self.accept)
        else:
            blockers = s["blockers"] or ["无可用 Vulkan 设备"]
            self.conclusion.setStyleSheet("color:#ef4444;")
            self.conclusion.setText("结论：跑不动。原因：" + "、".join(blockers))
        self.recheck.setEnabled(True)


# ==================================================================== 主窗口 ====
class MainWindow(FluentWindow, PipelineCore):
    def __init__(self):
        PipelineCore.init_core(self)
        super().__init__()
        setTheme(Theme.AUTO)
        self.setWindowTitle("3DGS 快速管线 - COLMAP + VkSplat(Vulkan) + VKGS")
        self.resize(1020, 700)

        self.cfg = load_config()
        self._init_vars()
        self.sig = _Signals()
        self._setup_logger()

        self.train_page = TrainPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        self.log_page = LogPage(self)
        icon = lambda name: getattr(FIF, name, FIF.HOME)
        self.addSubInterface(self.train_page, icon("HOME"), "训练")
        self.addSubInterface(self.history_page, icon("HISTORY"), "历史模型")
        self.addSubInterface(self.settings_page, icon("SETTING"), "设置")
        self.addSubInterface(self.log_page, icon("DOCUMENT"), "日志")

        self._load_cfg_to_widgets()
        self._connect_signals()
        self._wire_change_tracking()

        if syscheck.is_first_run():
            from PySide6.QtCore import QTimer
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
        self.cache_combo.currentTextChanged.connect(lambda v: (self.vs_cache_var.set(v), self.save_options()))
        self.res_combo.currentTextChanged.connect(lambda v: (self.res_var.set(v), self.save_options()))
        for rb in self.quality_group.buttons():
            rb.toggled.connect(lambda _: self._on_quality_changed())

    def _on_quality_changed(self):
        name = self.quality_group.checkedButton().text()
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
                detail = (f"进度 {pct*100:.0f}% · {step}/{total} 步 · "
                          f"已用 {elapsed/60:.1f} 分钟")
                if eta > 0:
                    detail += f" · 剩余 {eta/60:.1f} 分钟"
                detail += f" · {num} 个高斯"
                self.sig.progress.emit(pct, detail)
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
        self.sig.log.connect(self.log_page.append_line)
        self.sig.diag_done.connect(self._diagnostics_done)

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
        # 运行中禁用参数（训练页 + 设置页），避免中途改设置。
        # 先统一处理，再单独设置开始/停止按钮，避免被循环覆盖。
        # PySide6 的 findChildren 一次只接受一个类型，需逐个调用。
        disabled_types = (LineEdit, SpinBox, ComboBox, RadioButton, CheckBox, PushButton)
        for page in (self.train_page, self.settings_page):
            for typ in disabled_types:
                for w in page.findChildren(typ):
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

    def set_progress(self, frac, detail):
        self.sig.progress.emit(-1.0 if frac is None else float(frac), detail or "")

    def set_running(self, running, indeterminate=True):
        self.sig.running.emit(running, indeterminate)

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
            box = MessageBox("耗时预估", "\n".join(lines), self)
            return box.exec()
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
        box = MessageBox("检测到上次未完成的训练",
                          f"发现恢复点（step={step}）。\n\n是 → 从 step {step} 继续\n否 → 从头开始（删除恢复点）",
                          self)
        if not box.exec():
            for p in (ply_p, step_p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ------------------------------------------------ UI 动作 ----
    def browse_img(self):
        p = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if not p:
            return
        self.img_edit.setText(p)
        n = self._count_images(p)
        if n == 0:
            InfoBar.warning("没有图片", "该文件夹里没有支持的图片。", duration=3000,
                            position=InfoBarPosition.TOP, parent=self)
            return
        self.status_lab.setText(f"已选择 {n} 张照片。")
        self._fill_workspace_from_images(p, n)

    def _fill_workspace_from_images(self, p, n_imgs):
        """选好照片后预填工作区名；图片数与旧工作区不符时让用户选择，
        防止把新数据集的 COLMAP 结果覆盖到旧工作区。"""
        from PySide6.QtWidgets import QMessageBox
        name = os.path.basename(p.rstrip("/\\")) or "project"
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
                box.setInformativeText("是 → 仍使用当前工作区（重新跑 COLMAP 会覆盖旧数据）\n"
                                       "否 → 生成一个新的工作区名\n取消 → 返回")
                yes, no, cancel = (QMessageBox.StandardButton.Yes,
                                   QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.Cancel)
                box.setStandardButtons(yes | no | cancel)
                box.setDefaultButton(no)
                box.button(yes).setText("仍使用当前工作区")
                box.button(no).setText("生成新工作区")
                box.button(cancel).setText("取消")
                choice = box.exec()
                if choice == int(cancel) or choice == cancel:
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

    def open_syscheck(self):
        SyscheckDialog(self).exec()

    def export_diagnostics(self):
        """收集日志/自检/配置打成 zip（后台线程，避免卡住 UI）。"""
        import diagnostics
        dest = diagnostics.default_dest(PROJECT_ROOT)
        self.set_status("正在收集诊断信息...")
        self._log(f"[INFO] 正在导出诊断包: {dest}")

        def work():
            error = None
            try:
                diagnostics.build_zip(dest, PROJECT_ROOT, python_exe=sys.executable)
            except Exception as e:
                error = e
            self.sig.diag_done.emit(dest, error)

        threading.Thread(target=work, daemon=True).start()

    def _diagnostics_done(self, dest, error):
        if error is not None:
            self.set_status(f"导出诊断包失败: {error}")
            self._log(f"[FAIL] 导出诊断包失败: {error}")
            InfoBar.error("导出失败", str(error), duration=4000,
                          position=InfoBarPosition.TOP, parent=self)
            return
        self.set_status("诊断包已导出，把它发给开发者即可。")
        self._log(f"[OK] 诊断包已导出: {dest}")
        box = MessageBox("诊断包已导出",
                          f"已生成：\n{dest}\n\n"
                          f"内含最近日志、环境自检结果和配置（用户名路径已隐去）。\n\n"
                          f"要现在打开所在文件夹吗？", self)
        box.yesButton.setText("打开文件夹")
        box.cancelButton.setText("关闭")
        if box.exec():
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(dest)])
            except OSError as e:
                self._log(f"[WARN] 无法打开文件夹: {e}")

    def _show_eval(self, mean):
        dlg = EvalDialog(mean, on_view=self.open_viewer, parent=self)
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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("3DGS 快速管线")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
