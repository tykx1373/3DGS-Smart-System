# -*- coding: utf-8 -*-
"""
3DGS 快速管线 GUI (CustomTkinter 版)
串联：COLMAP (CUDA/nocuda) 稀疏重建 -> VkSplat (Vulkan) 训练 -> VKGS 实时渲染

运行：python quick_gui.py
说明：本文件以 UTF-8 (无 BOM) 保存，首行声明编码，可直接含中文源码。
      所有传给外部程序 (COLMAP/VkSplat) 的命令行参数保持 ASCII。
"""
import os
import sys
import json
import queue
import re
import subprocess
import threading
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

# 外观设置
ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

# ---------------------------------------------------------------- config ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # 3DGS/gui

# 环境自检模块（gui/syscheck.py），GUI 向导与 doctor.py 共用同一份判定
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
# 管线核心（常量/纯函数/PipelineCore），Tk 与 Qt 两个界面共用一份
from pipeline_core import (  # noqa: E402
    PROJECT_ROOT, CONFIG_PATH,
    DEFAULT_COLMAP, DEFAULT_VKGS, DEFAULT_VKSPLAT_PY,
    TRAIN_MAX_RETRIES, TRAIN_RETRY_DELAY,
    RES_AUTO, RES_DIR_MAP, RES_DEFAULT_BY_QUALITY, IMAGE_EXTS, EXIF_MARKER,
    QUALITY_PRESETS,
    _PROGRESS_RE, _TQDM_RE,
    SEQUENTIAL_MATCHER_THRESHOLD, LOW_REGISTRATION_RATE,
    resolve_path, relativize_path, _cfg_int, _cfg_choice,
    load_config as _load_config, save_config as _save_config,
    load_eval_mean, judge_eval_metrics,
    scan_history_models, is_path_within, delete_history_model,
    pick_colmap_matcher, parse_registered_images,
    PipelineCore,
)
import syscheck  # noqa: E402
import diagnostics  # noqa: E402

TRAIN_BACKENDS = ["VkSplat"]

# 字体常量
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_STEP = ("Microsoft YaHei UI", 11, "bold")
FONT_STEP_SUB = ("Microsoft YaHei UI", 9)
FONT_HINT = ("Microsoft YaHei UI", 9)
FONT_BIG_BTN = ("Microsoft YaHei UI", 13, "bold")
FONT_STATUS = ("Microsoft YaHei UI", 10)
FONT_LOG = ("Consolas", 11)

# 高级选项窗口里所有“标签 + 控件”行统一的标签列宽，保证各分区纵向对齐
ADV_LABEL_W = 120

# 质量档位 -> (训练步数, 说明) 等常量在 pipeline_core 中维护。


# ------------------------------------------------------------ tooltips ----
# 各控件的悬浮说明。以控件文字为键；输入框/下拉框这类没有自身文字的控件，
# 用同一行里紧邻的标签文字补位（见 _install_tooltips）。
TIP_TEXTS = {
    # 原则：界面常驻提示只给一句话；这里给具体数字、影响范围和什么时候该动它。
    "照片文件夹：": "支持 jpg / jpeg / png / bmp / tif / tiff。文件夹里只放本次拍摄的照片，"
                  "不要混入截图或重复照片；照片数量建议 30~200 张。",
    "快速": "5000 步 · 1/4 分辨率 · 约 2~3 分钟 · 高斯点上限 20 万。"
            "画面会发糊，只适合先确认重建轮廓和拍摄是否成功。",
    "标准": "15000 步 · 1/2 分辨率 · 约 8~10 分钟 · 高斯点上限 40 万。"
            "质量与速度平衡，日常使用推荐这一档。",
    "高质量": "30000 步 · 原分辨率 · 约 20 分钟以上 · 高斯点上限 80 万。"
              "细节最好；核显或显存紧张时会明显变慢，甚至可能失败。",
    "质量档位：": "档位同时决定训练步数、高斯点上限和默认分辨率。"
                  "这三项之后都能在「高级选项」里单独覆盖，不被档位锁死。",
    "开始生成 3D 模型": "一键执行三步：① COLMAP 推算每张照片的拍摄位置（约 1~5 分钟）；"
                      "② VkSplat 训练模型（按档位约 3~20 分钟以上）；③ 自动打开 VKGS 查看器。"
                      "中途可随时「停止」，下次从存档继续。",
    "停止": "安全停止：在工作区写入 STOP 标记，训练会在当前步正常收尾并保存存档，"
            "不是强杀进程。再次开始时自动从存档继续，不会重头训练。",
    "查看 3D 模型": "用 VKGS 打开工作区里最新的 PLY 模型，可同时开多个窗口对比。"
                   "还没有生成模型时点击无效。",
    "环境自检": "检查 Python 版本、vksplat 模块、依赖包、Vulkan 设备与显存、TdrDelay、"
                "COLMAP、VKGS、磁盘空间，给出“能不能跑”和预计耗时；核显会额外提示显卡超时设置。",
    "运行日志": "打开/关闭独立日志窗口，显示本次运行的完整输出。"
               "同样的内容也会写入 logs/ 目录下当天的日志文件。",
    "导出诊断": "把最近日志、环境自检结果和配置打成一个 zip（自动隐去用户名等路径信息）。"
                "出问题时把这个 zip 发给开发者即可，不用手动复制日志。",
    "COLMAP:": "COLMAP 启动文件（COLMAP.bat 或 colmap.exe），含中文/空格的路径也可以。"
               "程序会自动识别并使用 CUDA 或 noCUDA 版本。",
    "VkSplat Python:": "运行 VkSplat 训练的 Python 解释器，默认是 env/vksplat/python.exe，"
                      "里面已装好 vksplat / torch / torchvision 等依赖。换成别的环境需自行装齐。",
    "VKGS 查看器:": "vk_gaussian_splatting.exe，训练结束后用来旋转、缩放查看模型。"
                   "这个文件缺失不影响训练，只影响最后一步查看。",
    "工作区文件夹:": "每个数据集对应一个工作区，里面放 images 软链、sparse 位姿、"
                   "database.db、checkpoint 存档和训练产物。留空时自动在 workspaces/ 下按照片文件夹名生成。",
    "训练步数:": "训练迭代次数：5000 步看轮廓，15000 步日常使用，30000 步精修细节。"
                 "注意：若工作区里已有更靠后的 checkpoint，把步数改小不会产生新的训练，"
                 "需要先删掉 checkpoint 文件。",
    "MCMC 优化": "高斯点的增删策略。勾选（默认）：用 MCMC 统计采样自动增删点，"
                 "点数增长快、多数场景质量更好；取消：改用传统规则致密化，"
                 "照片很少（约 30 张以下）或小场景训练失败时更稳。",
    "图片缓存:": "训练图像放在哪里。gpu：读取快但占显存；cpu：不占显存，"
                 "核显或显存不足时选它。",
    "图像分辨率:": "训练和评测使用的图像尺寸：原图 / 1/2 / 1/4，越小越快但越糊。"
                   "跟随质量档位＝快速 1/4、标准 1/2、高质量原图。"
                   "COLMAP 始终使用原图，定位精度不受影响。",
    "训练后质量评估（PSNR/SSIM/LPIPS）":
        "训完后留出几张模型没见过的照片“考试”并打分：PSNR 是像素误差（越高越好，"
        ">25 不错，<18 通常说明照片或训练有问题）；SSIM 衡量结构相似度；"
        "LPIPS 最贴近人眼观感。CPU 版 PyTorch 大约需要几十秒；取消勾选则跳过，"
        "模型文件照常生成。",
    "允许联网下载 LPIPS 权重（约 760 MB，国内可能很慢）":
        "LPIPS 需要约 760 MB 预训练权重。不勾：本地没有权重时自动跳过 LPIPS，"
        "只输出 PSNR / SSIM，不会卡住；勾上：先联网下载权重再计算 LPIPS。",
    "Mask 文件夹:": "放黑白遮罩图的文件夹。遮罩文件名按 COLMAP 约定与照片同名"
                   "（照片 IMG_001.jpg 对应遮罩 IMG_001.jpg.png）；涂黑的区域训练时忽略，"
                   "可排除行人、车辆、拍摄者影子等移动物体。留空表示不使用。",
    "最大图片尺寸:": "COLMAP 提取特征时，把照片长边限制在该值以内（默认 1600）。"
                   "越大定位越精确，但更慢、更吃内存；照片本身小于该值则不受影响。",
    "只用 COLMAP（空间定位）": "只跑特征提取、匹配和稀疏重建（生成 sparse/0），不训练。"
                              "适合先验证照片能不能正常定位、注册率够不够。",
    "只用训练（生成模型）": "复用已有的 sparse/0 只跑训练，不重跑 COLMAP。"
                          "调参数重新训练时用它，省去重复定位的时间。",
    "保存路径配置": "把上面的工具路径与工作区写入 quick_gui_config.json，下次启动自动读取。"
                   "其实多数选项已经自动保存，这个按钮用于手动确认立即生效。",
}


