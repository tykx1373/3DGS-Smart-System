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
import shutil
import subprocess
import threading
import tempfile
import time
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
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                # 3DGS
CONFIG_PATH = os.path.join(SCRIPT_DIR, "quick_gui_config.json")

# 环境自检模块（gui/syscheck.py），GUI 向导与 doctor.py 共用同一份判定
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import syscheck  # noqa: E402

# 所有默认路径相对 PROJECT_ROOT 存储
DEFAULT_COLMAP = os.path.join("tools", "colmap-x64-windows-cuda", "COLMAP.bat")

def _find_vkgs_exe():
    """在 tools/ 下自动查找 vk_gaussian_splatting.exe，
    兼容不同版本目录名（如 vkgs-2026.2.9-windows-64bits）。"""
    tools = os.path.join(PROJECT_ROOT, "tools")
    if not os.path.isdir(tools):
        return os.path.join("tools", "vk_gaussian_splatting.exe")
    for root, dirs, files in os.walk(tools):
        if "vk_gaussian_splatting.exe" in files:
            return os.path.relpath(os.path.join(root, "vk_gaussian_splatting.exe"), PROJECT_ROOT)
    return os.path.join("tools", "vk_gaussian_splatting.exe")

DEFAULT_VKGS = _find_vkgs_exe()

