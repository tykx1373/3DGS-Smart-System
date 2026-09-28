# -*- coding: utf-8 -*-
"""
3DGS 快速管线 GUI
串联：COLMAP (CUDA/nocuda) 稀疏重建 -> VkSplat (Vulkan) 训练 -> VKGS 实时渲染

运行：python quick_gui.py
说明：本文件以 UTF-8 (无 BOM) 保存，首行声明编码，可直接含中文源码。
      所有传给外部程序 (COLMAP/VkSplat) 的命令行参数保持 ASCII。
"""
import os
import sys
import json
import queue
import shutil
import subprocess
import threading
import tempfile
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk, messagebox

# ---------------------------------------------------------------- config ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # 3DGS/gui
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                # 3DGS
CONFIG_PATH = os.path.join(SCRIPT_DIR, "quick_gui_config.json")

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
    # Strategy 0: project-local env (self-contained, most reliable)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(project_root, "env", "vksplat", "python.exe")
    if os.path.exists(p):
        return p
    # Strategy 1: find conda/mamba via PATH, derive env python from its base dir
    for cmd in ("mamba", "conda"):
        exe = shutil.which(cmd)
        if exe:
            # e.g. C:\miniforge3\Scripts\conda.exe -> C:\miniforge3
            base = os.path.dirname(os.path.dirname(exe))
            p = os.path.join(base, "envs", "vksplat", "python.exe")
            if os.path.exists(p):
                return p
    # Strategy 2: search common install paths
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


class _GuiLogHandler(logging.Handler):
    """把 logging 记录转发到 GUI 的 queue（供 _poll_log 显示）。"""
    # logging 级别 -> GUI 显示前缀
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
            # [OK] 消息用绿色前缀，其余按级别映射
            if getattr(record, "is_ok", False):
                prefix = "[OK]"
            else:
                prefix = self._LEVEL_PREFIX.get(record.levelno, "[INFO]")
            self.log_queue.put(f"{prefix} {record.getMessage()}")
        except Exception:
            pass


def setup_logger(log_queue):
    """配置日志：同时输出到文件和 GUI。
    - 文件：logs/YYYYMMDD.log，单文件最大 10MB，保留 5 个备份
    - GUI：通过 queue 转发到 Text 控件"""
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, datetime.now().strftime("%Y%m%d") + ".log")

    logger = logging.getLogger("quick_gui")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # 文件 Handler：带时间戳、级别
    fmt_file = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                                 datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024,
                             backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_file)
    logger.addHandler(fh)

    # GUI Handler：自动加级别前缀
    gh = _GuiLogHandler(log_queue)
    gh.setLevel(logging.DEBUG)
    logger.addHandler(gh)

    return logger


def resolve_path(p):
    """将相对路径解析为绝对路径（相对于 PROJECT_ROOT），绝对路径原样返回。"""
    if not p:
        return p
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(PROJECT_ROOT, p))


def relativize_path(p):
    """将绝对路径转为相对路径（相对于 PROJECT_ROOT），不在项目根下的原样返回。"""
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