class _Tip:
    """悬浮说明：鼠标停在控件上 250ms 后在其右侧弹出小窗；移开、点击、
    或窗口被移动/缩放都会关闭。

    说明直接挂在控件本体（按钮/输入框/复选框/单选钮等 CTk 复合控件）。
    CTk 控件内部还有 label/canvas 等子部件，指针在它们之间移动时会收到
    detail=NotifyInferior(3) 的 Leave/Enter —— 这类事件不算离开控件，
    否则提示会在控件内部一边移动一边闪。另有窗口级 <Motion> 兜底。
    """

    def __init__(self, app, widget, text, delay=250):
        self.app = app
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._win = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def contains_pointer(self):
        """指针是否还在控件范围内。"""
        try:
            px, py = self.widget.winfo_pointerxy()
            x, y = self.widget.winfo_rootx(), self.widget.winfo_rooty()
            w = self.widget.winfo_width() or self.widget.winfo_reqwidth()
            h = self.widget.winfo_height() or self.widget.winfo_reqheight()
            return x <= px <= x + w and y <= py <= y + h
        except Exception:
            return False

    @staticmethod
    def _is_inferior(e):
        # NotifyInferior = 3：指针只是移动到该控件的子部件上，不算离开/重新进入
        return getattr(e, "detail", None) == 3

    def _schedule(self, e=None):
        if self._is_inferior(e):
            return
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except Exception:
            self._after = None

    def _show(self):
        if self._win is not None:
            return
        try:
            if not self.widget.winfo_exists():
                return
            win = tk.Toplevel(self.widget)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            frame = ctk.CTkFrame(win, corner_radius=6, border_width=1,
                                 fg_color=("#ffffe1", "#3c3c3c"))
            frame.pack()
            ctk.CTkLabel(frame, text=self.text, font=FONT_HINT, justify="left",
                         wraplength=340).pack(padx=9, pady=6)
            win.update_idletasks()
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            # 放在控件右侧（不挡鼠标）；右边放不下就改到左侧
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
            if x + w > sw - 8:
                x = self.widget.winfo_rootx() - w - 8
            x = max(8, min(x, sw - 8 - w))
            y = max(8, min(self.widget.winfo_rooty() - 4, sh - 8 - h))
            win.geometry(f"+{x}+{y}")
            self._win = win
            self.app._active_tip = self
        except Exception:
            self._win = None

    def _hide(self, e=None):
        if self._is_inferior(e):
            return  # 只是移到内部子部件上，提示保持显示
        self._cancel()
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None
        if getattr(self.app, "_active_tip", None) is self:
            self.app._active_tip = None

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None


class _GuiLogHandler(logging.Handler):
    """把 logging 记录转发到 GUI 的 queue（供 _poll_log 显示）。"""
    _LEVEL_PREFIX = {
        logging.INFO: "[INFO]",
        logging.WARNING: "[WARN]",
        logging.ERROR: "[FAIL]",
        logging.DEBUG: "[DBG]",
    }

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            if getattr(record, "file_only", False):
                return  # 进度类输出只进日志文件，界面用进度条体现
            if getattr(record, "is_ok", False):
                prefix = "[OK]"
            else:
                prefix = self._LEVEL_PREFIX.get(record.levelno, "[INFO]")
            self.log_queue.put(f"{prefix} {record.getMessage()}")
        except Exception:
            pass


def setup_logger(log_queue):
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, datetime.now().strftime("%Y%m%d") + ".log")

    logger = logging.getLogger("quick_gui")
    logger.setLevel(logging.DEBUG)
    for h in logger.handlers:      # 先关旧句柄，否则重复调用会泄漏文件句柄
        try:
            h.close()
        except Exception:
            pass
    logger.handlers.clear()

    fmt_file = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                                 datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024,
                             backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_file)
    logger.addHandler(fh)

    gh = _GuiLogHandler(log_queue)
    gh.setLevel(logging.DEBUG)
    logger.addHandler(gh)

    return logger


def load_config():
    # 走本模块 CONFIG_PATH，单测通过 monkeypatch q.CONFIG_PATH 打桩
    return _load_config(CONFIG_PATH)


def save_config(cfg):
    _save_config(cfg, CONFIG_PATH)


def _make_group(parent, title):
    """创建带标题的分组容器（替代 ttk.LabelFrame）。"""
    outer = ctk.CTkFrame(parent, corner_radius=8)
    ctk.CTkLabel(outer, text=title, font=FONT_STEP).pack(anchor="w", padx=12, pady=(8, 0))
    inner = ctk.CTkFrame(outer, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=12, pady=(4, 12))
    return outer, inner


