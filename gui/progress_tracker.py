# -*- coding: utf-8 -*-
"""进度与阶段状态：分段映射、时间线、逐张进度、训练实测值。

PipelineCore 只负责编排；这里集中管理「这次跑到哪、整条进度多少、
训练耗时/高斯数/峰值显存」这些状态，避免它们散落在管线各处。
"""
import re
import time

# 整条管线共用一根进度条，这里只负责把阶段内的 0~1 映射到整条进度。
# 末尾的显存字段是可选的：旧版训练器只报 5 项，缺了也不能当成解析失败。
_PROGRESS_RE = re.compile(
    r"PROGRESS:\s*(\d+)/(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)(?:\s+(\d+))?")

# COLMAP 逐张日志
_COLMAP_REGISTER_RE = re.compile(
    r"Registering image #(\d+)(?:\s*\(num_reg_frames=(\d+)\))?")
_COLMAP_PROCESS_RE = re.compile(r"Processed file \[(\d+)/(\d+)\]")

# 训练器结束时打印的实测值
_TRAIN_SECONDS_RE = re.compile(r"Time elapsed:\s*([\d.]+)\s*seconds")
_PEAK_VRAM_RE = re.compile(r"Peak VRAM usage:\s*([\d.]+)\s*GiB")
_NUM_SPLATS_RE = re.compile(r"Num splats:\s*(\d+)")

# 训练进程内部的收尾（写 PLY → 渲染验证图 → 评估）没有统一的开始日志
_EVAL_MARKERS = ("Writing PLY", "Rendering train images", "Rendering val images",
                 "Running eval", "跳过 LPIPS", "LPIPS 权重未缓存")