# ------------------------------------------------------------------- app ----
class QuickSplatApp:
    def __init__(self, root):
        self.root = root
        root.title("3DGS 快速管线 - COLMAP + VkSplat(Vulkan) + VKGS")
        root.geometry("920x760")

        self.cfg = load_config()
        self.log_queue = queue.Queue()
        self.logger = setup_logger(self.log_queue)
        self.current_proc = None
        self.stop_flag = False

        self._build_ui()
        self._poll_log()

    # ------------------------------------------------------------ UI build ----
    def _build_ui(self):
        # ---- 全局样式 ----
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Step.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("StepSub.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("Hint.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Big.TButton", font=("Microsoft YaHei UI", 12, "bold"), padding=10)
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10))

        # 颜色状态
        self.COLOR_PENDING = "#9e9e9e"
        self.COLOR_ACTIVE = "#1976d2"
        self.COLOR_DONE = "#388e3c"

        # ---- 标题区 ----
        header = ttk.Frame(self.root, padding=(10, 12, 10, 4))
        header.pack(fill="x")
        ttk.Label(header, text="3D 照片重建", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="把你拍的一组照片变成可旋转、可缩放的 3D 模型。",
                  style="Hint.TLabel", foreground="#555").pack(anchor="w", pady=(2, 0))

        # ---- 步骤指示器 ----
        stepbar = ttk.Frame(self.root, padding=(10, 6, 10, 2))
        stepbar.pack(fill="x")
        self.step_labels = []
        step_infos = [
            ("①", "选择照片", "选一个装照片的文件夹"),
            ("②", "生成 3D 模型", "电脑自动计算（几分钟~几十分钟）"),
            ("③", "查看结果", "自动打开 3D 查看器"),
        ]
        for i, (num, title, sub) in enumerate(step_infos):
            cell = ttk.Frame(stepbar)
            cell.grid(row=0, column=i, padx=6, sticky="ew")
            stepbar.columnconfigure(i, weight=1)
            num_lbl = ttk.Label(cell, text=f"  {num}  ", style="Step.TLabel",
                                foreground=self.COLOR_PENDING)
            num_lbl.pack(side="left")
            txt = ttk.Frame(cell)
            txt.pack(side="left")
            ttk.Label(txt, text=title, style="Step.TLabel",
                      foreground=self.COLOR_PENDING).pack(anchor="w")
            ttk.Label(txt, text=sub, style="StepSub.TLabel",
                      foreground=self.COLOR_PENDING).pack(anchor="w")
            self.step_labels.append((num_lbl, txt))
        self._set_step(1)

        # ---- 主操作区：照片选择 + 质量档位 + 开始按钮 ----
        main = ttk.LabelFrame(self.root, text="操作面板", padding=10)
        main.pack(fill="x", padx=10, pady=6)

        # 照片选择
        r1 = ttk.Frame(main)
        r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="照片文件夹：", width=14).pack(side="left")
        self.img_var = tk.StringVar()
        self._img_entry = ttk.Entry(r1, textvariable=self.img_var)
        self._img_entry.pack(side="left", fill="x", expand=True, padx=4)
        self._img_browse_btn = ttk.Button(r1, text="浏览…", width=8, command=self._browse_img)
        self._img_browse_btn.pack(side="left")
        ttk.Label(main, text="拍照小技巧：绕物体一圈拍，每张重叠 60% 以上，建议 30~200 张。",
                  style="Hint.TLabel", foreground="#1976d2").pack(anchor="w", pady=(0, 4))

        # 质量档位
        r2 = ttk.Frame(main)
        r2.pack(fill="x", pady=4)
        ttk.Label(r2, text="质量档位：", width=14).pack(side="left")
        self.quality_var = tk.StringVar(value="标准")
        self._quality_radios = []
        for text in ("快速", "标准", "高质量"):
            rb = ttk.Radiobutton(r2, text=text, value=text, variable=self.quality_var,
                                 command=self._apply_quality_preset)
            rb.pack(side="left", padx=8)
            self._quality_radios.append(rb)
        self.quality_hint = ttk.Label(main, text="", style="Hint.TLabel", foreground="#666")
        self.quality_hint.pack(anchor="w", pady=(0, 4))

        # 大按钮行
        btns = ttk.Frame(main)
        btns.pack(fill="x", pady=(6, 0))
        self.run_btn = ttk.Button(btns, text="开始生成 3D 模型", style="Big.TButton",
                                  command=self.start_pipeline)
        self.run_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop_pipeline,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.view_btn = ttk.Button(btns, text="查看 3D 模型", command=self._open_viewer)
        self.view_btn.pack(side="left", padx=4)
        ttk.Label(btns, text="（可打开多个窗口对比，关闭窗口即退出）",
                  style="Hint.TLabel", foreground="#888").pack(side="left", padx=8)

        # ---- 高级选项（独立窗口） ----
        self.adv_toggle_var = tk.StringVar(value="高级选项")
        self.adv_btn = ttk.Button(self.root, textvariable=self.adv_toggle_var,
                                  command=self._toggle_advanced)
        self.adv_btn.pack(fill="x", padx=10, pady=(2, 0))

        # 独立窗口，初始隐藏
        self.adv_window = tk.Toplevel(self.root)
        self.adv_window.title("高级选项")
        self.adv_window.geometry("560x620")
        self.adv_window.withdraw()
        self.adv_window.protocol("WM_DELETE_WINDOW", self._hide_advanced)
        self.advanced_frame = ttk.Frame(self.adv_window, padding=12)
        self.advanced_frame.pack(fill="both", expand=True)

        # 高级选项内容（parent = advanced_frame，无需改动）
        self._build_advanced_panel()

        # ---- 进度区 ----
        prog = ttk.Frame(self.root, padding=(10, 4, 10, 2))
        prog.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪。请先选择照片文件夹。")
        ttk.Label(prog, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(prog, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 0))

        # ---- 日志 ----
        logf = ttk.LabelFrame(self.root, text="运行日志", padding=4)
        logf.pack(fill="both", expand=True, padx=10, pady=6)
        self.log = scrolledtext.ScrolledText(logf, state="disabled", height=14,
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        # 日志级别颜色标签
        self.log.tag_configure("info", foreground="#333333")
        self.log.tag_configure("ok", foreground="#1a7f1a")
        self.log.tag_configure("warn", foreground="#cc8800")
        self.log.tag_configure("fail", foreground="#cc2222")
        self.log.tag_configure("dbg", foreground="#888888")

        self._apply_quality_preset()
        self._refresh_backend_opts()

    # --------------------------------------------------- advanced panel ----
    def _build_advanced_panel(self):
        af = self.advanced_frame

        # 工具路径
        self.colmap_var = tk.StringVar(value=self.cfg.get("colmap_path", DEFAULT_COLMAP))
        self.vkgs_var = tk.StringVar(value=self.cfg.get("vkgs_exe", DEFAULT_VKGS))
        self.vksplat_py_var = tk.StringVar(value=self.cfg.get("vksplat_python", DEFAULT_VKSPLAT_PY))

        def _browse_file(var, filetypes):
            p = filedialog.askopenfilename(filetypes=filetypes)
            if p:
                var.set(relativize_path(p))

        ttk.Label(af, text="工具路径", style="Step.TLabel").pack(anchor="w", pady=(2, 2))
        rows = [
            ("COLMAP:", self.colmap_var,
             [("COLMAP", "*.bat *.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")]),
            ("VkSplat Python:", self.vksplat_py_var,
             [("Python", "python.exe pythonw.exe"), ("所有文件", "*.*")]),
            ("VKGS 查看器:", self.vkgs_var,
             [("可执行文件", "*.exe"), ("所有文件", "*.*")]),
        ]
        for label, var, ft in rows:
            r = ttk.Frame(af)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=label, width=18).pack(side="left")
            ttk.Entry(r, textvariable=var).pack(side="left", fill="x", expand=True, padx=4)
            ttk.Button(r, text="浏览", width=8,
                       command=lambda v=var, f=ft: _browse_file(v, f)).pack(side="left")

        # 工作区
        ttk.Label(af, text="项目工作区", style="Step.TLabel").pack(anchor="w", pady=(8, 2))
        rw = ttk.Frame(af)
        rw.pack(fill="x", pady=1)
        ttk.Label(rw, text="工作区文件夹:", width=18).pack(side="left")
        self.ws_var = tk.StringVar()
        ttk.Entry(rw, textvariable=self.ws_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(rw, text="浏览", width=8, command=self._browse_ws).pack(side="left")
        ttk.Label(af, text="（留空则自动生成到 workspaces/ 目录）",
                  style="Hint.TLabel", foreground="#888").pack(anchor="w")

        # VkSplat 训练参数
        ttk.Label(af, text="VkSplat 训练参数", style="Step.TLabel").pack(anchor="w", pady=(8, 2))
        self.vs_frame = ttk.Frame(af)
        self.vs_frame.pack(fill="x", pady=1)
        ttk.Label(self.vs_frame, text="训练步数:").pack(side="left")
        self.vs_steps_var = tk.IntVar(value=15000)
        ttk.Entry(self.vs_frame, textvariable=self.vs_steps_var, width=10).pack(side="left", padx=4)
        self.vs_mcmc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.vs_frame, text="MCMC 优化",
                        variable=self.vs_mcmc_var).pack(side="left", padx=6)
        ttk.Label(self.vs_frame, text="  图片缓存:").pack(side="left")
        self.vs_cache_var = tk.StringVar(value="cpu")
        ttk.Combobox(self.vs_frame, textvariable=self.vs_cache_var,
                     values=["cpu", "gpu"], width=6, state="readonly").pack(side="left", padx=4)

        # COLMAP 选项
        ttk.Label(af, text="COLMAP 选项", style="Step.TLabel").pack(anchor="w", pady=(8, 2))
        rc = ttk.Frame(af)
        rc.pack(fill="x", pady=1)
        ttk.Label(rc, text="最大图片尺寸:").pack(side="left")
        self.max_img_var = tk.IntVar(value=1600)
        ttk.Entry(rc, textvariable=self.max_img_var, width=8).pack(side="left", padx=4)

        # 分步按钮
        ttk.Label(af, text="分步操作", style="Step.TLabel").pack(anchor="w", pady=(8, 2))
        sb = ttk.Frame(af)
        sb.pack(fill="x", pady=1)
        ttk.Button(sb, text="只用 COLMAP（空间定位）",
                   command=self.start_colmap_only).pack(side="left", padx=4)
        ttk.Button(sb, text="只用训练（生成模型）",
                   command=self.start_train_only).pack(side="left", padx=4)
        ttk.Button(sb, text="保存路径配置",
                   command=self._save_paths).pack(side="left", padx=4)

    def _toggle_advanced(self):
        """显示或隐藏高级选项窗口。"""
        if self.adv_window.state() == "withdrawn":
            self.adv_window.deiconify()
            self.adv_window.lift()
            self.adv_window.focus_force()
        else:
            self.adv_window.withdraw()

    def _hide_advanced(self):
        """点窗口 X 时隐藏而非销毁，保留所有配置状态。"""
        self.adv_window.withdraw()

    # --------------------------------------------------- step / status ----
    def _set_step(self, n):
        """设置当前步骤高亮 (1/2/3)。"""
        colors = [self.COLOR_PENDING] * 3
        if n >= 1:
            colors[0] = self.COLOR_DONE if n > 1 else self.COLOR_ACTIVE
        if n >= 2:
            colors[1] = self.COLOR_DONE if n > 2 else self.COLOR_ACTIVE
        if n == 3:
            colors[2] = self.COLOR_ACTIVE
        for i, (num_lbl, txt) in enumerate(self.step_labels):
            fg = colors[i]
            num_lbl.configure(foreground=fg)
            for child in txt.winfo_children():
                try:
                    child.configure(foreground=fg)
                except tk.TclError:
                    pass

    def _set_status(self, text):
        self.status_var.set(text)

    def _make_output_ply_name(self, ws_dir):
        """生成带参数标识的输出 PLY 文件名。
        格式: vksplat_<steps>steps_<quality>.ply
        例如: vksplat_15000steps_standard.ply"""
        steps = self.vs_steps_var.get()
        quality = self.quality_var.get()
        quality_map = {"快速": "fast", "标准": "standard", "高质量": "high"}
        q = quality_map.get(quality, "standard")
        return os.path.join(ws_dir, f"vksplat_{steps}steps_{q}.ply")

    def _find_latest_ply(self, ws_dir):
        """在工作区里找最新的 .ply 文件（兼容旧的 splat.ply 和新的参数命名）。"""
        plys = [os.path.join(ws_dir, f) for f in os.listdir(ws_dir)
                if f.lower().endswith(".ply")]
        if not plys:
            return None
        return max(plys, key=os.path.getmtime)

    def _apply_quality_preset(self):
        """质量档位 -> 训练参数映射。所有档位统一使用 MCMC 策略。"""
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
        """训练开始时锁定所有参数输入，结束时恢复。防止用户忘记之前的设置。"""
        state = "normal" if enabled else "disabled"
        # 主面板控件
        self._img_entry.config(state=state)
        self._img_browse_btn.config(state=state)
        for rb in self._quality_radios:
            rb.config(state=state)
        # 高级选项窗口里的所有输入控件
        def _walk(widget):
            for child in widget.winfo_children():
                try:
                    child.config(state=state)
                except tk.TclError:
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

        # 没有模型时让用户选文件
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

        # 有多个模型时弹出列表让用户选，默认选中最新的
        self._viewer_pick = None
        dlg = tk.Toplevel(self.root)
        dlg.title("选择要查看的 3D 模型")
        dlg.geometry("480x360")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=f"工作区共有 {len(plys)} 个模型，默认选中最新的：",
                  padding=(12, 10)).pack(anchor="w")
        list_frame = ttk.Frame(dlg, padding=(12, 0))
        list_frame.pack(fill="both", expand=True)
        lb = tk.Listbox(list_frame, height=12, activestyle="dotbox")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        for p in plys:
            mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")
            size_mb = os.path.getsize(p) / 1024 / 1024
            lb.insert("end", f"{os.path.basename(p)}   ({size_mb:.0f} MB, {mtime})")
        lb.selection_set(0)  # 默认选最新的
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

        btns = ttk.Frame(dlg, padding=12)
        btns.pack(fill="x")
        ttk.Button(btns, text="打开选中的模型", command=_pick).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="选择其他文件…", command=_browse_other).pack(side="left")
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right")

        dlg.bind("<Double-Button-1>", lambda e: _pick())
        self.root.wait_window(dlg)
        if self._viewer_pick:
            self._run_viewer(self._viewer_pick)


    # ---------------------------------------------------------- UI helpers ----
    def _refresh_backend_opts(self):
        """VkSplat 是唯一训练后端，直接显示其参数面板。"""
        self.vs_frame.pack(fill="x", pady=2)

    def _count_images(self, folder):
        """统计文件夹里的图片数量（jpg/jpeg/png）。"""
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
            # 工作区名带图片数量，避免不同数据集共用工作区
            ws_rel = os.path.join("workspaces", f"{name}_{n_imgs}imgs_gs")
            ws_abs = resolve_path(ws_rel)

            # 一致性检测：工作区已存在时，检查图片数量是否匹配
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
                    if choice is None:  # 取消
                        return
                    if not choice:  # 否：重新生成工作区名
                        i = 2
                        while True:
                            ws_rel = os.path.join("workspaces", f"{name}_{n_imgs}imgs_{i}_gs")
                            if not os.path.isdir(resolve_path(ws_rel)):
                                break
                            i += 1
                        ws_abs = resolve_path(ws_rel)

            self.ws_var.set(ws_rel)
            self._set_step(2)
            # 检测是否已有模型（找最新的 .ply）
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
        """写日志。自动识别 [INFO]/[WARN]/[FAIL]/[DBG]/[OK] 前缀设置级别，
        消息前缀会被去掉，由 logging 系统统一添加。
        同时输出到 GUI（带前缀、颜色）和日志文件（logs/YYYYMMDD.log）。"""
        t = text.strip()
        low = t.lower()
        # 去掉已知级别前缀
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
                self.log.config(state="normal")
                # 按级别着色
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
                    tag = "info"
                self.log.insert("end", line + "\n", tag)
                self.log.see("end")
                self.log.config(state="disabled")
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
    def run_cmd(self, cmd_list, env=None, cwd=None):
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

        for line in self.current_proc.stdout:
            if self.stop_flag:
                try:
                    self.current_proc.terminate()
                except Exception:
                    pass
                self._log("[WARN] 已被用户停止。")
                return False
            line = line.rstrip()
            if line:
                self._log(line)
        self.current_proc.wait()
        rc = self.current_proc.returncode
        self.current_proc = None
        if rc != 0:
            self._log(f"[FAIL] 退出码: {rc}")
            return False
        return True

    # -------------------------------------------------------- junction ----
    def _make_junction(self, link, target):
        """创建目录联接。如果已存在但指向不同目标，则删除重建。"""
        target_abs = os.path.abspath(target)
        if os.path.exists(link):
            # 检查 junction 当前指向是否就是目标
            try:
                link_real = os.path.realpath(link)
                if os.path.normcase(link_real) == os.path.normcase(target_abs):
                    return True
                # 指向不一致，删除旧 junction
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
        """COLMAP mapper 默认输出到 sparse/0；
        VkSplat 需要 sparse/0/ 下的 .bin 文件。这里把 mapper 输出规范化。"""
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
                              device_id=-1, cap_max=1000000):
        """生成内联 Python 脚本调用 vksplat 库训练。
        直接调用 simple_trainer.train_main，确保路径拼接、initialize、
        训练循环、PLY 写入等步骤与参考实现完全一致。
        所有档位统一使用 MCMCTrainerConfig，效果远优于默认策略。"""
        return f"""# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.abspath(r"{os.path.join(PROJECT_ROOT, 'tools', 'vksplat', 'vksplat')}"))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import simple_trainer
simple_trainer.TRAIN_DEVICE = {device_id}  # 优先独显，核显自动降 cap_max

from simple_trainer import MCMCTrainerConfig, train_main

if __name__ == "__main__":
    # 关键：max_steps 和 refine_stop_iter 必须 == train_steps，
    # 否则 LR 调度只衰减到一半，位置不收敛（这是之前效果差的根因）。
    config = MCMCTrainerConfig(
        output_dir=r"{output_dir}",
        output_ply="splat.ply",
        train_steps={train_steps},
        max_steps={train_steps},          # LR 调度周期 = 训练步数
        refine_stop_iter={train_steps},   # 稠密化停止时机 = 训练结束
        dataset_dir=r"{dataset_dir}",
        image_dir=r"{image_dir}",
        sparse_dir=r"{sparse_dir}",
        image_cache_device="{cache_device}",
        cap_max={cap_max},
    )
    train_main(config)
"""

    def _detect_gpu(self, vksp_py):
        """检测 Vulkan 设备，优先独显。返回 (device_id, is_integrated, name)。"""
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
        """检测是否为 NVIDIA GPU（COLMAP CUDA 版本需要）。"""
        try:
            import subprocess as _sp
            result = _sp.run(["wmic", "path", "win32_VideoController", "get", "name"],
                             capture_output=True, text=True, timeout=10)
            names = result.stdout.lower()
            return ("nvidia" in names)
        except Exception:
            return False

    def run_vksplat_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        """用 vksplat conda 环境的 Python 跑训练。"""
        vksp_py = self.vksplat_py_var.get().strip() or DEFAULT_VKSPLAT_PY
        vksp_py = resolve_path(vksp_py)
        if not os.path.exists(vksp_py):
            self._log(f"[FAIL] VkSplat Python 未找到: {vksp_py}")
            return False

        # 检测 GPU，优先独显；核显限制 cap_max 防止 TDR 超时
        device_id, is_integrated, gpu_name = self._detect_gpu(vksp_py)
        quality = self.quality_var.get()
        # 质量档位 -> (训练分辨率目录, cap_max 上限)
        # 快速：1/4 分辨率 + 20 万点，约 2~3 分钟，能看出轮廓
        # 标准：半分辨率 + 40 万点，约 8~10 分钟，效果不错
        # 高质量：全分辨率 + 80 万点，约 20 分钟+，细节最好
        res_map = {"快速": "images_4", "标准": "images_2", "高质量": "images"}
        cap_map = {"快速": 200000, "标准": 400000, "高质量": 800000}
        res_dir = res_map.get(quality, "images_2")
        base_cap = cap_map.get(quality, 400000)

        if gpu_name == "unknown":
            cap_max = base_cap
            cache = self.vs_cache_var.get()
            self._log(f"[WARN] GPU 检测失败，使用: cap_max={cap_max}，图片缓存={cache}")
        elif is_integrated:
            # 核显再砍半，防止 TDR 超时
            cap_max = min(base_cap, 200000 if quality == "快速" else 300000)
            cache = "cpu"
            self._log(f"[INFO] 检测到核显: {gpu_name}，cap_max={cap_max}，图片缓存=cpu")
        else:
            cap_max = base_cap
            cache = "gpu"
            self._log(f"[INFO] 检测到独显: {gpu_name}，cap_max={cap_max}，图片缓存=gpu，分辨率={res_dir}")

        steps = self.vs_steps_var.get()
        # cache 已根据 GPU 类型自动设置（核显=cpu，独显=gpu）
        # 高级选项里手动选的值仅在 GPU 检测失败时作为 fallback

        dataset_dir = ws_dir.replace("\\", "/")
        # 按质量档位选择训练分辨率：images_4=1/4, images_2=半分辨率, images=全分辨率
        # COLMAP 用全分辨率重建，vkSplat 用低分辨率训练，提速且质量可控
        image_dir = res_dir
        sparse_dir = os.path.relpath(sparse_zero, ws_dir).replace("\\", "/")
        # VkSplat 原始训练输出（时间戳子目录）统一放到项目根 outputs/
        output_dir = os.path.join(PROJECT_ROOT, "outputs").replace("\\", "/")
        os.makedirs(output_dir, exist_ok=True)

        # 记录训练前已有的 outputs 子目录，训练后定位新增目录
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
        ok = self.run_cmd([vksp_py, "-u", tmp_path], cwd=cwd)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        if not ok:
            return False

        # 找到新增的 outputs 子目录，重命名为带参数的名字，并清理验证图
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
            # 同参数重训：删除旧目录
            target = os.path.join(output_dir, target_name)
            if os.path.exists(target):
                shutil.rmtree(target)
            try:
                os.rename(newest, target)
                self._log(f"[INFO] 输出目录已重命名: {target_name}")
            except Exception as e:
                self._log(f"[WARN] 重命名输出目录失败: {e}")
                target = newest

            # 清理 val_*.png（占空间且不需要）
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

            # 从清理后的目录找 splat.ply
            ply_path = os.path.join(target, "splat.ply")
            if os.path.exists(ply_path):
                shutil.copy2(ply_path, output_ply)
                self._log(f"[OK] 已将 PLY 复制到: {output_ply}")
                return True

        # fallback：遍历找最新 ply
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
        """COLMAP SfM 三步走。返回 (colmap_exe, env, sparse_zero) 或 (None, None, None)。"""
        colmap_path = resolve_path(self.colmap_var.get().strip())

        # 自动选择 CUDA / nocuda 版本：非 NVIDIA GPU 用 nocuda，CUDA 版本不存在时回退
        cuda_path = resolve_path(os.path.join("tools", "colmap-x64-windows-cuda", "COLMAP.bat"))
        nocuda_path = resolve_path(os.path.join("tools", "colmap-x64-windows-nocuda", "COLMAP.bat"))
        is_nvidia = self._is_nvidia_gpu()

        if not colmap_path or not os.path.exists(colmap_path):
            # 用户选的路径无效，自动选可用的
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
            # 用户选了 CUDA 版本但 GPU 不是 NVIDIA，自动切换
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
        # vkSplat 通过 image_dir 名称自动缩放分辨率：images_2=半分辨率，images_4=1/4 分辨率。
        # COLMAP 用全分辨率 images 做特征提取，vkSplat 按质量档位选低分辨率训练，提速 4~16 倍。
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
                self.root.after(0, self._set_status, "❌ 图片文件夹无效，请重新选择。")
                self._log("[FAIL] 图片文件夹无效。")
                return

            # 工作区留空则自动生成（带图片数量）
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
                    self.root.after(0, self._set_status, "❌ 空间定位失败，请查看日志。")
                    return
            else:
                # 检查已有的 sparse/0
                sparse_zero = os.path.join(ws_dir, "sparse", "0")
                if not os.path.isdir(sparse_zero):
                    self.root.after(0, self._set_status, "❌ 未找到已有的空间定位结果。")
                    self._log(f"[FAIL] 未找到已有 sparse/0 目录: {sparse_zero}")
                    return
                self._log(f"[INFO] 跳过 COLMAP，复用已有稀疏重建: {sparse_zero}")

            if self.stop_flag:
                return

            if do_train:
                self.root.after(0, self._set_step, 2)
                self.root.after(0, self._set_status, "正在训练 3D 模型...（请耐心等待）")
                if not self._run_train(ws_dir, img_dir, sparse_zero, output_ply):
                    self.root.after(0, self._set_status, "❌ 模型训练失败，请查看日志。")
                    return

                if self.stop_flag:
                    return

                self.root.after(0, self._set_step, 3)
                self.root.after(0, self._set_status, "✅ 训练完成，正在打开 3D 查看器...")
                self._run_viewer(output_ply)
                self._log(f"[OK] 全部完成! 输出: {output_ply}")
                self.root.after(0, self._set_status, "完成！3D 模型已生成，可随时点「查看 3D 模型」重新打开。")
            else:
                # 只跑了 COLMAP，没有模型，不打开查看器
                self.root.after(0, self._set_step, 1)
                self.root.after(0, self._set_status, "✅ 空间定位完成。可点「开始生成 3D 模型」继续训练，或直接查看已有模型。")
                self._log("[OK] COLMAP 空间定位完成。")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log(f"[FAIL] 未预期的错误: {e}")
            self.root.after(0, self._set_status, f"❌ 发生错误: {e}")
        finally:
            self.root.after(0, self._on_done)

    # ----------------------------------------------------------- controls ----
    def start_pipeline(self):
        if not self.img_var.get().strip():
            messagebox.showwarning("提示", "请先选择照片文件夹！\n\n点上面的「浏览…」按钮，选一个装着照片的文件夹。")
            return
        self.stop_flag = False
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_params_enabled(False)
        self.progress.start(12)
        threading.Thread(
            target=self.pipeline_thread, kwargs={"do_colmap": True, "do_train": True},
            daemon=True).start()

    def start_colmap_only(self):
        if not self.img_var.get().strip():
            messagebox.showwarning("提示", "请先选择照片文件夹！")
            return
        self.stop_flag = False
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_params_enabled(False)
        self.progress.start(12)
        threading.Thread(
            target=self.pipeline_thread, kwargs={"do_colmap": True, "do_train": False},
            daemon=True).start()

    def start_train_only(self):
        if not self.img_var.get().strip():
            messagebox.showwarning("提示", "请先选择照片文件夹！")
            return
        self.stop_flag = False
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_params_enabled(False)
        self.progress.start(12)
        threading.Thread(
            target=self.pipeline_thread, kwargs={"do_colmap": False, "do_train": True},
            daemon=True).start()

    def stop_pipeline(self):
        self.stop_flag = True
        if self.current_proc:
            try:
                self.current_proc.terminate()
            except Exception:
                pass
        self._log("[WARN] 用户请求停止...")
        self._set_status("⏹ 已停止。")

    def _on_done(self):
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self._set_params_enabled(True)
        self.progress.stop()


# ------------------------------------------------------------------ main ----
if __name__ == "__main__":
    root = tk.Tk()
    QuickSplatApp(root)
    root.mainloop()
