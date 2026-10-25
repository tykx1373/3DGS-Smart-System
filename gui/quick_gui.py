# -*- coding: utf-8 -*-
"""
3DGS 快速管线 GUI（纯 PySide6，无第三方 UI 库）
管线逻辑在 pipeline_core.PipelineCore，界面外观在 qt_theme（QSS）。

运行：python quick_gui.py
页面：照片 / 训练设置 / 运行 / 历史模型 / 设置 / 日志
"""
import os
import sys
import logging
import subprocess
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QListWidget, QStackedWidget, QLabel, QPushButton,
    QLineEdit, QCheckBox, QRadioButton, QComboBox, QSpinBox, QMessageBox,
    QSystemTrayIcon, QMenu, QStyle,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from pipeline_core import (  # noqa: E402
    PROJECT_ROOT, DEFAULT_COLMAP, DEFAULT_VKGS, DEFAULT_VKSPLAT_PY,
    QUALITY_PRESETS, RES_AUTO,
    _cfg_int, _cfg_choice, load_config, save_config,
    resolve_path, relativize_path, PipelineCore,
)
from dataset_tools import (  # noqa: E402
    IMAGE_EXTS, CAPTURE_ASK_TIMEOUT,
    blur_scores, pick_blurry, photo_precheck_text, capture_report_text,
)
from dialogs import EvalDialog, SyscheckDialog  # noqa: E402
from pages.photo import PhotoPage  # noqa: E402
from pages.train_settings import TrainSettingsPage  # noqa: E402
from pages.run import RunPage  # noqa: E402
from pages.history import HistoryPage  # noqa: E402
from pages.settings import SettingsPage  # noqa: E402
from pages.log import LogPage  # noqa: E402
import syscheck  # noqa: E402
import qt_theme  # noqa: E402
from app_version import APP_VERSION  # noqa: E402
from qt_theme import (  # noqa: E402
    apply_theme, make_label, Toast, confirm,
)


# 内置示例数据集：安装包「示例数据集」组件会把它放到 <安装目录>/sample 下。
SAMPLE_SUBDIR = os.path.join("sample", "south-building", "images")
# 工作区名里带长边像素：示例图曾从 3072px 降到 1600px（为缩小安装包），
# 相机内参是按当时的分辨率算的，名字相同就会复用旧工作区导致位姿错位。
SAMPLE_DATASET_NAME = "south-building-1600"
# 少于这个张数 COLMAP 基本定位不出来，不配当新手的「第一次成功体验」。
SAMPLE_MIN_IMAGES = 20

# 任务栏/窗口图标候选路径（装机版把 app.ico 放到 gui/ 下，开发树在 installer/ 下）
ICON_CANDIDATES = (os.path.join("gui", "app.ico"),
                   os.path.join("installer", "app.ico"), "app.ico")

# faulthandler 的输出文件要一直开着，否则崩溃时文件已被回收
_CRASH_LOG = None


