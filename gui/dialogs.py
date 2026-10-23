# -*- coding: utf-8 -*-
"""与流程无关的独立对话框：训练完成、环境自检。

页面只负责打开它们，具体展示逻辑留在这里，避免主窗口继续膨胀。
"""
import threading

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QWidget,
)

import syscheck
from eval_metrics import judge_eval_metrics
from pipeline_core import resolve_path
from qt_theme import make_label, PrimaryButton
from ui_helpers import _dur


class EvalDialog(QDialog):
    """训练完成：先给「这次怎么跑的 + 跑成什么样」，有评测再给质量分数。

    评测关掉时也弹这一页：步数、分辨率、耗时、高斯数同样值得看一眼。
    """

    def __init__(self, mean, on_view, on_share=None, parent=None, stats=None):
        super().__init__(parent)
        self.setWindowTitle("训练完成")
        self.setMinimumWidth(470)
        stats = stats or {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(6)
        lay.addWidget(make_label("训练完成", "title"))

        info = []
        if stats.get("quality"):
            info.append(("质量档位", str(stats["quality"]), ""))
        if stats.get("steps"):
            info.append(("训练步数", f"{int(stats['steps']):,} 步", ""))
        if stats.get("res_label"):
            info.append(("训练分辨率", str(stats["res_label"]), ""))
        if stats.get("n_imgs"):
            info.append(("照片", f"{int(stats['n_imgs'])} 张", ""))
        if "mcmc" in stats:
            info.append(("MCMC", "开启" if stats["mcmc"] else "关闭", ""))
        if stats.get("seconds") is not None:
            info.append(("本次训练用时", _dur(stats["seconds"]), ""))
        if stats.get("num_splats") is not None:
            info.append(("高斯点", f"{int(stats['num_splats']):,} 个", ""))
        if stats.get("peak_vram_gb") is not None:
            info.append(("峰值显存", f"{float(stats['peak_vram_gb']):.2f} GB", ""))
        elif stats.get("vram_mb"):
            info.append(("显存占用", f"{float(stats['vram_mb']) / 1024:.2f} GB", ""))

        def add_row(name, value, hint=""):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 1, 0, 1)
            a = QLabel(name)
            a.setFixedWidth(100)
            b = QLabel(value)
            rl.addWidget(a)
            rl.addWidget(b)
            if hint:
                b.setFixedWidth(110)
                c = make_label(hint, "caption")
                c.setWordWrap(True)
                rl.addWidget(c, 1)
            else:
                rl.addStretch(1)
            lay.addWidget(row)

        for name, value, hint in info:
            add_row(name, value, hint)

        if mean is not None:
            verdict, level, rows = judge_eval_metrics(mean)
            color = {"good": "#16a34a", "mid": "#d97706",
                     "bad": "#dc2626", "none": "#888888"}[level]
            lay.addSpacing(6)
            v = QLabel(verdict)
            v.setStyleSheet(f"color: {color}; font-weight: 600;")
            v.setWordWrap(True)
            lay.addWidget(v)
            for name, value, hint in rows:
                add_row(name, value, hint)
            lay.addWidget(make_label("逐图明细见模型输出目录里的 eval.json", "caption"))
        else:
            lay.addWidget(make_label(
                "本次没有质量评估分数（训练设置里未勾选「训练后质量评估」，"
                "或评估未完成）。", "caption"))

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


class _SyscheckSignals(QObject):
    done = Signal(object)


class SyscheckDialog(QDialog):
    """环境自检：逐项展示检查结果。"""

    def __init__(self, win, auto_close=False):
        super().__init__(win)
        self.win = win
        self.auto_close = auto_close
        self._sig = _SyscheckSignals()
        self._sig.done.connect(self._render)
        self._busy = False
        # 自动关闭计时器挂在对话框自己身上：窗口关闭/主窗口销毁时一起失效，
        # 不会留下一个对准已关闭窗口的悬空回调（连点自检时尤其危险）。
        self._auto_close = QTimer(self)
        self._auto_close.setSingleShot(True)
        self._auto_close.timeout.connect(self.accept)
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

    def detect(self):
        """起一个后台检测；已有检测在跑就直接忽略，防止连点叠出多个线程。"""
        if self._busy:
            return
        self._busy = True
        self._auto_close.stop()
        self.recheck.setEnabled(False)
        self.conclusion.setText("正在检测…")
        self.view.setPlainText("正在检测，请稍候…")
        # 参数在 UI 线程取好再交给工作线程：Qt 控件/宿主变量不在子线程里碰
        colmap_path = resolve_path(self.win.colmap_var.get().strip())
        vkgs_exe = resolve_path(self.win.vkgs_var.get().strip())
        quality = self.win.quality_var.get()
        steps = int(self.win.vs_steps_var.get())
        # 日志里留个脚印：万一检测过程中崩溃，诊断包能看出卡在哪一步
        self.win._log("[INFO] 环境自检：开始检测...")

        def work():
            try:
                summary = syscheck.summarize(
                    colmap_path=colmap_path, vkgs_exe=vkgs_exe,
                    quality=quality, steps=steps)
                syscheck.record_check()
            except Exception as e:
                # 线程里的异常没有人接：不兜住的话按钮会永远停在「检测中」，
                # 用户只会再点一次，进一步放大问题。
                self._sig.done.emit({"error": f"{type(e).__name__}: {e}"})
                return
            self._sig.done.emit(summary)

        threading.Thread(target=work, daemon=True).start()

    def _render(self, s):
        import html
        self._busy = False
        self.recheck.setEnabled(True)
        if not isinstance(s, dict) or "error" in s:
            msg = (s or {}).get("error") if isinstance(s, dict) else "没有拿到检测结果"
            self.view.setPlainText("检测没有完成：" + msg)
            self.conclusion.setStyleSheet("color:#dc2626;")
            self.conclusion.setText("自检失败：" + msg + "（可点「重新检测」再试）")
            self.win._log(f"[WARN] 环境自检未完成: {msg}")
            return
        self.win._log("[OK] 环境自检完成" if s.get("can_run")
                      else "[WARN] 环境自检完成：这台机器当前跑不动")
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
            if all(r.status == syscheck.OK for r in s["results"]) and self.isVisible() \
                    and self.auto_close:
                # 只有首次启动的自动自检才自动关闭；用户自己点的检查留在原地
                # 让他看完，也免得「刚打开就消失」导致反复点。
                self._auto_close.start(1800)
        else:
            blockers = s["blockers"] or ["无可用 Vulkan 设备"]
            self.conclusion.setStyleSheet("color:#dc2626;")
            self.conclusion.setText("结论：跑不动。原因：" + "、".join(blockers))