# VkSplat 训练环境 Python（动态查找 vksplat conda 环境，找不到回退当前 Python）
def _find_vksplat_python():
    """优先查找项目目录下的 env/vksplat（自包含），其次常见 conda 安装路径，
    找不到则回退到当前运行 GUI 的 Python（要求其已 pip install vksplat）。"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(project_root, "env", "vksplat", "python.exe")
    if os.path.exists(p):
        return p
    for cmd in ("mamba", "conda"):
        exe = shutil.which(cmd)
        if exe:
            base = os.path.dirname(os.path.dirname(exe))
            p = os.path.join(base, "envs", "vksplat", "python.exe")
            if os.path.exists(p):
                return p
    for base in [
        os.path.expanduser(r"~\.conda"),
        r"C:\mambaforge", r"C:\miniforge3", r"C:\miniconda3", r"C:\anaconda3",
        r"D:\mambaforge", r"D:\miniforge3", r"D:\miniconda3-pbe", r"D:\miniconda3", r"D:\anaconda3",
        os.path.expanduser(r"~\mambaforge"), os.path.expanduser(r"~\miniforge3"),
        os.path.expanduser(r"~\miniconda3"), os.path.expanduser(r"~\anaconda3"),
        os.path.expanduser(r"~\AppData\Local\mambaforge"),
        os.path.expanduser(r"~\AppData\Local\miniforge3"),
        os.path.expanduser(r"~\AppData\Local\miniconda3"),
        os.path.expanduser(r"~\AppData\Local\anaconda3"),
        r"C:\ProgramData\mambaforge", r"C:\ProgramData\miniforge3",
        r"C:\ProgramData\miniconda3", r"C:\ProgramData\anaconda3",
    ]:
        p = os.path.join(base, "envs", "vksplat", "python.exe")
        if os.path.exists(p):
            return p
    return sys.executable

DEFAULT_VKSPLAT_PY = _find_vksplat_python()

TRAIN_BACKENDS = ["VkSplat"]

# 训练崩溃自动续训
TRAIN_MAX_RETRIES = 3   # 训练异常退出后，自动从恢复点续训的最大次数
TRAIN_RETRY_DELAY = 10  # 每次续训前的等待秒数（给 GPU/驱动恢复留时间）

# 字体常量
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_STEP = ("Microsoft YaHei UI", 11, "bold")
FONT_STEP_SUB = ("Microsoft YaHei UI", 9)
FONT_HINT = ("Microsoft YaHei UI", 9)
FONT_BIG_BTN = ("Microsoft YaHei UI", 13, "bold")
FONT_STATUS = ("Microsoft YaHei UI", 10)
FONT_LOG = ("Consolas", 11)

# tqdm 走 stderr 且用 \r 刷新，会把 stdout 的 PROGRESS 标记挤到行中间，
# 因此这里不要求行首匹配，而是在整行内查找进度标记。
_PROGRESS_RE = re.compile(r"PROGRESS:\s*(\d+)/(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)")


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


def resolve_path(p):
    if not p:
        return p
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(PROJECT_ROOT, p))


def relativize_path(p):
    if not p:
        return p
    if not os.path.isabs(p):
        return p
    try:
        rel = os.path.relpath(p, PROJECT_ROOT)
        if rel.startswith(".."):
            return p
        return rel
    except ValueError:
        return p


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "colmap_path": DEFAULT_COLMAP,
        "vkgs_exe": DEFAULT_VKGS,
        "vksplat_python": DEFAULT_VKSPLAT_PY,
    }


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=True)
    except Exception:
        pass


def _make_group(parent, title):
    """创建带标题的分组容器（替代 ttk.LabelFrame）。"""
    outer = ctk.CTkFrame(parent, corner_radius=8)
    ctk.CTkLabel(outer, text=title, font=FONT_STEP).pack(anchor="w", padx=12, pady=(8, 0))
    inner = ctk.CTkFrame(outer, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=12, pady=(4, 12))
    return outer, inner


# ------------------------------------------------------------------- app ----
class QuickSplatApp:
    def __init__(self, root):
        self.root = root
        root.title("3DGS 快速管线 - COLMAP + VkSplat(Vulkan) + VKGS")
        root.geometry("960x780")

        self.cfg = load_config()
        self.log_queue = queue.Queue()
        self.logger = setup_logger(self.log_queue)
        self.current_proc = None
        self.stop_flag = False

        self._ips_recorded = False
        self._build_ui()
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
        header.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(header, text="3D 照片重建", font=FONT_TITLE).pack(anchor="w")
        ctk.CTkLabel(header, text="把你拍的一组照片变成可旋转、可缩放的 3D 模型。",
                     font=FONT_HINT, text_color="#888").pack(anchor="w", pady=(2, 0))

        # ---- 步骤指示器 ----
        stepbar = ctk.CTkFrame(self.root, fg_color="transparent")
        stepbar.pack(fill="x", padx=16, pady=(8, 2))
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
        self.quality_var = tk.StringVar(value="标准")
        self._quality_radios = []
        for text in ("快速", "标准", "高质量"):
            rb = ctk.CTkRadioButton(r2, text=text, value=text, variable=self.quality_var,
                                    command=self._apply_quality_preset)
            rb.pack(side="left", padx=10)
            self._quality_radios.append(rb)
        self.quality_hint = ctk.CTkLabel(main, text="", font=FONT_HINT, text_color="#888")
        self.quality_hint.pack(anchor="w", pady=(0, 4))

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
        ctk.CTkLabel(btns, text="（可打开多个窗口对比，关闭窗口即退出）",
                     font=FONT_HINT, text_color="#888").pack(side="left", padx=10)

        # ---- 高级选项切换 ----
        self.adv_toggle_var = tk.StringVar(value="高级选项 ▼")
        self.adv_btn = ctk.CTkButton(self.root, textvariable=self.adv_toggle_var,
                                     command=self._toggle_advanced, height=32)
        self.adv_btn.pack(fill="x", padx=16, pady=(2, 0))

        # 高级选项独立窗口
        self.adv_window = ctk.CTkToplevel(self.root)
        self.adv_window.title("高级选项")
        self.adv_window.geometry("600x640")
        self.adv_window.withdraw()
        self.adv_window.protocol("WM_DELETE_WINDOW", self._hide_advanced)
        self.advanced_frame = ctk.CTkFrame(self.adv_window, fg_color="transparent")
        self.advanced_frame.pack(fill="both", expand=True, padx=14, pady=14)
        self._build_advanced_panel()

        # ---- 进度区 ----
        prog = ctk.CTkFrame(self.root, fg_color="transparent")
        prog.pack(fill="x", padx=16, pady=(6, 2))
        self.status_var = tk.StringVar(value="就绪。请先选择照片文件夹。")
        ctk.CTkLabel(prog, textvariable=self.status_var, font=FONT_STATUS, anchor="w").pack(fill="x")
        self.progress = ctk.CTkProgressBar(prog)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(6, 0))
        # 进度条下方的数值显示
        self.progress_detail_var = tk.StringVar(value="")
        ctk.CTkLabel(prog, textvariable=self.progress_detail_var,
                     font=FONT_HINT, text_color="#888").pack(anchor="w")

        # ---- 运行日志（独立窗口） ----
        self.log_btn = ctk.CTkButton(self.root, text="运行日志", command=self.toggle_log_window,
                                     height=32, fg_color="transparent", border_width=1,
                                     text_color=("#3b82f6", "#60a5fa"))
        self.log_btn.pack(fill="x", padx=16, pady=(2, 0))
        self._build_log_window()

        self._apply_quality_preset()
        self._refresh_backend_opts()

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
            ctk.CTkLabel(r, text=label, width=130, anchor="w").pack(side="left")
            ctk.CTkEntry(r, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
            ctk.CTkButton(r, text="浏览", width=70,
                          command=lambda v=var, f=ft: _browse_file(v, f)).pack(side="left")

        ctk.CTkLabel(af, text="项目工作区", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        rw = ctk.CTkFrame(af, fg_color="transparent")
        rw.pack(fill="x", pady=3)
        ctk.CTkLabel(rw, text="工作区文件夹:", width=130, anchor="w").pack(side="left")
        self.ws_var = tk.StringVar()
        ctk.CTkEntry(rw, textvariable=self.ws_var).pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(rw, text="浏览", width=70, command=self._browse_ws).pack(side="left")
        ctk.CTkLabel(af, text="（留空则自动生成到 workspaces/ 目录）",
                     font=FONT_HINT, text_color="#888").pack(anchor="w")

        ctk.CTkLabel(af, text="VkSplat 训练参数", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        self.vs_frame = ctk.CTkFrame(af, fg_color="transparent")
        self.vs_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(self.vs_frame, text="训练步数:", width=90, anchor="w").pack(side="left")
        self.vs_steps_var = tk.IntVar(value=15000)
        ctk.CTkEntry(self.vs_frame, textvariable=self.vs_steps_var, width=100).pack(side="left", padx=4)
        self.vs_mcmc_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.vs_frame, text="MCMC 优化",
                        variable=self.vs_mcmc_var).pack(side="left", padx=12)
        ctk.CTkLabel(self.vs_frame, text="图片缓存:", width=80, anchor="w").pack(side="left")
        self.vs_cache_var = tk.StringVar(value="cpu")
        ctk.CTkComboBox(self.vs_frame, variable=self.vs_cache_var,
                        values=["cpu", "gpu"], width=80, state="readonly").pack(side="left", padx=4)

        ctk.CTkLabel(af, text="COLMAP 选项", font=FONT_STEP).pack(anchor="w", pady=(12, 4))
        rc = ctk.CTkFrame(af, fg_color="transparent")
        rc.pack(fill="x", pady=3)
        ctk.CTkLabel(rc, text="最大图片尺寸:", width=130, anchor="w").pack(side="left")
        self.max_img_var = tk.IntVar(value=1600)
        ctk.CTkEntry(rc, textvariable=self.max_img_var, width=100).pack(side="left", padx=4)

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
            self.adv_toggle_var.set("高级选项 ▲")
        else:
            self.adv_window.withdraw()
            self.adv_toggle_var.set("高级选项 ▼")

    def _hide_advanced(self):
        self.adv_window.withdraw()
        self.adv_toggle_var.set("高级选项 ▼")

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

    def _make_output_ply_name(self, ws_dir):
        steps = self.vs_steps_var.get()
        quality = self.quality_var.get()
        quality_map = {"快速": "fast", "标准": "standard", "高质量": "high"}
        q = quality_map.get(quality, "standard")
        return os.path.join(ws_dir, f"vksplat_{steps}steps_{q}.ply")

    def _find_latest_ply(self, ws_dir):
        plys = [os.path.join(ws_dir, f) for f in os.listdir(ws_dir)
                if f.lower().endswith(".ply")]
        if not plys:
            return None
        return max(plys, key=os.path.getmtime)

    def _apply_quality_preset(self):
        q = self.quality_var.get()
        mapping = {
            "快速":   (5000,  "约 2~3 分钟（1/4 分辨率），快速预览轮廓"),
            "标准":   (15000, "约 8~10 分钟（半分辨率），推荐日常使用"),
            "高质量": (30000, "约 20 分钟+（全分辨率），细节最丰富"),
        }
        steps, hint = mapping.get(q, (15000, ""))
        self.vs_steps_var.set(steps)
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

    def _count_images(self, folder):
        if not folder or not os.path.isdir(folder):
            return 0
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
        return sum(1 for f in os.listdir(folder)
                   if f.lower().endswith(exts))

    def _browse_img(self):
        p = filedialog.askdirectory()
        if p:
            self.img_var.set(relativize_path(p))
            name = os.path.basename(p.rstrip("/\\"))
            n_imgs = self._count_images(p)
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

    def _save_paths(self):
        self.cfg["colmap_path"] = self.colmap_var.get()
        self.cfg["vkgs_exe"] = self.vkgs_var.get()
        self.cfg["vksplat_python"] = self.vksplat_py_var.get()
        save_config(self.cfg)
        self._log("[OK] 路径已保存到配置文件。")

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
        # tqdm 刷新帧（形如 "Training:  3%|██  | 95/3000 [...]"）只进日志文件
        if "%|" in text:
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

    # -------------------------------------------------------- colmap env ----
    def _resolve_colmap(self, colmap_path):
        p = colmap_path.strip()
        low = p.lower()
        if low.endswith(".bat"):
            base = os.path.dirname(p)
            exe = os.path.join(base, "bin", "colmap.exe")
        else:
            exe = p
            base = os.path.dirname(os.path.dirname(p))
        env = os.environ.copy()
        bin_dir = os.path.join(base, "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        plugins = os.path.join(base, "plugins")
        if os.path.isdir(plugins):
            env["QT_PLUGIN_PATH"] = plugins + os.pathsep + env.get("QT_PLUGIN_PATH", "")
        return exe, env

    # ----------------------------------------------------------- run cmd ----
    def run_cmd(self, cmd_list, env=None, cwd=None, graceful_ws_dir=None):
        display = " ".join(f'"{c}"' if (" " in c or c == "") else c for c in cmd_list)
        self._log(">>> " + display)
        try:
            self.current_proc = subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd,
            )
        except Exception as e:
            self._log(f"[FAIL] 启动失败: {e}")
            return False

        graceful_requested = False
        graceful_deadline = None
        for line in self.current_proc.stdout:
            if self.stop_flag and not graceful_requested:
                if graceful_ws_dir:
                    # 训练进程：写 STOP 文件，等它自己保存进度后退出
                    try:
                        with open(os.path.join(graceful_ws_dir, "STOP"), "w") as f:
                            f.write("stop")
                        graceful_requested = True
                        graceful_deadline = time.time() + 60
                        self._log("[WARN] 已请求安全停止，等待训练保存进度...")
                        self.root.after(0, self._set_status, "正在保存训练进度，请稍候...")
                        continue  # 继续读输出，等进程自己退出
                    except Exception:
                        pass
                try:
                    self.current_proc.terminate()
                except Exception:
                    pass
                self._log("[WARN] 已被用户停止。")
                return False
            # 安全网：优雅停止后超过 60 秒进程仍未退出，强制终止
            if graceful_requested and graceful_deadline and time.time() > graceful_deadline:
                try:
                    self.current_proc.terminate()
                except Exception:
                    pass
                self._log("[WARN] 等待超时，已强制终止训练进程（进度回退到上一个恢复点）。")
                return False
            line = line.rstrip()
            if line:
                self._log(line)
        self.current_proc.wait()
        rc = self.current_proc.returncode
        self.current_proc = None
        if graceful_requested:
            self._log("[WARN] 训练已安全停止，进度已保存。")
            return False
        if rc != 0:
            self._log(f"[FAIL] 退出码: {rc}")
            return False
        return True

    # -------------------------------------------------------- junction ----
    def _make_junction(self, link, target):
        target_abs = os.path.abspath(target)
        if os.path.exists(link):
            try:
                link_real = os.path.realpath(link)
                if os.path.normcase(link_real) == os.path.normcase(target_abs):
                    return True
                if os.path.islink(link):
                    os.unlink(link)
                else:
                    shutil.rmtree(link)
            except Exception:
                pass
        try:
            res = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                                 capture_output=True, text=True)
            if res.returncode == 0:
                return True
            self._log(f"[FAIL] mklink 失败: {res.stderr.strip() or res.stdout.strip()}")
            return False
        except Exception as e:
            self._log(f"[FAIL] 无法创建目录联接: {e}")
            return False

    # --------------------------------------------------- ensure sparse/0 ----
    def _ensure_sparse_zero(self, sparse_dir):
        sparse_zero = os.path.join(sparse_dir, "0")
        os.makedirs(sparse_zero, exist_ok=True)
        moved_something = False
        for fname in ("cameras.bin", "images.bin", "points3D.bin"):
            src = os.path.join(sparse_dir, fname)
            dst = os.path.join(sparse_zero, fname)
            if os.path.isfile(src) and not os.path.isfile(dst):
                shutil.move(src, dst)
                moved_something = True
        if moved_something:
            self._log("[INFO] 已将 COLMAP bin 文件移到 sparse/0/ 下。")
        return sparse_zero

    # -------------------------------------------------------- VkSplat py ----
    def _build_vksplat_script(self, dataset_dir, image_dir, sparse_dir,
                              output_dir, train_steps, cache_device,
                              device_id=-1, cap_max=1000000, resume_output_dir=None):
        resume_line = f", resume_output_dir=r\"{resume_output_dir}\"" if resume_output_dir else ""
        return f"""# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.abspath(r"{os.path.join(PROJECT_ROOT, 'tools', 'vksplat', 'vksplat')}"))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# 强制 UTF-8 输出，避免中文日志在 GUI 中乱码
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import simple_trainer
simple_trainer.TRAIN_DEVICE = {device_id}