def _enable_crash_log():
    """把原生崩溃（0xc0000005 这类）的现场写进 logs/crash.log。

    Python 层的异常有 traceback，但访问冲突会直接把进程带走，控制台什么都不留。
    faulthandler 至少能把崩溃时各线程的 Python 栈落盘，下次看日志就知道卡在哪。
    """
    global _CRASH_LOG
    if _CRASH_LOG is not None:
        return
    try:
        import faulthandler
        logs_dir = os.path.join(PROJECT_ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        _CRASH_LOG = open(os.path.join(logs_dir, "crash.log"), "a",
                          encoding="utf-8", buffering=1)
        faulthandler.enable(file=_CRASH_LOG)
    except Exception:
        _CRASH_LOG = None


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
    stage = Signal(int)                  # 阶段序号（7 段管线）
    stage_plan = Signal(object)          # 本次实际要跑的阶段列表
    workspace = Signal(str)
    progress = Signal(float, str)        # frac(-1 表示只更新文字), detail
    running = Signal(bool, bool)         # 是否运行中, 不确定进度条
    eval_ready = Signal(object, object)  # 质量指标（可能为 None）, 训练参数/实测值
    failure = Signal(str, str)          # 原因, 建议
    capture = Signal(object)            # 采集质量报告（工作线程发，等 UI 回答）
    precheck = Signal(str, str, int)    # 结论, 级别, 序号（旧的序号直接丢弃）
    log = Signal(str, str)               # 文本, 级别(info/warn/fail/ok)
    diag_done = Signal(str, object)      # 目标路径, 异常或 None
    share_done = Signal(str, str)        # .splat 路径, 错误信息（空串表示成功）


# ==================================================================== 主窗口 ====
class MainWindow(QMainWindow, PipelineCore):
    NAV = ("照片", "训练设置", "运行", "历史模型", "设置", "日志")

    def __init__(self):
        PipelineCore.init_core(self)
        super().__init__()
        _enable_crash_log()
        self.setWindowTitle(f"3DGS 快速管线 v{APP_VERSION} - COLMAP + VkSplat(Vulkan) + VKGS")
        self.resize(1020, 700)

        self.cfg = load_config()
        self._init_vars()
        self.sig = _Signals()
        # 自检窗口只保留一个实例：连点按钮时复用它，不再叠出多个检测线程
        self._syscheck_dlg = None
        # 任务是否在运行：只有运行中才允许最小化/关闭到托盘
        self._task_running = False
        self._tray = None
        self._tray_menu = None
        # tqdm 刷屏治理：按「阶段名 -> 已写到的百分比桶」去重，
        # 每个阶段每 10% 只留一行（训练阶段由 PROGRESS 驱动，完全不记）
        self._tqdm_bucket = {}
        self._setup_logger()
        # 日志里留一行版本：用户发来的诊断包因此能判定是哪个构建
        # （同号多个构建的情况真实发生过）
        self._log(f"[INFO] 3DGS 快速管线 v{APP_VERSION}")

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
        bs = make_label(f"照片 → 3D 模型 · v{APP_VERSION}", "caption")
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

        self.photo_page = PhotoPage(self)
        self.train_settings_page = TrainSettingsPage(self)
        self.run_page = RunPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        self.log_page = LogPage(self)
        for p in (self.photo_page, self.train_settings_page, self.run_page,
                  self.history_page, self.settings_page, self.log_page):
            self.stack.addWidget(p)
        # 经门禁再切页：照片没选好时，不让训练设置/运行页被打开
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        h.addWidget(sidebar)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._load_cfg_to_widgets()
        self._connect_signals()
        self._wire_change_tracking()
        self._update_photo_gate()      # 启动时还没选照片，「下一步」保持不可点
        self._setup_tray()

        if syscheck.is_first_run():
            # 首次启动的自动自检：全部通过时自动收起，不挡住用户选照片
            QTimer.singleShot(400, lambda: self.open_syscheck(auto_close=True))

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
        self.img_edit.textChanged.connect(self._update_photo_gate)
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

    # ------------------------------------------------ 流程门禁 ----
    def _has_selected_photos(self):
        """照片文件夹里至少有一张能用的图，才算走完第 1 步。"""
        return self._count_images(resolve_path(self.img_edit.text().strip())) > 0

    def _update_photo_gate(self, _text=None):
        """没选到可用照片时「下一步」不可点，和侧栏门禁用同一个判断。"""
        self.next_btn.setEnabled(self._has_selected_photos())

    def _on_nav_changed(self, row):
        """按顺序走：照片没选好时，训练设置与运行页不许进。

        历史模型 / 设置 / 日志不拦——改工具路径、翻旧模型都不依赖这次的照片。
        """
        if row < 0:
            return
        if self.NAV[row] in ("训练设置", "运行") and not self._has_selected_photos():
            Toast.show_toast(self, "先选照片",
                             "先在第 1 步选好照片，再进入后面的步骤。",
                             "warning", 2600)
            # 鼠标点击的选中动作还在 Qt 内部处理中：此刻直接改 row/页面会被
            # 随后到来的选中覆盖（页面回去了、侧栏高亮却留在原处）。推迟一拍
            # 再一起改回来，并确认用户没有在期间点了别的页。
            QTimer.singleShot(0, lambda r=row: self._restore_photo_row(r))
            return
        self.stack.setCurrentIndex(row)

    def _restore_photo_row(self, blocked_row):
        if self.nav.currentRow() != blocked_row:
            return      # 用户已经点了别的页，别把他拽回来
        photo_row = self.NAV.index("照片")
        self.nav.setCurrentRow(photo_row)
        self.stack.setCurrentIndex(photo_row)
        self.nav.viewport().update()      # 高亮必须和页面一起重绘，不能只回去一半

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
        """核心在工作线程调用：文件日志 + 信号刷新界面，并解析进度。

        文件日志的写法与界面不同：界面给人看（带颜色、前缀），文件给排查用
        （级别要能过滤、正文不要带自相矛盾的前缀、tqdm 不能刷屏）。
        """
        from pipeline_core import _PROGRESS_RE, _TQDM_RE
        text = text.rstrip()
        marks = _PROGRESS_RE.findall(text)
        if marks:
            try:
                s, t, el, eta, n, vram_mb = marks[-1]
                step, total, num = int(s), int(t), int(n)
                elapsed, eta = float(el), float(eta)
                pct = step / total if total else 0.0
                overall = self.map_progress(pct)
                detail = f"训练 {pct*100:.0f}%"
                if self.progress.train_span != (0.0, 1.0):
                    # 与 COLMAP 同跑时前 30% 归重建，这里补一句整条管线走到哪
                    detail += f" · 总进度 {overall*100:.0f}%"
                detail += (f" · {step}/{total} 步 · 已用 {elapsed/60:.1f} 分钟")
                if eta > 0:
                    detail += f" · 剩余 {eta/60:.1f} 分钟"
                detail += f" · {num} 个高斯"
                if vram_mb:
                    # 分子是 vksplat 自己缓冲区的占用，不含驱动与其它程序；
                    # 分母只在能给出可信总量时才有（核显共享内存不给）
                    used_gb = int(vram_mb) / 1024
                    total_mb = getattr(self, "_vram_total_mb", None)
                    detail += (f" · 模型显存 {used_gb:.1f}/{total_mb/1024:.1f} GB" if total_mb
                               else f" · 模型显存 {used_gb:.1f} GB")
                self.sig.progress.emit(overall, detail)
                # 文件里只留结构化的一行：这行原文常带着被 \r 挤过来的 tqdm 尾巴
                # （"...it/s]PROGRESS: ..."），原样写进诊断包既长又难读。
                self.logger.info(f"{step}/{total} 步 · {num} 个高斯"
                                 + (f" · 模型显存 {int(vram_mb) / 1024:.1f} GB" if vram_mb else ""))
                # 约 30% 处记录一次累计平均 it/s，供下次耗时估算（每次运行仅一次）
                if not self._ips_recorded and pct >= 0.3 and elapsed > 5:
                    self._ips_recorded = True
                    try:
                        syscheck.record_measured_ips(self.quality_var.get(), step / elapsed)
                    except Exception:
                        pass
            except Exception:
                # 解析失败也要留痕，否则诊断包里会凭空少一行
                self.logger.info(text)
            return
        if "%|" in text:
            m = _TQDM_RE.search(text)
            if m:
                label = m.group("label").strip()
                # 训练器内部用的是英文阶段名，给用户看的部分换成中文；
                # 认不出来的（以后新增的阶段）保持原样，不丢信息。
                label = {"Running eval": "评估质量",
                         "Rendering val images": "渲染验证图",
                         "Rendering train images": "渲染训练图"}.get(label, label)
                try:
                    pct = int(m.group("pct"))
                except (TypeError, ValueError):
                    return
                # Training 由上面的 PROGRESS 驱动：它每 100 步已经写了结构化的
                # 一行，tqdm 再逐帧记一遍没有信息量，只会让日志膨胀几十倍。
                if label == "Training":
                    return
                # 其它阶段（评测等）每 10% 留一行。tqdm 在文件里由 \r 刷新，
                # 逐帧写会刷出几百行；诊断包 210 KB 里有三分之一是这种行。
                bucket = pct // 10
                if bucket > self._tqdm_bucket.get(label, -1):
                    self._tqdm_bucket[label] = bucket
                    d = f"{label}：{m.group('n')}/{m.group('total')}"
                    if m.group("elapsed"):
                        d += f" · 已用 {m.group('elapsed')}"
                    if m.group("eta") and m.group("eta") != "?":
                        d += f" · 剩余 {m.group('eta')}"
                    self.sig.progress.emit(-1.0, d)
                    self.logger.info(d)
                return
            self.logger.info(text)
            return
        # COLMAP 特征提取的逐图明细：每张 6 行（文件名/尺寸/相机模型/焦距/
        # 特征数），128 张就是 768 行，且内容几乎完全重复。界面只留每 10 张
        # 一个进度节点，明细仍写进文件（排查"某张图特征异常"时要用）。
        if any(p in text for p in ("  Name:", "  Dimensions:", "  Camera:",
                                   "  Focal Length:", "  Features:")):
            self.logger.info(text)
            return
        if "Processed file [" in text:
            self.logger.info(text)
            try:
                pair = text.split("Processed file [", 1)[1].split("]", 1)[0]
                n_now, n_total = (int(x) for x in pair.split("/"))
                if n_now % 10 == 0 or n_now == n_total:
                    self.sig.log.emit(text, "info")
            except Exception:
                pass
            return
        # COLMAP 的逐张配准行（128 张图就是 250+ 行）：进度条已经按
        # 「正在定位照片 64/128」逐张推进，界面上再逐张刷一遍只会把
        # 真正有用的信息顶出视野。文件里保留全文，排查配准问题时要看。
        if ("Registering image #" in text or "=> Image sees" in text
                or "Registering image with" in text):
            self.logger.info(text)
            return
        # 级别从正文前缀里取，写文件时把前缀剥掉：logger 行头已经有
        # [ERROR]/[WARNING]，正文再带一个 [FAIL] 就成了「[INFO] [FAIL]」
        # 这种自相矛盾的拼接（诊断包里出现过 21 行）。
        # 界面仍显示原文：前缀不只是颜色，也是色盲用户唯一的分级线索。
        raw = text
        level, log_level = "info", logging.INFO
        for prefix, lv, ll in (("[FAIL]", "fail", logging.ERROR),
                               ("[WARN]", "warn", logging.WARNING),
                               ("[OK]", "ok", logging.INFO),
                               ("[INFO]", "info", logging.INFO)):
            if text.startswith(prefix):
                level, log_level = lv, ll
                text = text[len(prefix):].lstrip()
                break
        self.logger.log(log_level, text)
        self.sig.log.emit(raw, level)

    # ------------------------------------------------ signals ----
    def _connect_signals(self):
        self.sig.status.connect(lambda t: self.status_lab.setText(t))
        self.sig.step.connect(self.run_page.set_step_color)
        self.sig.stage.connect(self.run_page.set_stage)
        self.sig.stage_plan.connect(self.run_page.set_stage_plan)
        self.sig.workspace.connect(self.ws_edit.setText)
        self.sig.progress.connect(self._on_progress)
        self.sig.running.connect(self._apply_running)
        self.sig.running.connect(self.run_page.set_run_active)
        self.sig.eval_ready.connect(self._show_eval)
        self.sig.failure.connect(self.run_page.set_failure)
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
        self._task_running = bool(running)
        self.ind_bar.setVisible(running and indeterminate)
        self.det_bar.setVisible(running and not indeterminate)
        if running:
            self.det_bar.setValue(0)
            self.run_page.fail_card.setVisible(False)   # 新一轮开始：收起上一次的报错
            self.run_page.set_context(self._run_context_text())
            # 上一轮的百分比桶作废，否则新一次的评测前 10% 会被当成「已经记过」
            self._tqdm_bucket.clear()
        # 运行中禁用参数（照片页 + 训练设置页 + 设置页），避免中途改设置。
        # 先统一处理，再单独设置运行页的按钮，避免被循环覆盖。
        for page in (self.photo_page, self.train_settings_page, self.settings_page,
                     self.run_page):
            exempt = getattr(page, "_runtime_exempt_widgets", ())
            for typ in (QLineEdit, QSpinBox, QComboBox, QRadioButton,
                        QCheckBox, QPushButton):
                for w in page.findChildren(typ):
                    if w in exempt:
                        continue
                    w.setEnabled(not running)
        self.run_btn.setEnabled(not running)
        self.rerun_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        # 任务是在托盘里跑完的：留一条气泡，窗口仍由用户自己决定何时打开
        if not running and self._tray is not None and self._tray.isVisible():
            self._tray.showMessage(
                "3DGS 快速管线", "任务已结束，点击托盘图标查看结果。",
                QSystemTrayIcon.MessageIcon.Information, 5000)

    # ------------------------------------------------ 系统托盘 ----
    def _setup_tray(self):
        """任务运行中最小化/关闭时收进托盘；空闲时保持系统默认行为。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        icon_path = find_app_icon()
        icon = (QIcon(icon_path) if icon_path
                else self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("3DGS 快速管线")
        menu = QMenu(self)
        menu.addAction("显示主窗口").triggered.connect(self._restore_from_tray)
        menu.addAction("退出程序").triggered.connect(self._quit_from_tray)
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_from_tray()

    def _hide_to_tray(self):
        if self._tray is None:
            self.showMinimized()
            return
        self.hide()
        self._tray.show()
        self._tray.showMessage(
            "3DGS 快速管线", "已收进托盘，任务继续在后台运行。",
            QSystemTrayIcon.MessageIcon.Information, 3000)

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if self._tray is not None:
            self._tray.hide()

    def _quit_from_tray(self):
        if self._task_running:
            # 直接退出会把训练进程带走，先把窗口叫回来让用户自己停
            self._restore_from_tray()
            Toast.show_toast(self, "任务还在进行",
                             "请先在运行页点「停止」，保存完成后再退出。",
                             "warning", 5000)
            return
        QApplication.instance().quit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QEvent.Type.WindowStateChange
                and self._task_running and self._tray is not None
                and self.isMinimized()):
            QTimer.singleShot(0, self._hide_to_tray)

    def closeEvent(self, event):
        if self._task_running and self._tray is not None:
            # 关窗口不等于停任务：先明确告知会收进托盘，别让用户以为训练被关掉了
            to_tray = confirm(
                self, "任务还在进行",
                "关闭窗口不会停止任务：程序会收进系统托盘，训练继续在后台运行。\n\n"
                "要彻底退出，请先在运行页点「停止」，等进度保存后再关闭。",
                "收进托盘", "取消")
            if to_tray:
                self._hide_to_tray()
            event.ignore()
            return
        event.accept()

    # ------------------------------------------------ PipelineCore 宿主 ----
    def set_status(self, text):
        self.sig.status.emit(text)

    def set_step(self, n):
        self.sig.step.emit(n)

    def set_stage(self, n):
        self.sig.stage.emit(int(n))

    def set_stage_plan(self, stages):
        self.sig.stage_plan.emit(list(stages))

    def _run_context_text(self):
        """运行页顶部那行「本次怎么跑」：照片数、档位、分辨率、步数、评估。"""
        n = self._count_selected_images()
        quality = self.quality_var.get()
        res = self.res_var.get()
        res_txt = f"自动（{quality}档）" if res == RES_AUTO else res
        steps = int(self.vs_steps_var.get())
        ev = "训练后评估开启" if self.run_eval_var.get() else "训练后评估关闭"
        txt = f"本次：{n} 张照片 · {quality}档 · 分辨率 {res_txt} · {steps} 步 · {ev}"
        if self.progress.reuse:
            txt += " · 复用上次定位"
        return txt

    def outputs_dir(self):
        """模型输出根目录。页面不直接依赖 PROJECT_ROOT，测试也能整体换根目录。"""
        return os.path.join(PROJECT_ROOT, "outputs")

    def set_workspace(self, path):
        self.sig.workspace.emit(path)

    def show_eval(self, mean, stats=None):
        self.sig.eval_ready.emit(mean, stats or {})

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

    def ask_reuse_colmap(self, n_imgs, ws_dir):
        """上次的空间定位还能用：让用户决定复用还是重算，不替用户做主。"""
        name = os.path.basename(ws_dir.rstrip("/\\"))
        return confirm(
            self, "可以复用上次的空间定位",
            f"工作区「{name}」里已有用这 {n_imgs} 张照片做好的空间定位，"
            f"照片和「最大图像尺寸」都没有变。\n\n"
            f"复用：跳过 COLMAP 的三步，直接开始训练，能省几分钟。\n"
            f"重新计算：从头再跑一遍 COLMAP。受随机采样与多线程计算影响，"
            f"结果通常很接近，但不保证与上次完全一致。",
            "复用（快）", "重新计算")

    def ask_retrain_existing(self, ws_dir, cfg):
        """相同照片 + 相同设置已经训过：给「重新训练 / 查看已有模型 / 取消」。"""
        settings = cfg.get("settings") or {}
        ply = cfg.get("ply") or ""
        name = os.path.splitext(os.path.basename(ply))[0] or os.path.basename(ply)
        when = str(cfg.get("finished_at") or "").replace("T", " ")
        detail = " · ".join(x for x in (
            f"{settings.get('steps')} 步" if settings.get("steps") else "",
            str(settings.get("quality") or ""),
            str(settings.get("res_choice") or ""),
        ) if x)
        box = QMessageBox(self)
        box.setWindowTitle("这组照片已经训练过了")
        box.setText(f"「{name}」就是用这组照片和相同设置训练出来的。{when}")
        box.setInformativeText(
            (f"训练设置：{detail}\n\n" if detail else "")
            + "要重新训练一遍，还是直接看已有模型？")
        box.addButton("重新训练", QMessageBox.AcceptRole)
        view = box.addButton("查看已有模型", QMessageBox.ActionRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(view)
        box.exec()
        clicked = box.clickedButton()
        if clicked is view:
            self.run_viewer(ply)
            return "view"
        if clicked is cancel or clicked is None:
            return "cancel"
        return "retrain"

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

    def open_syscheck(self, auto_close=False):
        """打开环境自检（单实例、非模态）。

        连点时只把已有窗口提到前面：每点一次就 new 一个对话框会在后台叠出
        多个自检线程，还可能出现「窗口已经关掉、检测线程还在往它发结果」。
        """
        dlg = self._syscheck_dlg
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        if dlg is None:
            self._syscheck_dlg = dlg = SyscheckDialog(self)
        dlg.auto_close = auto_close
        dlg.detect()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

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

    def _show_eval(self, mean, stats=None):
        dlg = EvalDialog(mean, on_view=self.open_viewer,
                         on_share=self.share_latest_splat, parent=self,
                         stats=stats or {})
        dlg.exec()

    # 三个开始入口（按钮绑定）
    def start_pipeline(self):
        self._sync_edits_to_vars()
        if not self._has_selected_photos():
            # 没照片就不该起步：回到第 1 步，别让运行页空转一圈再报错
            Toast.show_toast(self, "还没有照片",
                             "先在第 1 步选好照片，再开始生成。", "warning", 2600)
            self.nav.setCurrentRow(self.NAV.index("照片"))
            return
        # 开始后直接切到运行页：进度与排错都在那里，不用用户自己找
        self.nav.setCurrentRow(self.NAV.index("运行"))
        self.start(True, True)

    def start_colmap_only(self):
        self._sync_edits_to_vars()
        self.nav.setCurrentRow(self.NAV.index("运行"))
        # 这个入口的语义就是「重做空间定位」，所以强制重算、不询问复用
        self.start(True, False, force_colmap=True)

    def start_train_only(self):
        self._sync_edits_to_vars()
        self.nav.setCurrentRow(self.NAV.index("运行"))
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


def apply_app_identity(app, root=None):
    """设置窗口图标与 AppUserModelID。

    快捷方式的图标来自 EXE 的内嵌资源，但任务栏上的按钮只看**窗口图标**和
    **AppUserModelID**：两者都不设时，Windows 把窗口算到宿主 pythonw.exe 头上，
    显示成默认方框——装机后"有图标却不在任务栏显示"就是这么来的。
    """
    icon = find_app_icon(root)
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