# ------------------------------------------------------------------- app ----
class QuickSplatApp(PipelineCore):
    def __init__(self, root):
        self.init_core()
        self.root = root
        root.title("3DGS 快速管线 - COLMAP + VkSplat(Vulkan) + VKGS")
        # 内容实际只需约 520 高；780 会在底部留一大片空白
        root.geometry("960x580")

        self.cfg = load_config()
        self.log_queue = queue.Queue()
        self.logger = setup_logger(self.log_queue)
        self._build_ui()
        # 内容高度随 DPI / 字体缩放变化，按实际请求尺寸设最小窗口，
        # 避免窗口被拖小或高缩放下把底部工具栏裁掉。
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())
        self._poll_log()

        # 首次运行：自动弹出环境自检向导，先给结论再让用户开跑
        if syscheck.is_first_run():
            self.root.after(400, lambda: self.open_syscheck(first_run=True))

    # ------------------------------------------------------------ UI build ----
    def _build_ui(self):
        self.COLOR_PENDING = "#9e9e9e"
        self.COLOR_ACTIVE = "#3b82f6"
        self.COLOR_DONE = "#22c55e"

        # ---- 标题区 ----
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(header, text="3D 照片重建", font=FONT_TITLE).pack(anchor="w")
        ctk.CTkLabel(header, text="把你拍的一组照片变成可旋转、可缩放的 3D 模型。",
                     font=FONT_HINT, text_color="#888").pack(anchor="w", pady=(2, 0))

        # ---- 步骤指示器 ----
        stepbar = ctk.CTkFrame(self.root, fg_color="transparent")
        stepbar.pack(fill="x", padx=16, pady=(6, 2))
        self.step_labels = []
        step_infos = [
            ("①", "选择照片", "选一个装照片的文件夹"),
            ("②", "生成 3D 模型", "电脑自动计算（几分钟~几十分钟）"),
            ("③", "查看结果", "自动打开 3D 查看器"),
        ]
        for i, (num, title, sub) in enumerate(step_infos):
            cell = ctk.CTkFrame(stepbar, fg_color="transparent")
            cell.grid(row=0, column=i, padx=8, sticky="ew")
            stepbar.grid_columnconfigure(i, weight=1)
            num_lbl = ctk.CTkLabel(cell, text=f"  {num}  ", font=FONT_STEP,
                                   text_color=self.COLOR_PENDING)
            num_lbl.pack(side="left")
            txt = ctk.CTkFrame(cell, fg_color="transparent")
            txt.pack(side="left")
            ctk.CTkLabel(txt, text=title, font=FONT_STEP,
                         text_color=self.COLOR_PENDING).pack(anchor="w")
            ctk.CTkLabel(txt, text=sub, font=FONT_STEP_SUB,
                         text_color=self.COLOR_PENDING).pack(anchor="w")
            self.step_labels.append((num_lbl, txt))
        self._set_step(1)

        # ---- 主操作区 ----
        main_outer, main = _make_group(self.root, "操作面板")
        main_outer.pack(fill="x", padx=16, pady=6)

        # 照片选择
        r1 = ctk.CTkFrame(main, fg_color="transparent")
        r1.pack(fill="x", pady=4)
        ctk.CTkLabel(r1, text="照片文件夹：", width=100, anchor="w").pack(side="left")
        self.img_var = tk.StringVar()
        self._img_entry = ctk.CTkEntry(r1, textvariable=self.img_var)
        self._img_entry.pack(side="left", fill="x", expand=True, padx=6)
        self._img_browse_btn = ctk.CTkButton(r1, text="浏览…", width=80, command=self._browse_img)
        self._img_browse_btn.pack(side="left")
        ctk.CTkLabel(main, text="拍照小技巧：绕物体一圈拍，每张重叠 60% 以上，建议 30~200 张。",
                      font=FONT_HINT, text_color="#3b82f6").pack(anchor="w", pady=(0, 4))

        # 质量档位
        r2 = ctk.CTkFrame(main, fg_color="transparent")
        r2.pack(fill="x", pady=4)
        ctk.CTkLabel(r2, text="质量档位：", width=100, anchor="w").pack(side="left")
        self.quality_var = tk.StringVar(
            value=_cfg_choice(self.cfg, "quality", QUALITY_PRESETS, "标准"))
        self._quality_radios = []
        for text in ("快速", "标准", "高质量"):
            rb = ctk.CTkRadioButton(r2, text=text, value=text, variable=self.quality_var)
            rb.pack(side="left", padx=10)
            self._quality_radios.append(rb)
        self.quality_hint = ctk.CTkLabel(main, text="", font=FONT_HINT, text_color="#888")
        self.quality_hint.pack(anchor="w", pady=(0, 4))
        self._refresh_quality_hint()
        # 用 trace 而不是 radio 的 command：CTk 单选钮在构造阶段就会触发一次
        # command，那会把刚从配置恢复出来的训练步数覆盖成档位默认值。
        self.quality_var.trace_add("write", lambda *_: self._on_quality_changed())

        # 大按钮行
        btns = ctk.CTkFrame(main, fg_color="transparent")
        btns.pack(fill="x", pady=(8, 0))
        self.run_btn = ctk.CTkButton(btns, text="开始生成 3D 模型", font=FONT_BIG_BTN,
                                     height=40, command=self.start_pipeline)
        self.run_btn.pack(side="left", padx=(0, 10))
        self.stop_btn = ctk.CTkButton(btns, text="停止", width=90, height=40,
                                      command=self.stop_pipeline, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.view_btn = ctk.CTkButton(btns, text="查看 3D 模型", width=120, height=40,
                                      command=self._open_viewer)
        self.view_btn.pack(side="left", padx=4)
        self.doctor_btn = ctk.CTkButton(btns, text="环境自检", width=100, height=40,
                                        command=self.open_syscheck,
                                        fg_color="transparent", border_width=1,
                                        text_color=("#3b82f6", "#60a5fa"))
        self.doctor_btn.pack(side="left", padx=4)
        # 这里原本还有一行“可打开多个窗口对比…”的灰字，与「查看 3D 模型」的
        # 悬浮说明重复，挤在按钮行末尾会被裁掉，已删除（说明见“查看 3D 模型”的「?」）。

        # ---- 高级选项独立窗口（切换按钮统一放在底部工具栏）----
        self.adv_window = ctk.CTkToplevel(self.root)
        self.adv_window.title("高级选项")
        self.adv_window.geometry("860x700")
        self.adv_window.withdraw()
        self.adv_window.protocol("WM_DELETE_WINDOW", self._hide_advanced)
        # 可滚动：高 DPI 缩放 / 内容增高时不会被窗口底边裁掉
        self.advanced_frame = ctk.CTkScrollableFrame(self.adv_window, fg_color="transparent")
        self.advanced_frame.pack(fill="both", expand=True, padx=14, pady=14)
        self._build_advanced_panel()

        # ---- 进度区 ----
        prog = ctk.CTkFrame(self.root, fg_color="transparent")
        prog.pack(fill="x", padx=16, pady=(8, 2))
        self.status_var = tk.StringVar(value="就绪。请先选择照片文件夹。")
        ctk.CTkLabel(prog, textvariable=self.status_var, font=FONT_STATUS, anchor="w").pack(fill="x")
        self.progress = ctk.CTkProgressBar(prog)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(6, 0))
        # 进度条下方的数值显示
        self.progress_detail_var = tk.StringVar(value="")
        ctk.CTkLabel(prog, textvariable=self.progress_detail_var,
                     font=FONT_HINT, text_color="#888").pack(anchor="w")

        # ---- 底部工具栏：次要操作并成一行，不再各自独占一整行 ----
        footer = ctk.CTkFrame(self.root, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(4, 12))
        self.adv_toggle_var = tk.StringVar(value="高级选项")
        self.adv_btn = ctk.CTkButton(footer, textvariable=self.adv_toggle_var,
                                     command=self._toggle_advanced, height=32,
                                     fg_color="transparent", border_width=1,
                                     text_color=("#3b82f6", "#60a5fa"))
        self.adv_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.log_btn = ctk.CTkButton(footer, text="运行日志", command=self.toggle_log_window,
                                     height=32, fg_color="transparent", border_width=1,
                                     text_color=("#3b82f6", "#60a5fa"))
        self.log_btn.pack(side="left", fill="x", expand=True, padx=6)
        self.diag_btn = ctk.CTkButton(footer, text="导出诊断", command=self.export_diagnostics,
                                      height=32, fg_color="transparent", border_width=1,
                                      text_color=("#3b82f6", "#60a5fa"))
        self.diag_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._build_log_window()

        # 这里不能调 _apply_quality_preset()：它会把刚从配置恢复出来的训练步数
        # 覆盖成档位默认值。档位提示已由 _refresh_quality_hint() 填好。
        self._refresh_backend_opts()
        self._install_tooltips()

    # ------------------------------------------------------- tooltips ----
    def _add_tip(self, widget, text):
        if not text:
            return
        if not hasattr(self, "_tips"):
            self._tips, self._tipped, self._active_tip = [], set(), None
        if id(widget) in self._tipped:
            return
        self._tipped.add(id(widget))
        try:
            self._tips.append(_Tip(self, widget, text))
        except Exception:
            pass

    def _tip_motion(self, _e=None):
        """窗口级兜底：指针离开控件矩形就关掉提示（复合控件的 Leave 事件不可靠）。"""
        t = getattr(self, "_active_tip", None)
        if t is not None and not t.contains_pointer():
            t._hide()

    def _tip_window_changed(self, event):
        """窗口被移动/缩放时关掉提示，否则小窗会留在原地。"""
        if event.widget is not event.widget.winfo_toplevel():
            return            # 忽略子控件自身产生的 Configure
        t = getattr(self, "_active_tip", None)
        if t is not None:
            t._hide()

    def _watch_tips(self):
        for w in (self.root, self.adv_window, self.log_window):
            try:
                w.bind("<Motion>", self._tip_motion, add="+")
                w.bind("<Configure>", self._tip_window_changed, add="+")
            except Exception:
                pass

    def _install_tooltips(self):
        """把说明直接挂到控件本体：鼠标悬停按钮/输入框/复选框/单选钮即弹出。

        同一段说明可能同时匹配一行里的标签、输入框和浏览按钮，按
        “可点击控件 > 输入框 > 标签”的优先级只挂一次。
        输入框/下拉框没有自身文字，用同一行里紧邻的标签补位。
        """
        PRIO_CLICK, PRIO_ENTRY, PRIO_LABEL = 3, 2, 1
        CLICK_CLS = ("CTkCheckBox", "CTkRadioButton", "CTkButton")
        ENTRY_CLS = ("Entry", "TEntry", "CTkEntry", "CTkComboBox")

        chosen = {}  # tip 正文 -> (控件, 优先级)

        def consider(widget, text, prio):
            cur = chosen.get(text)
            if cur is None or prio > cur[1]:
                chosen[text] = (widget, prio)

        def walk(container, last_label):
            for child in container.winfo_children():
                txt = None
                try:
                    t = child.cget("text")
                    txt = t if isinstance(t, str) else None
                except Exception:
                    pass
                # 注意：CTk 控件的 winfo_class() 都返回 "Frame"，必须用类型名判断
                cls = type(child).__name__

                handled = False
                if txt and txt in TIP_TEXTS:
                    prio = PRIO_CLICK if cls in CLICK_CLS else PRIO_LABEL
                    consider(child, TIP_TEXTS[txt], prio)
                    handled = True
                elif cls in ENTRY_CLS and last_label in TIP_TEXTS:
                    consider(child, TIP_TEXTS[last_label], PRIO_ENTRY)
                    handled = True
                # 「浏览」按钮与同行输入框共用同一段说明，不再重复挂

                if txt and txt.rstrip().endswith((":", "：")):
                    last_label = txt
                if not handled:
                    walk(child, last_label)

        walk(self.root, None)
        for text, (widget, _prio) in chosen.items():
            self._add_tip(widget, text)
        # 高级选项按钮的文字不在 TIP_TEXTS（随展开状态变化），单独挂
        self._add_tip(self.adv_btn, "路径配置、训练参数、COLMAP 选项与分步操作。")
        self._watch_tips()

    def _build_log_window(self):
        """运行日志放在独立窗口，避免挤占主界面。"""
        self.log_window = ctk.CTkToplevel(self.root)
        self.log_window.title("运行日志")
        self.log_window.geometry("780x500")
        self.log_window.minsize(480, 300)
        self.log_window.withdraw()
        self.log_window.protocol("WM_DELETE_WINDOW", self._hide_log_window)

        self.log = ctk.CTkTextbox(self.log_window, state="disabled", font=FONT_LOG,
                                  corner_radius=6, wrap="none")
        self.log.pack(fill="both", expand=True, padx=12, pady=12)
        # 日志级别颜色标签
        self.log.tag_config("ok", foreground="#22c55e")
        self.log.tag_config("warn", foreground="#f59e0b")
        self.log.tag_config("fail", foreground="#ef4444")
        self.log.tag_config("dbg", foreground="#9ca3af")

    def _hide_log_window(self):
        self.log_window.withdraw()

    def toggle_log_window(self):
        if self.log_window.winfo_viewable():
            self.log_window.withdraw()
        else:
            self.log_window.deiconify()
            self.log_window.lift()

    # ------------------------------------------------------- 导出诊断 ----
    def export_diagnostics(self):
        """把日志、环境自检结果和配置打包成 zip，省得让对方手动贴日志。

        doctor 那一步会跑几秒（要问系统和显卡），放线程里做，免得界面卡住。
        """
        dest = diagnostics.default_dest(PROJECT_ROOT)
        self.diag_btn.configure(state="disabled")
        self._set_status("正在收集诊断信息...")
        self._log(f"[INFO] 正在导出诊断包: {dest}")

        def work():
            error = None
            try:
                diagnostics.build_zip(dest, PROJECT_ROOT, python_exe=sys.executable)
            except Exception as e:
                error = e
            if error is None:
                self._log(f"[OK] 诊断包已导出: {dest}")
            else:
                self._log(f"[FAIL] 导出诊断包失败: {error}")
            self.root.after(0, self._diagnostics_done, dest, error)

        threading.Thread(target=work, daemon=True).start()

    def _diagnostics_done(self, dest, error):
        self.diag_btn.configure(state="normal")
        if error is not None:
            self._set_status(f"导出诊断包失败: {error}")
            messagebox.showerror("导出失败", f"没能生成诊断包：\n{error}")
            return
        self._set_status("诊断包已导出，把它发给开发者即可。")
        if messagebox.askyesno("诊断包已导出",
                               f"已生成：\n{dest}\n\n"
                               f"内含最近日志、环境自检结果和配置（用户名路径已隐去）。\n\n"
                               f"要现在打开所在文件夹吗？"):
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(dest)])
            except Exception as e:
                self._log(f"[WARN] 无法打开文件夹: {e}")

    # ------------------------------------------------------ eval popup ----
    def _show_eval_popup(self, mean_obj):
        """训练结束后展示质量指标（须在主线程调用，经 root.after 调度）。"""
        old = getattr(self, "_eval_popup", None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
            self._eval_popup = None

        verdict, level, rows = judge_eval_metrics(mean_obj)
        color = {"good": "#22c55e", "mid": "#f59e0b",
                 "bad": "#ef4444", "none": "#888888"}[level]

        win = ctk.CTkToplevel(self.root)
        self._eval_popup = win
        win.title("训练完成 · 质量评估")
        win.transient(self.root)
        win.resizable(False, False)
        win.after(60, win.lift)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(16, 8))

        ctk.CTkLabel(body, text="训练完成", font=FONT_TITLE).pack(anchor="w")
        ctk.CTkLabel(body, text=verdict, font=FONT_STEP,
                     text_color=color, wraplength=380,
                     justify="left").pack(anchor="w", pady=(6, 10))

        for name, value, hint in rows:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=name, font=FONT_STEP, width=110,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=FONT_STEP, width=90,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=hint, font=FONT_HINT, text_color="#888",
                         anchor="w").pack(side="left")

        ctk.CTkLabel(body, text="逐图明细见模型输出目录里的 eval.json",
                     font=FONT_HINT, text_color="#888").pack(anchor="w", pady=(12, 0))

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(10, 16))
        ctk.CTkButton(btns, text="查看 3D 模型", width=130,
                      command=self._open_viewer).pack(side="left")
        ctk.CTkButton(btns, text="关闭", width=90, command=win.destroy,
                      fg_color="transparent", border_width=1,
                      text_color=("#3b82f6", "#60a5fa")).pack(side="left", padx=8)

    # --------------------------------------------------- advanced panel ----
    def _build_advanced_panel(self):
        af = self.advanced_frame

        self.colmap_var = tk.StringVar(value=self.cfg.get("colmap_path", DEFAULT_COLMAP))
        self.vkgs_var = tk.StringVar(value=self.cfg.get("vkgs_exe", DEFAULT_VKGS))
        self.vksplat_py_var = tk.StringVar(value=self.cfg.get("vksplat_python", DEFAULT_VKSPLAT_PY))

        def _browse_file(var, filetypes):
            p = filedialog.askopenfilename(filetypes=filetypes)
            if p:
                var.set(relativize_path(p))

        ctk.CTkLabel(af, text="工具路径", font=FONT_STEP).pack(anchor="w", pady=(2, 4))
        rows = [
            ("COLMAP:", self.colmap_var,
             [("COLMAP", "*.bat *.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")]),
            ("VkSplat Python:", self.vksplat_py_var,
             [("Python", "python.exe pythonw.exe"), ("所有文件", "*.*")]),
            ("VKGS 查看器:", self.vkgs_var,
             [("可执行文件", "*.exe"), ("所有文件", "*.*")]),
        ]
        for label, var, ft in rows:
            r = ctk.CTkFrame(af, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=label, width=ADV_LABEL_W, anchor="w").pack(side="left")
            ctk.CTkEntry(r, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
            ctk.CTkButton(r, text="浏览", width=70,
                          command=lambda v=var, f=ft: _browse_file(v, f)).pack(side="left")

        ctk.CTkLabel(af, text="项目工作区", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        rw = ctk.CTkFrame(af, fg_color="transparent")
        rw.pack(fill="x", pady=3)
        ctk.CTkLabel(rw, text="工作区文件夹:", width=ADV_LABEL_W, anchor="w").pack(side="left")
        self.ws_var = tk.StringVar()
        ctk.CTkEntry(rw, textvariable=self.ws_var).pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(rw, text="浏览", width=70, command=self._browse_ws).pack(side="left")
        ctk.CTkLabel(af, text="（留空则自动生成到 workspaces/ 目录）",
                     font=FONT_HINT, text_color="#888").pack(anchor="w")

        ctk.CTkLabel(af, text="VkSplat 训练参数", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        self.vs_frame = ctk.CTkFrame(af, fg_color="transparent")
        self.vs_frame.pack(fill="x", pady=3)
        # 分两行放：全部挤在一行会超出窗口宽度被裁掉
        # （整行需求宽度约 1100px，而高级选项窗口没这么宽）
        r1 = ctk.CTkFrame(self.vs_frame, fg_color="transparent")
        r1.pack(fill="x", pady=3)
        ctk.CTkLabel(r1, text="训练步数:", width=ADV_LABEL_W, anchor="w").pack(side="left")
        self.vs_steps_var = tk.IntVar(value=_cfg_int(self.cfg, "train_steps", 15000, 100, 10 ** 7))
        ctk.CTkEntry(r1, textvariable=self.vs_steps_var, width=100).pack(side="left", padx=4)
        self.vs_steps_var.trace_add("write", lambda *_: self._save_options())
        self.vs_mcmc_var = tk.BooleanVar(value=bool(self.cfg.get("vs_mcmc", True)))
        ctk.CTkCheckBox(r1, text="MCMC 优化",
                        variable=self.vs_mcmc_var).pack(side="left", padx=12)

        r2 = ctk.CTkFrame(self.vs_frame, fg_color="transparent")
        r2.pack(fill="x", pady=3)
        ctk.CTkLabel(r2, text="图片缓存:", width=ADV_LABEL_W, anchor="w").pack(side="left")
        self.vs_cache_var = tk.StringVar(value="cpu")
        ctk.CTkComboBox(r2, variable=self.vs_cache_var,
                        values=["cpu", "gpu"], width=80, state="readonly").pack(side="left", padx=4)
        ctk.CTkLabel(r2, text="图像分辨率:", width=ADV_LABEL_W, anchor="w").pack(side="left", padx=(12, 0))
        saved_res = self.cfg.get("res_choice", RES_AUTO)
        if saved_res not in list(RES_DIR_MAP) + [RES_AUTO]:
            saved_res = RES_AUTO
        self.res_var = tk.StringVar(value=saved_res)
        ctk.CTkComboBox(r2, variable=self.res_var,
                        values=[RES_AUTO] + list(RES_DIR_MAP),
                        width=140, state="readonly").pack(side="left", padx=4)

        r3 = ctk.CTkFrame(self.vs_frame, fg_color="transparent")
        r3.pack(fill="x", pady=3)
        self.run_eval_var = tk.BooleanVar(value=bool(self.cfg.get("run_eval", True)))
        ctk.CTkCheckBox(r3, text="训练后质量评估（PSNR/SSIM/LPIPS）",
                        variable=self.run_eval_var).pack(side="left")

        r4 = ctk.CTkFrame(self.vs_frame, fg_color="transparent")
        r4.pack(fill="x", pady=3)
        self.lpips_dl_var = tk.BooleanVar(value=bool(self.cfg.get("lpips_download", False)))
        ctk.CTkCheckBox(r4, text="允许联网下载 LPIPS 权重（约 760 MB，国内可能很慢）",
                        variable=self.lpips_dl_var).pack(side="left")

        # 这些项改了就写回配置（在设初值之后挂 trace，避免启动时白写一次）
        self.vs_mcmc_var.trace_add("write", lambda *_: self._save_options())
        self.run_eval_var.trace_add("write", lambda *_: self._save_options())
        self.res_var.trace_add("write", lambda *_: self._save_options())
        self.lpips_dl_var.trace_add("write", lambda *_: self._save_options())

        ctk.CTkLabel(af, text="Mask（可选）", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        rm = ctk.CTkFrame(af, fg_color="transparent")
        rm.pack(fill="x", pady=3)
        ctk.CTkLabel(rm, text="Mask 文件夹:", width=ADV_LABEL_W, anchor="w").pack(side="left")
        self.mask_var = tk.StringVar(value=str(self.cfg.get("mask_dir", "") or ""))
        ctk.CTkEntry(rm, textvariable=self.mask_var).pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(rm, text="浏览", width=70,
                      command=lambda: self._browse_dir(self.mask_var)).pack(side="left")
        ctk.CTkLabel(af, text="遮罩图须与照片同名（如 IMG_001.jpg.png），训练时忽略被遮区域；留空不使用",
                     font=FONT_HINT, text_color="#888").pack(anchor="w")
        self.mask_var.trace_add("write", lambda *_: self._save_options())

        ctk.CTkLabel(af, text="COLMAP 选项", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        rc = ctk.CTkFrame(af, fg_color="transparent")
        rc.pack(fill="x", pady=3)
        ctk.CTkLabel(rc, text="最大图片尺寸:", width=ADV_LABEL_W, anchor="w").pack(side="left")
        self.max_img_var = tk.IntVar(value=_cfg_int(self.cfg, "max_image_size", 1600, 256, 20000))
        ctk.CTkEntry(rc, textvariable=self.max_img_var, width=100).pack(side="left", padx=4)
        self.max_img_var.trace_add("write", lambda *_: self._save_options())

        ctk.CTkLabel(af, text="分步操作", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        sb = ctk.CTkFrame(af, fg_color="transparent")
        sb.pack(fill="x", pady=3)
        ctk.CTkButton(sb, text="只用 COLMAP（空间定位）",
                      command=self.start_colmap_only).pack(side="left", padx=4)
        ctk.CTkButton(sb, text="只用训练（生成模型）",
                      command=self.start_train_only).pack(side="left", padx=4)
        ctk.CTkButton(sb, text="保存路径配置",
                      command=self._save_paths).pack(side="left", padx=4)

    def _toggle_advanced(self):
        if self.adv_window.state() == "withdrawn":
            self.adv_window.deiconify()
            self.adv_window.lift()
            self.adv_window.focus_force()
        else:
            self.adv_window.withdraw()

    def _hide_advanced(self):
        self.adv_window.withdraw()

    # --------------------------------------------------- step / status ----
    def _set_step(self, n):
        colors = [self.COLOR_PENDING] * 3
        if n >= 1:
            colors[0] = self.COLOR_DONE if n > 1 else self.COLOR_ACTIVE
        if n >= 2:
            colors[1] = self.COLOR_DONE if n > 2 else self.COLOR_ACTIVE
        if n == 3:
            colors[2] = self.COLOR_ACTIVE
        for i, (num_lbl, txt) in enumerate(self.step_labels):
            fg = colors[i]
            num_lbl.configure(text_color=fg)
            for child in txt.winfo_children():
                try:
                    child.configure(text_color=fg)
                except Exception:
                    pass

    def _set_status(self, text):
        self.status_var.set(text)

    def _on_quality_changed(self):
        """用户切换质量档位：套用该档位默认步数，并记住这次选择。"""
        self._apply_quality_preset()
        self._save_options()

    def _apply_quality_preset(self):
        steps, _hint = QUALITY_PRESETS.get(self.quality_var.get(), (15000, ""))
        self.vs_steps_var.set(steps)
        self._refresh_quality_hint()

    def _refresh_quality_hint(self):
        steps, hint = QUALITY_PRESETS.get(self.quality_var.get(), (15000, ""))
        self.quality_hint.configure(text=f"→ {hint}（训练步数 {steps}）")

    def _set_params_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self._img_entry.configure(state=state)
        self._img_browse_btn.configure(state=state)
        for rb in self._quality_radios:
            rb.configure(state=state)

        def _walk(widget):
            for child in widget.winfo_children():
                try:
                    child.configure(state=state)
                except Exception:
                    pass
                _walk(child)
        _walk(self.advanced_frame)

    def _open_viewer(self):
        ws_dir = resolve_path(self.ws_var.get().strip())
        plys = []
        if ws_dir and os.path.isdir(ws_dir):
            plys = sorted(
                [os.path.join(ws_dir, f) for f in os.listdir(ws_dir) if f.lower().endswith(".ply")],
                key=os.path.getmtime, reverse=True
            )

        if not plys:
            choice = messagebox.askyesno(
                "查看 3D 模型",
                "当前工作区还没有生成的模型。\n\n是否选择一个已有的 .ply 文件来查看？",
            )
            if choice:
                ply = filedialog.askopenfilename(
                    title="选择 3D 模型文件 (.ply)",
                    filetypes=[("PLY 模型", "*.ply"), ("所有文件", "*.*")],
                )
                if ply:
                    self._run_viewer(ply)
            return

        self._viewer_pick = None
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("选择要查看的 3D 模型")
        dlg.geometry("520x380")
        dlg.transient(self.root)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text=f"工作区共有 {len(plys)} 个模型，默认选中最新的：",
                     font=FONT_STATUS).pack(anchor="w", padx=14, pady=(12, 6))
        list_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=14, pady=4)
        lb = tk.Listbox(list_frame, height=12, activestyle="dotbox",
                        font=("Microsoft YaHei UI", 10))
        sb = ctk.CTkScrollbar(list_frame, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        for p in plys:
            mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")
            size_mb = os.path.getsize(p) / 1024 / 1024
            lb.insert("end", f"{os.path.basename(p)}   ({size_mb:.0f} MB, {mtime})")
        lb.selection_set(0)
        lb.activate(0)

        def _pick():
            sel = lb.curselection()
            if sel:
                self._viewer_pick = plys[sel[0]]
            dlg.destroy()

        def _browse_other():
            dlg.destroy()
            ply = filedialog.askopenfilename(
                title="选择其他 3D 模型文件 (.ply)",
                filetypes=[("PLY 模型", "*.ply"), ("所有文件", "*.*")],
            )
            if ply:
                self._run_viewer(ply)

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=12)
        ctk.CTkButton(btns, text="打开选中的模型", command=_pick).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="选择其他文件…", command=_browse_other,
                      fg_color="transparent", border_width=1, text_color=("#111", "#ddd")).pack(side="left")
        ctk.CTkButton(btns, text="取消", command=dlg.destroy,
                      fg_color="transparent", border_width=1, text_color=("#111", "#ddd")).pack(side="right")

        dlg.bind("<Double-Button-1>", lambda e: _pick())
        self.root.wait_window(dlg)
        if self._viewer_pick:
            self._run_viewer(self._viewer_pick)

    # ---------------------------------------------------------- UI helpers ----
    def _refresh_backend_opts(self):
        self.vs_frame.pack(fill="x", pady=2)

    def _browse_img(self):
        p = filedialog.askdirectory()
        if p:
            n_imgs = self._count_images(p)
            if n_imgs == 0:
                # 否则会生成 "..._0imgs_gs" 这种没意义的工作区，后面还会跑到空数据上
                exts = "、".join(e.lstrip(".") for e in IMAGE_EXTS)
                messagebox.showwarning(
                    "这个文件夹里没有照片",
                    f"在\n{p}\n里没有找到支持的图片（{exts}）。\n\n请选择装着照片的文件夹。")
                return
            self.img_var.set(relativize_path(p))
            name = os.path.basename(p.rstrip("/\\"))
            ws_rel = os.path.join("workspaces", f"{name}_{n_imgs}imgs_gs")
            ws_abs = resolve_path(ws_rel)

            if os.path.isdir(ws_abs):
                ws_images = os.path.join(ws_abs, "images")
                ws_n = self._count_images(ws_images) if os.path.isdir(ws_images) else 0
                if ws_n > 0 and ws_n != n_imgs:
                    choice = messagebox.askyesnocancel(
                        "数据集与工作区不匹配",
                        f"该工作区之前是基于 {ws_n} 张图重建的，\n"
                        f"但你选的文件夹有 {n_imgs} 张图。\n\n"
                        f"• 是 → 仍使用当前工作区（会重新跑 COLMAP 覆盖旧数据）\n"
                        f"• 否 → 重新生成一个工作区名\n"
                        f"• 取消 → 返回",
                    )
                    if choice is None:
                        return
                    if not choice:
                        i = 2
                        while True:
                            ws_rel = os.path.join("workspaces", f"{name}_{n_imgs}imgs_{i}_gs")
                            if not os.path.isdir(resolve_path(ws_rel)):
                                break
                            i += 1
                        ws_abs = resolve_path(ws_rel)

            self.ws_var.set(ws_rel)
            self._set_step(2)
            existing_ply = self._find_latest_ply(ws_abs)
            if existing_ply:
                self._set_status("检测到已有 3D 模型，可直接点「查看 3D 模型」预览，或重新生成。")
            else:
                self._set_status("照片已选好。选个质量档位，然后点「开始生成 3D 模型」。")

    def _browse_ws(self):
        p = filedialog.askdirectory()
        if p:
            self.ws_var.set(relativize_path(p))

    def _browse_dir(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(relativize_path(p))

    def _save_paths(self):
        self.cfg["colmap_path"] = self.colmap_var.get()
        self.cfg["vkgs_exe"] = self.vkgs_var.get()
        self.cfg["vksplat_python"] = self.vksplat_py_var.get()
        self._save_options()
        save_config(self.cfg)
        self._log("[OK] 路径与选项已保存到配置文件。")

    def _save_options(self):
        """记住质量档位与高级选项：改了就写回配置，不必再点“保存路径配置”。
        输入框处于半成品状态（例如被清空）时 get() 会抛错，跳过这一次保存即可。"""
        self.cfg["quality"] = self.quality_var.get()
        self.cfg["res_choice"] = self.res_var.get()
        self.cfg["lpips_download"] = bool(self.lpips_dl_var.get())
        self.cfg["vs_mcmc"] = bool(self.vs_mcmc_var.get())
        self.cfg["run_eval"] = bool(self.run_eval_var.get())
        self.cfg["mask_dir"] = self.mask_var.get().strip()
        for key, var in (("train_steps", self.vs_steps_var),
                         ("max_image_size", self.max_img_var)):
            try:
                self.cfg[key] = int(var.get())
            except Exception:
                pass
        save_config(self.cfg)

    # --------------------------------------------------------------- log ----
    def _log(self, text):
        # 识别 PROGRESS 标记：PROGRESS: step/total elapsed_sec eta_sec num_splats
        # 标记可能被 tqdm 的输出挤到行中间，故在整行内查找（取最后一个）
        marks = _PROGRESS_RE.findall(text)
        if marks:
            try:
                step, total, elapsed, eta, num_splats = marks[-1]
                step, total = int(step), int(total)
                elapsed, eta, num_splats = float(elapsed), float(eta), int(num_splats)
                pct = step / total if total > 0 else 0
                self.root.after(0, self.progress.set, pct)
                if eta > 0:
                    self.root.after(0, self.progress_detail_var.set,
                        f"进度 {pct*100:.0f}%  ·  {step}/{total} 步  ·  "
                        f"已用 {elapsed/60:.1f} 分钟  ·  剩余 {eta/60:.1f} 分钟  ·  "
                        f"{num_splats} 个高斯")
                else:
                    self.root.after(0, self.progress_detail_var.set,
                        f"进度 {pct*100:.0f}%  ·  {step}/{total} 步  ·  "
                        f"已用 {elapsed/60:.1f} 分钟  ·  {num_splats} 个高斯")
                # 取约 30% 处的累计平均 it/s 记一次，供下次耗时估算（仅一次）
                if not self._ips_recorded and pct >= 0.3 and elapsed > 5:
                    self._ips_recorded = True
                    try:
                        syscheck.record_measured_ips(self.quality_var.get(), step / elapsed)
                    except Exception:
                        pass
            except Exception:
                pass
            # 进度行完整写入日志文件，界面只由进度条/详情体现
            self.logger.info(text.strip(), extra={"file_only": True})
            return
        # tqdm 刷新帧（形如 "Training:  3%|██  | 95/3000 [...]" 或
        # "Running eval: 44%|...| 7/16 [...]"）：完整写入日志文件，界面不用文字
        # 刷屏，改为更新进度详情——否则评测这类长阶段看起来像卡死。
        if "%|" in text:
            m = _TQDM_RE.search(text)
            # Training 阶段由上面的 PROGRESS 标记驱动（文案更全），跳过以免两种格式互相覆盖
            if m and m.group("label").strip() != "Training":
                label = m.group("label").strip()
                n, total = int(m.group("n")), int(m.group("total"))
                elapsed, eta = m.group("elapsed"), m.group("eta")
                detail = f"{label}：{n}/{total}"
                if elapsed:
                    detail += f" · 已用 {elapsed}"
                if eta and eta != "?":
                    detail += f" · 剩余 {eta}"
                try:
                    self.progress_detail_var.set(detail)
                except Exception:
                    pass
            self.logger.info(text.strip(), extra={"file_only": True})
            return
        t = text.strip()
        low = t.lower()
        for p in ("[fail]", "[error]", "[warn]", "[dbg]", "[debug]", "[info]", "[ok]"):
            if low.startswith(p):
                t = t[len(p):].strip()
                break
        if low.startswith("[fail]") or low.startswith("[error]"):
            self.logger.error(t)
        elif low.startswith("[warn]"):
            self.logger.warning(t)
        elif low.startswith("[dbg]") or low.startswith("[debug]"):
            self.logger.debug(t)
        elif low.startswith("[ok]"):
            self.logger.info(t, extra={"is_ok": True})
        else:
            self.logger.info(t)

    def _poll_log(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                low = line.lower()
                if low.startswith("[fail]") or low.startswith("[error]"):
                    tag = "fail"
                elif low.startswith("[warn]"):
                    tag = "warn"
                elif low.startswith("[ok]"):
                    tag = "ok"
                elif low.startswith("[dbg]"):
                    tag = "dbg"
                else:
                    tag = None
                if tag:
                    self.log.insert("end", line + "\n", tag)
                else:
                    self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    # ------------------------------------------------------- syscheck UI ----
    def open_syscheck(self, first_run=False):
        """环境自检向导：检测 Vulkan/依赖/工具，并给出"能不能跑 + 预计耗时"。"""
        win = ctk.CTkToplevel(self.root)
        win.title("环境自检")
        win.geometry("660x600")
        win.transient(self.root)
        win.after(50, win.lift)

        head = "首次运行自检" if first_run else "环境自检"
        ctk.CTkLabel(win, text=head, font=FONT_TITLE).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(win, text="检查这台机器能不能跑（Vulkan 能力 / 依赖 / 工具 / 耗时预估）",
                     font=FONT_HINT, text_color="#888").pack(anchor="w", padx=16)

        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=10)
        status = ctk.CTkLabel(win, text="正在检测…", font=FONT_STATUS,
                              anchor="w", justify="left", wraplength=600)
        status.pack(fill="x", padx=16)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(6, 14))

        def render(summary):
            for w in body.winfo_children():
                w.destroy()
            for r in summary["results"]:
                row = ctk.CTkFrame(body, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=f"[{syscheck.STATUS_MARK[r.status]}]",
                             text_color=syscheck.STATUS_COLOR[r.status], font=FONT_STEP,
                             width=54, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=r.name, font=FONT_STEP, width=106,
                             anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=r.detail, font=FONT_HINT, anchor="w",
                             wraplength=400, justify="left").pack(side="left", fill="x", expand=True)
                if r.hint:
                    ctk.CTkLabel(body, text=f"→ {r.hint}", font=FONT_HINT,
                                 text_color="#f59e0b", anchor="w", wraplength=560,
                                 justify="left").pack(fill="x", padx=(54, 0))
            clean = summary["can_run"] and all(r.status == syscheck.OK
                                               for r in summary["results"])
            if summary["can_run"]:
                dev = summary["device"]
                kind = "核显" if summary["is_integrated"] else "独显"
                txt = f"结论：你的机器可以跑。{dev['name']}（{kind}）"
                if summary["laptop"]:
                    txt += f"\n机型为笔记本：耗时估算已按 {syscheck.LAPTOP_PENALTY}x 保守放大。"
                est = summary["est_total_sec"]
                if est is not None:
                    note = "实测修正" if summary["measured"] else "首次估算"
                    txt += f"\n预计耗时（{note}）：{syscheck.format_duration(est)}"
                if clean:
                    txt += "\n全部检查通过，窗口将自动关闭。"
                status.configure(text=txt, text_color="#22c55e")
                if clean:
                    # 环境没问题：展示结论片刻后自动关闭，不打断用户
                    win.after(1800, lambda: win.winfo_exists() and win.destroy())
            else:
                blockers = summary["blockers"] or ["无可用 Vulkan 设备"]
                status.configure(text="结论：跑不动。原因：" + "、".join(blockers),
                                 text_color="#ef4444")

        def detect():
            status.configure(text="正在检测…", text_color="#888")

            def work():
                summary = syscheck.summarize(
                    colmap_path=resolve_path(self.colmap_var.get().strip()),
                    vkgs_exe=resolve_path(self.vkgs_var.get().strip()),
                    quality=self.quality_var.get(),
                    steps=self.vs_steps_var.get(),
                )
                syscheck.record_check()
                self.root.after(0, render, summary)

            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(btns, text="重新检测", width=110, command=detect).pack(side="left")
        ctk.CTkButton(btns, text="关闭", width=110, command=win.destroy,
                      fg_color="transparent", border_width=1,
                      text_color=("#3b82f6", "#60a5fa")).pack(side="left", padx=8)
        detect()

    # -------- PipelineCore 宿主接口（Tk 实现，负责线程封送）--------
    def set_status(self, text):
        self.root.after(0, self._set_status, text)

    def set_step(self, n):
        self.root.after(0, self._set_step, n)

    def set_workspace(self, path):
        self.root.after(0, self.ws_var.set, path)

    def show_eval(self, mean_obj):
        self.root.after(0, self._show_eval_popup, mean_obj)

    def set_progress(self, frac, detail):
        def _ui():
            if frac is not None:
                self.progress.configure(mode="determinate")
                self.progress.set(max(0.0, min(1.0, float(frac))))
            if detail is not None:
                self.progress_detail_var.set(detail)
        self.root.after(0, _ui)

    def set_running(self, running, indeterminate=True):
        self.root.after(0, self._apply_running, running, indeterminate)

    def _apply_running(self, running, indeterminate):
        self._set_params_enabled(not running)
        self.run_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self.progress.configure(mode="indeterminate" if indeterminate else "determinate")
            if indeterminate:
                self.progress.start()
            else:
                self.progress.stop()
        else:
            self.stop_flag = False
            self.progress.stop()
            self.progress.set(0)

    def ask_continue(self, do_colmap):
        """UI 线程调用：训练前耗时预估确认。"""
        try:
            quality = self.quality_var.get()
            steps = self.vs_steps_var.get()
            devices, _ = syscheck.enumerate_vulkan_devices()
            best = syscheck.pick_device(devices)
            laptop = syscheck.detect_laptop(devices)
            measured = (syscheck.load_cache().get("measured_ips") or {}).get(quality)
            est_train = syscheck.estimate_train_seconds(
                best, quality, steps, measured_ips=measured, laptop=laptop) if best else None
            if est_train is None:
                return True
            est_colmap = (syscheck.estimate_colmap_seconds(self._count_selected_images(), laptop=laptop)
                          if do_colmap else None)
            est = est_train + (est_colmap or 0)
            lines = [f"预计耗时：{syscheck.format_duration(est)}"]
            if do_colmap and est_colmap:
                lines.append(f"  其中 COLMAP 约 {syscheck.format_duration(est_colmap)}，"
                             f"训练约 {syscheck.format_duration(est_train)}")
            else:
                lines.append(f"  训练 {steps} 步（{quality}档）")
            if laptop and not measured:
                lines.append(f"  笔记本已按 {syscheck.LAPTOP_PENALTY}x 保守放大，实际可能更短")
            lines.append("  基于上次实测速度" if measured
                         else "  首次估算，跑过一次后会用实测速度修正")
            lines.append("")
            lines.append("是否继续？")
            return messagebox.askyesno("耗时预估", "\n".join(lines))
        except Exception:
            return True

    def ask_resume(self):
        """UI 线程调用：检测工作区里的 checkpoint，询问是否继续训练。"""
        ws_dir = resolve_path(self.ws_var.get().strip() or "")
        if not ws_dir or not os.path.isdir(ws_dir):
            return
        step_path = os.path.join(ws_dir, "checkpoint.ply.step")
        ply_path = os.path.join(ws_dir, "checkpoint.ply")
        if not (os.path.isfile(ply_path) and os.path.isfile(step_path)):
            legacy = os.path.join(ws_dir, "checkpoint.npz")
            if os.path.isfile(legacy):
                try:
                    os.remove(legacy)
                except OSError:
                    pass
            return
        try:
            step = int(open(step_path, encoding="utf-8").read().strip())
        except Exception:
            return
        choice = messagebox.askyesno(
            "检测到上次未完成的训练",
            f"在该工作区发现训练中断的恢复点（step={step}）。\n\n"
            f"• 是 → 从 step {step} 继续训练\n"
            f"• 否 → 从头开始（删除恢复点）",
        )
        if not choice:
            for p in (ply_path, step_path):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def start_pipeline(self):
        self.start(do_colmap=True, do_train=True)

    def start_colmap_only(self):
        self.start(do_colmap=True, do_train=False)

    def start_train_only(self):
        self.start(do_colmap=False, do_train=True)


def main():
    root = ctk.CTk()
    app = QuickSplatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