from simple_trainer import MCMCTrainerConfig, TrainerConfig, train_main

if __name__ == "__main__":
    config = MCMCTrainerConfig(
        output_dir=r"{output_dir}",
        output_ply="splat.ply",
        train_steps={train_steps},
        max_steps={train_steps},
        refine_stop_iter={train_steps},
        dataset_dir=r"{dataset_dir}",
        image_dir=r"{image_dir}",
        sparse_dir=r"{sparse_dir}",
        image_cache_device="{cache_device}",
        cap_max={cap_max},
    )
    train_main(config{resume_line})
"""

    def _detect_gpu(self, vksp_py):
        detect_script = os.path.join(PROJECT_ROOT, "gui", "detect_gpu.py")
        spv_dir = os.path.join("tools", "vksplat", "vksplat", "shader", "generated")
        try:
            result = subprocess.run(
                [vksp_py, "-u", detect_script, spv_dir],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.join(PROJECT_ROOT, "tools", "vksplat", "vksplat"),
            )
            import json
            info = json.loads(result.stdout.strip().splitlines()[-1])
            return info["device_id"], info["is_integrated"], info["name"]
        except Exception as e:
            self._log(f"[WARN] GPU 检测失败，使用默认设备: {e}")
            return -1, False, "unknown"

    def _is_nvidia_gpu(self):
        """是否装有 NVIDIA 显卡（决定 COLMAP 用 CUDA 还是 noCUDA 版本）。

        用 PowerShell CIM 替代已弃用的 wmic（Win11 24H2 起移除）。
        """
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=15,
            )
            return "nvidia" in (result.stdout or "").lower()
        except Exception:
            return False

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

    def _count_selected_images(self):
        folder = resolve_path(self.img_var.get().strip()) if self.img_var.get().strip() else ""
        if not folder or not os.path.isdir(folder):
            return None
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
        try:
            return sum(1 for f in os.listdir(folder) if f.lower().endswith(exts))
        except Exception:
            return None

    def _confirm_estimate(self, do_colmap):
        """训练前给出耗时预估（笔记本保守放大），让用户决定是否继续。

        这里只做轻量估算（不含 run_all 的重型子进程检查），避免主线程卡顿。
        """
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

    def _ask_resume(self):
        """主线程调用：检测工作区里的 checkpoint，询问用户是否继续训练。"""
        ws_dir = resolve_path(self.ws_var.get().strip() or "")
        if not ws_dir or not os.path.isdir(ws_dir):
            return
        step_path = os.path.join(ws_dir, "checkpoint.ply.step")
        ply_path = os.path.join(ws_dir, "checkpoint.ply")
        if not (os.path.isfile(ply_path) and os.path.isfile(step_path)):
            # 清理旧版本的 npz checkpoint（已废弃）
            legacy = os.path.join(ws_dir, "checkpoint.npz")
            if os.path.isfile(legacy):
                try:
                    os.remove(legacy)
                except Exception:
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
                except Exception:
                    pass

    def run_vksplat_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        vksp_py = self.vksplat_py_var.get().strip() or DEFAULT_VKSPLAT_PY
        vksp_py = resolve_path(vksp_py)
        if not os.path.exists(vksp_py):
            self._log(f"[FAIL] VkSplat Python 未找到: {vksp_py}")
            return False

        # checkpoint 询问已在主线程完成（_ask_resume），此处只需日志
        if os.path.isfile(os.path.join(ws_dir, "checkpoint.ply")):
            self._log("[INFO] 检测到训练恢复点，将从中断处继续训练。")

        device_id, is_integrated, gpu_name = self._detect_gpu(vksp_py)
        quality = self.quality_var.get()
        res_map = {"快速": "images_4", "标准": "images_2", "高质量": "images"}
        cap_map = {"快速": 200000, "标准": 400000, "高质量": 800000}
        res_dir = res_map.get(quality, "images_2")
        base_cap = cap_map.get(quality, 400000)

        if gpu_name == "unknown":
            cap_max = base_cap
            cache = self.vs_cache_var.get()
            self._log(f"[WARN] GPU 检测失败，使用: cap_max={cap_max}，图片缓存={cache}")
        elif is_integrated:
            cap_max = min(base_cap, 200000 if quality == "快速" else 300000)
            cache = "cpu"
            self._log(f"[INFO] 检测到核显: {gpu_name}，cap_max={cap_max}，图片缓存=cpu")
        else:
            cap_max = base_cap
            cache = "gpu"
            self._log(f"[INFO] 检测到独显: {gpu_name}，cap_max={cap_max}，图片缓存=gpu，分辨率={res_dir}")

        steps = self.vs_steps_var.get()
        try:
            laptop = syscheck.detect_laptop()
            measured = (syscheck.load_cache().get("measured_ips") or {}).get(quality)
            est = syscheck.estimate_train_seconds(
                {"name": gpu_name}, quality, steps, measured_ips=measured, laptop=laptop)
            note = "基于上次实测速度" if measured else "首次估算"
            tail = "（笔记本已按保守系数放大）" if (laptop and not measured) else ""
            self._log(f"[INFO] 预计训练耗时（{note}）：{syscheck.format_duration(est)}{tail}")
        except Exception:
            pass
        dataset_dir = ws_dir.replace("\\", "/")
        image_dir = res_dir
        sparse_dir = os.path.relpath(sparse_zero, ws_dir).replace("\\", "/")
        output_dir = os.path.join(PROJECT_ROOT, "outputs").replace("\\", "/")
        os.makedirs(output_dir, exist_ok=True)

        existing_dirs = set()
        if os.path.isdir(output_dir):
            for d in os.listdir(output_dir):
                if os.path.isdir(os.path.join(output_dir, d)):
                    existing_dirs.add(d)

        script = self._build_vksplat_script(
            dataset_dir=dataset_dir, image_dir=image_dir,
            sparse_dir=sparse_dir, output_dir=output_dir,
            train_steps=steps, cache_device=cache,
            device_id=device_id, cap_max=cap_max,
            resume_output_dir=ws_dir.replace("\\", "/"),
        )

        tmp_path = os.path.join(tempfile.gettempdir(), "vksplat_train_generated.py")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(script)
        except Exception as e:
            self._log(f"[FAIL] 无法写出训练脚本: {e}")
            return False

        self._log(f"[INFO] 生成的训练脚本: {tmp_path}")
        cwd = ws_dir
        # 崩溃自动续训：训练进程异常退出且存在恢复点时，自动重跑（脚本会从 checkpoint 继续）
        ok = False
        retries = 0
        while True:
            ok = self.run_cmd([vksp_py, "-u", tmp_path], cwd=cwd, graceful_ws_dir=ws_dir)
            if ok or self.stop_flag:
                break  # 成功，或用户主动停止：不重试
            ckpt_ply = os.path.join(ws_dir, "checkpoint.ply")
            ckpt_step = os.path.join(ws_dir, "checkpoint.ply.step")
            if not (os.path.isfile(ckpt_ply) and os.path.isfile(ckpt_step)):
                self._log("[WARN] 训练异常退出，但没有可用恢复点（崩溃在首个存档点之前），无法自动续训。")
                break
            if retries >= TRAIN_MAX_RETRIES:
                self._log(f"[FAIL] 已自动续训 {TRAIN_MAX_RETRIES} 次仍未成功，停止。")
                break
            retries += 1
            self._log(f"[WARN] 训练异常退出，{TRAIN_RETRY_DELAY} 秒后自动从恢复点续训"
                      f"（第 {retries}/{TRAIN_MAX_RETRIES} 次）…")
            self.root.after(0, self._set_status,
                            f"训练异常，正在自动续训（第 {retries}/{TRAIN_MAX_RETRIES} 次）…")
            for _ in range(TRAIN_RETRY_DELAY):
                if self.stop_flag:
                    break
                time.sleep(1)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        if not ok:
            return False

        quality_en = {"快速": "fast", "标准": "standard", "高质量": "high"}.get(quality, "standard")
        target_name = f"vksplat_{steps}steps_{quality_en}"
        newest = None
        if os.path.isdir(output_dir):
            for d in os.listdir(output_dir):
                full = os.path.join(output_dir, d)
                if os.path.isdir(full) and d not in existing_dirs:
                    if newest is None or os.path.getmtime(full) > os.path.getmtime(newest):
                        newest = full

        if newest:
            target = os.path.join(output_dir, target_name)
            if os.path.exists(target):
                shutil.rmtree(target)
            try:
                os.rename(newest, target)
                self._log(f"[INFO] 输出目录已重命名: {target_name}")
            except Exception as e:
                self._log(f"[WARN] 重命名输出目录失败: {e}")
                target = newest

            cleaned = 0
            for f in os.listdir(target):
                if f.startswith("val_") and f.endswith(".png"):
                    try:
                        os.remove(os.path.join(target, f))
                        cleaned += 1
                    except Exception:
                        pass
            if cleaned:
                self._log(f"[INFO] 已清理 {cleaned} 张验证图（节省空间）")

            ply_path = os.path.join(target, "splat.ply")
            if os.path.exists(ply_path):
                shutil.copy2(ply_path, output_ply)
                self._log(f"[OK] 已将 PLY 复制到: {output_ply}")
                return True

        if os.path.isdir(output_dir):
            newest_ply = None
            newest_mtime = 0
            for root, _, files in os.walk(output_dir):
                for f in files:
                    if f.lower().endswith(".ply"):
                        full = os.path.join(root, f)
                        mt = os.path.getmtime(full)
                        if mt > newest_mtime:
                            newest_mtime = mt
                            newest_ply = full
            if newest_ply:
                shutil.copy2(newest_ply, output_ply)
                self._log(f"[OK] 已将最新 PLY 复制到: {output_ply}")
        return True

    # ----------------------------------------------------------- pipeline ----
    def _run_colmap(self, img_dir, ws_dir):
        colmap_path = resolve_path(self.colmap_var.get().strip())

        cuda_path = resolve_path(os.path.join("tools", "colmap-x64-windows-cuda", "COLMAP.bat"))
        nocuda_path = resolve_path(os.path.join("tools", "colmap-x64-windows-nocuda", "COLMAP.bat"))
        is_nvidia = self._is_nvidia_gpu()

        if not colmap_path or not os.path.exists(colmap_path):
            if is_nvidia and os.path.exists(cuda_path):
                colmap_path = cuda_path
                self._log("[INFO] 自动选择 COLMAP CUDA 版本。")
            elif os.path.exists(nocuda_path):
                colmap_path = nocuda_path
                self._log("[INFO] 自动选择 COLMAP noCUDA 版本（兼容所有显卡）。")
            else:
                self._log("[FAIL] COLMAP 路径未找到，请先运行 download_tools.bat。")
                return None, None, None
        else:
            if "cuda" in colmap_path.lower() and not is_nvidia and os.path.exists(nocuda_path):
                colmap_path = nocuda_path
                self._log("[INFO] 检测到非 NVIDIA GPU，自动切换到 COLMAP noCUDA 版本。")

        colmap_exe, colmap_env = self._resolve_colmap(colmap_path)
        if not os.path.exists(colmap_exe):
            self._log(f"[FAIL] colmap.exe 未找到: {colmap_exe}")
            return None, None, None

        os.makedirs(ws_dir, exist_ok=True)
        images_link = os.path.join(ws_dir, "images")
        if not self._make_junction(images_link, img_dir):
            return None, None, None
        self._make_junction(os.path.join(ws_dir, "images_2"), img_dir)
        self._make_junction(os.path.join(ws_dir, "images_4"), img_dir)

        db_path = os.path.join(ws_dir, "database.db")
        sparse_dir = os.path.join(ws_dir, "sparse")
        os.makedirs(sparse_dir, exist_ok=True)
        max_img = self.max_img_var.get()

        self._log("===== 步骤 1/3: COLMAP 特征提取 =====")
        if not self.run_cmd([
            colmap_exe, "feature_extractor",
            "--database_path", db_path,
            "--image_path", images_link,
            "--FeatureExtraction.max_image_size", str(max_img),
        ], env=colmap_env):
            return None, None, None

        if self.stop_flag:
            return None, None, None

        self._log("===== 步骤 2/3: COLMAP 特征匹配 =====")
        if not self.run_cmd([
            colmap_exe, "exhaustive_matcher",
            "--database_path", db_path,
        ], env=colmap_env):
            return None, None, None

        if self.stop_flag:
            return None, None, None

        self._log("===== 步骤 3/3: COLMAP 稀疏重建 =====")
        if not self.run_cmd([
            colmap_exe, "mapper",
            "--database_path", db_path,
            "--image_path", images_link,
            "--output_path", sparse_dir,
        ], env=colmap_env):
            return None, None, None

        sparse_zero = self._ensure_sparse_zero(sparse_dir)
        return colmap_exe, colmap_env, sparse_zero

    def _run_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        self._log("===== 步骤 4/5: VkSplat 训练 (Vulkan) =====")
        return self.run_vksplat_train(ws_dir, img_dir, sparse_zero, output_ply)

    def _run_viewer(self, output_ply):
        self._log("===== 步骤 5/5: 启动 VKGS 查看器 =====")
        vkgs = resolve_path(self.vkgs_var.get().strip())
        if vkgs and os.path.exists(vkgs):
            try:
                subprocess.Popen([vkgs, output_ply])
                self._log("[OK] 查看器已启动。")
            except Exception as e:
                self._log(f"[FAIL] 无法启动查看器: {e}")
        else:
            self._log(f"[WARN] VKGS 查看器未配置。输出 PLY: {output_ply}")

    def pipeline_thread(self, do_colmap=True, do_train=True):
        try:
            img_dir = resolve_path(self.img_var.get().strip())
            ws_dir = resolve_path(self.ws_var.get().strip())

            if not img_dir or not os.path.isdir(img_dir):
                self.root.after(0, self._set_status, "图片文件夹无效，请重新选择。")
                self._log("[FAIL] 图片文件夹无效。")
                return

            if not ws_dir:
                name = os.path.basename(img_dir.rstrip("/\\")) or "project"
                n_imgs = self._count_images(img_dir)
                ws_dir = os.path.join(PROJECT_ROOT, "workspaces", f"{name}_{n_imgs}imgs_gs")
                self.root.after(0, self.ws_var.set, relativize_path(ws_dir))

            os.makedirs(ws_dir, exist_ok=True)
            output_ply = self._make_output_ply_name(ws_dir)

            if do_colmap:
                self.root.after(0, self._set_step, 1)
                self.root.after(0, self._set_status,
                                "正在识别照片中的特征点并计算相机位置...（这一步最耗时）")
                _, _, sparse_zero = self._run_colmap(img_dir, ws_dir)
                if sparse_zero is None:
                    self.root.after(0, self._set_status, "空间定位失败，请查看日志。")
                    return
            else:
                sparse_zero = os.path.join(ws_dir, "sparse", "0")
                if not os.path.isdir(sparse_zero):
                    self.root.after(0, self._set_status, "未找到已有的空间定位结果。")
                    self._log(f"[FAIL] 未找到已有 sparse/0 目录: {sparse_zero}")
                    return
                self._log(f"[INFO] 跳过 COLMAP，复用已有稀疏重建: {sparse_zero}")

            if self.stop_flag:
                return

            if do_train:
                self.root.after(0, self._set_step, 2)
                self.root.after(0, self._set_status, "正在训练 3D 模型...（请耐心等待）")
                self.root.after(0, self.progress.stop)
                self.root.after(0, self.progress.configure, {"mode": "determinate"})
                self.root.after(0, self.progress.set, 0)
                self.root.after(0, self.progress_detail_var.set, "准备训练...")
                if not self._run_train(ws_dir, img_dir, sparse_zero, output_ply):
                    if self.stop_flag:
                        self.root.after(0, self._set_status, "训练已安全停止，进度已保存，下次可继续。")
                    else:
                        self.root.after(0, self._set_status, "模型训练失败，请查看日志。")
                    return

                if self.stop_flag:
                    return

                self.root.after(0, self._set_step, 3)
                self.root.after(0, self._set_status, "训练完成，正在打开 3D 查看器...")
                self._run_viewer(output_ply)
                self._log(f"[OK] 全部完成! 输出: {output_ply}")
                self.root.after(0, self._set_status, "完成！3D 模型已生成，可随时点「查看 3D 模型」重新打开。")
            else:
                self.root.after(0, self._set_step, 1)
                self.root.after(0, self._set_status, "空间定位完成。可点「开始生成 3D 模型」继续训练，或直接查看已有模型。")
                self._log("[OK] COLMAP 空间定位完成。")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log(f"[FAIL] 未预期的错误: {e}")
            self.root.after(0, self._set_status, f"发生错误: {e}")
        finally:
            self.root.after(0, self._on_done)

    def start_pipeline(self):
        self._ask_resume()
        if not self._confirm_estimate(do_colmap=True):
            return
        self._ips_recorded = False
        self.stop_flag = False
        self._set_params_enabled(False)
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.progress_detail_var.set("")
        threading.Thread(target=self.pipeline_thread, kwargs={"do_colmap": True, "do_train": True},
                         daemon=True).start()

    def start_colmap_only(self):
        self.stop_flag = False
        self._set_params_enabled(False)
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.progress_detail_var.set("")
        threading.Thread(target=self.pipeline_thread, kwargs={"do_colmap": True, "do_train": False},
                         daemon=True).start()

    def start_train_only(self):
        self._ask_resume()
        if not self._confirm_estimate(do_colmap=False):
            return
        self._ips_recorded = False
        self.stop_flag = False
        self._set_params_enabled(False)
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.progress_detail_var.set("准备训练...")
        threading.Thread(target=self.pipeline_thread, kwargs={"do_colmap": False, "do_train": True},
                         daemon=True).start()

    def stop_pipeline(self):
        self.stop_flag = True
        self._log("[WARN] 用户请求停止...")
        # 注意：不要在这里 terminate —— 训练进程由 run_cmd 通过 STOP 文件
        # 优雅停止（保存进度），其他进程（COLMAP 等）由 run_cmd 强制终止。

    def _on_done(self):
        self.stop_flag = False
        self._set_params_enabled(True)
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.progress.stop()
        self.progress.set(0)


def main():
    root = ctk.CTk()
    app = QuickSplatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