class ProgressTracker:
    """宿主（PipelineCore）持有一个实例；宿主只负责把回调转给界面。"""

    def __init__(self, host):
        self.host = host
        self.p_lo, self.p_hi = 0.0, 1.0
        self.colmap_span, self.train_span = (0.0, 1.0), (0.0, 1.0)
        self.colmap_t0 = None
        self.colmap_last_n = 0
        self.stage_now = 0
        self.stage_ids = None
        self.reuse = False
        self.train_params = {}
        self.train_stats = {}

    # ------------------------------------------------------------ 运行生命周期 ----
    def reset_run(self):
        """新一轮开始：清掉上一轮的阶段/训练结果。"""
        self.train_params = {}
        self.train_stats = {}
        self.stage_now = 0
        self.reuse = False

    def configure(self, run_colmap, do_train):
        """按本次要做的事划分整条进度的区段。"""
        both = run_colmap and do_train
        self.colmap_span = (0.0, 0.30) if both else (0.0, 1.0)
        self.train_span = (0.30, 1.0) if both else (0.0, 1.0)
        self.set_span(*(self.colmap_span if run_colmap else self.train_span))

    # ------------------------------------------------------------ 分段映射 ----
    def set_span(self, lo, hi):
        self.p_lo, self.p_hi = float(lo), float(hi)

    def set_train_span(self, a, b):
        """把训练大段（准备/训练/评估/导出）内部的 [a,b] 映射到整条进度。"""
        lo, hi = self.train_span
        self.set_span(lo + (hi - lo) * a, lo + (hi - lo) * b)

    def map_progress(self, frac):
        """把阶段内的 0~1 映射到整条进度的当前区间。"""
        f = max(0.0, min(1.0, float(frac)))
        return self.p_lo + (self.p_hi - self.p_lo) * f

    def progress(self, frac, detail):
        self.host.set_progress(self.map_progress(frac), detail)

    # ------------------------------------------------------------ 阶段时间线 ----
    def stage_plan(self, stages):
        """告诉宿主本次实际要跑哪几段；宿主没实现就静默跳过。"""
        self.stage_ids = list(stages)
        self.stage_now = 0
        fn = getattr(self.host, "set_stage_plan", None)
        if callable(fn):
            try:
                fn(list(stages))
            except Exception:
                pass

    def stage(self, n):
        """进入第 n 段；只许前进，计划外（本次不跑）的段直接忽略。"""
        n = int(n)
        if self.stage_ids is not None and n not in self.stage_ids:
            return
        if n <= self.stage_now:      # 续训/重跑时同段可能再次进入，不重复报
            return
        self.stage_now = n
        fn = getattr(self.host, "set_stage", None)
        if callable(fn):
            try:
                fn(n)
            except Exception:
                pass

    # ------------------------------------------------------------ 训练实测值 ----
    def record_train_stats(self, line):
        """从训练器输出里记下耗时/高斯数/显存，训练完成时和参数一起展示。

        "Time elapsed / Num splats / Peak VRAM" 是训练器结束时打印的权威值；
        PROGRESS 里的数是过程中的，只在缺权威值时兜底（续训/旧版训练器）。
        """
        m = _TRAIN_SECONDS_RE.search(line)
        if m:
            try:
                self.train_stats["seconds"] = float(m.group(1))
            except ValueError:
                pass
        m = _PEAK_VRAM_RE.search(line)
        if m:
            try:
                self.train_stats["peak_vram_gb"] = float(m.group(1))
            except ValueError:
                pass
        m = _NUM_SPLATS_RE.search(line)
        if m:
            try:
                self.train_stats["num_splats"] = int(m.group(1))
            except ValueError:
                pass
        m = _PROGRESS_RE.search(line)
        if m:
            _s, _t, elapsed, _eta, n_splats, vram_mb = m.groups()
            try:
                self.train_stats.setdefault("seconds", float(elapsed))
                self.train_stats["num_splats"] = int(n_splats)
                if vram_mb:
                    self.train_stats["vram_mb"] = int(vram_mb)
            except ValueError:
                pass

    def set_train_params(self, params):
        self.train_params = dict(params or {})

    def train_summary(self):
        """训练完成弹窗要展示的「怎么跑的 + 跑成什么样」。"""
        out = dict(self.train_params or {})
        out.update(self.train_stats or {})
        return out

    def stage_from_output(self, line):
        """训练进程的输出里认「已离开训练循环」：写 PLY / 渲染 / 评估。"""
        if self.stage_now != 5:
            return
        if any(m in line for m in _EVAL_MARKERS):
            self.stage(6)
            if self.stage_now != 6:
                return      # 本次没安排评估，状态交给后面的训练完成/导出流程
            self.set_train_span(0.92, 0.99)
            self.progress(0.0, "训练完成，正在收尾（写 PLY、渲染验证图、评估质量）...")
            self.host.set_status("训练完成，正在评估模型质量（通常 1~2 分钟）...")

    # ------------------------------------------------------------ COLMAP 逐张 ----
    def reset_colmap_timing(self):
        self.colmap_t0 = None
        self.colmap_last_n = 0

    def colmap_line_progress(self, line, total):
        """从 COLMAP 的逐张日志里读真实进度。

        feature_extractor → "Processed file [N/M]"；
        mapper → "Registering image #id (num_reg_frames=M)"，分子取括号里的
        已定位张数，不能拿图像 id 当进度（刚定位第 3 张时 id 可能已经很大）。
        """
        m = _COLMAP_PROCESS_RE.search(line)
        if m:
            n, seen_total = int(m.group(1)), int(m.group(2))
            self.step_progress(n, seen_total or total, "正在提取照片特征")
            return

        m = _COLMAP_REGISTER_RE.search(line)
        if not m:
            return
        n = int(m.group(2) or m.group(1))
        self.step_progress(n, total, "正在定位照片")

    def step_progress(self, n, total, verb):
        """阶段内逐张进度：只许前进，攒够 5 张再给剩余时间。"""
        if total <= 0:
            return
        n = max(0, min(n, total))
        # 场景不连通时 COLMAP 会另起一个子模型、计数从头开始，进度只许前进
        n = max(n, self.colmap_last_n)
        self.colmap_last_n = n
        now = time.time()
        t0 = self.colmap_t0
        if t0 is None:
            self.colmap_t0 = now
        detail = f"{verb} {n}/{total}"
        if n >= 5 and t0 is not None:
            used = max(now - t0, 1.0)
            left = used * max(total - n, 0) / float(n)
            detail += (f" · 已用 {used/60:.1f} 分钟"
                       f" · 预计还需 {left/60:.1f} 分钟")
        self.progress(n / float(total), detail)
