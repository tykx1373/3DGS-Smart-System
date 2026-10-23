# -*- coding: utf-8 -*-
"""第 3 步：运行（阶段时间线、进度、用时、失败原因）。"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
)

import qt_theme
from qt_theme import Card, make_label
from ui_helpers import _dur


class RunPage(QWidget):
    """只管一件事：跑起来之后的进度、结果与排错。"""

    def __init__(self, win):
        super().__init__()
        self.setObjectName("runPage")
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(make_label("3 · 生成与查看", "title"))
        root.addWidget(make_label("点「开始生成」后这一页会显示进度；出错时原因与办法也在这里。",
                                  "caption"))

        # 步骤指示
        steps = QWidget()
        sl = QHBoxLayout(steps)
        sl.setContentsMargins(2, 6, 0, 2)
        self.step_labels = []
        for num, title, sub in (("1", "选择照片", "在「照片」页完成"),
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

        # 操作按钮
        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        win.rerun_btn = QPushButton("重新生成")
        win.rerun_btn.setFixedHeight(40)
        win.rerun_btn.setToolTip("用当前设置从头再跑一遍（已有恢复点时会询问是否继续）。")
        win.rerun_btn.clicked.connect(win.start_pipeline)
        bl.addWidget(win.rerun_btn)
        win.stop_btn = QPushButton("停止")
        win.stop_btn.setFixedHeight(40)
        win.stop_btn.setEnabled(False)
        win.stop_btn.clicked.connect(win.stop_pipeline)
        bl.addWidget(win.stop_btn)
        win.view_btn = QPushButton("查看 3D 模型")
        win.view_btn.setFixedHeight(40)
        win.view_btn.clicked.connect(win.open_viewer)
        bl.addWidget(win.view_btn)
        bl.addStretch(1)
        root.addWidget(brow)

        # 本次运行的固定信息：进度文字每秒都在变，而「这次是怎么跑的」不变，
        # 单独放一行，用户随时能确认照片数/分辨率/步数。
        win.ctx_lab = make_label("", "caption")
        root.addWidget(win.ctx_lab)

        # 阶段时间线：把「电脑现在在忙哪一段」摆出来。整条管线被拆成 7 段，
        # 只跑其中一部分时（只做空间定位 / 跳过评估），用不上的段会被隐藏。
        self.STAGES = ((1, "特征提取"), (2, "特征匹配"), (3, "稀疏重建"),
                       (4, "准备"), (5, "训练"), (6, "评估"), (7, "导出"))
        timeline = QHBoxLayout()
        timeline.setContentsMargins(0, 2, 0, 2)
        timeline.setSpacing(6)
        self.stage_chips = []
        for idx, name in self.STAGES:
            chip = QLabel(f"{idx} {name}")
            chip.setAlignment(Qt.AlignCenter)
            chip.setFixedHeight(26)
            self.stage_chips.append((idx, name, chip))
            timeline.addWidget(chip)
        timeline.addStretch(1)
        root.addLayout(timeline)
        self._stage_plan = [i for i, _ in self.STAGES]
        self._stage_now = 0
        self._style_stages()

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
        # 整体用时的实时读数（秒级）：阶段细节在上面，这里回答「一共多久了」
        win.meta_lab = make_label("", "caption")
        root.addWidget(win.meta_lab)

        self._run_t0 = None
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

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
        # 卡片在运行页；用户可能正停在别的页（比如去设置里改路径），
        # 出错时直接跳过来，否则这句「为什么」等于没说。
        self.win.nav.setCurrentRow(self.win.NAV.index("运行"))

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

    # ------------------------------------------------------- 阶段时间线 ----
    def set_context(self, text):
        """本次运行的固定信息（照片数/分辨率/步数），开跑时写一次。"""
        self.win.ctx_lab.setText(text)

    def set_stage_plan(self, stages):
        """本次实际要跑的阶段；没列进去的隐藏，剩下的按顺序重新编号。"""
        plan = [int(s) for s in stages]
        self._stage_plan = plan or [i for i, _ in self.STAGES]
        self._stage_now = 0
        self._style_stages()

    def set_stage(self, n):
        """核心进入第 n 段；只接受本次计划里的阶段，且只许前进。"""
        n = int(n)
        if n not in self._stage_plan or n <= self._stage_now:
            return
        self._stage_now = n
        self._style_stages()

    def _style_stages(self):
        p = qt_theme._PALETTES[qt_theme.current_scheme()]
        for idx, name, chip in self.stage_chips:
            visible = idx in self._stage_plan
            chip.setVisible(visible)
            if not visible:
                continue
            order = self._stage_plan.index(idx) + 1
            if self._stage_now and idx < self._stage_now:
                state, text = "done", f"✓ {name}"
            elif idx == self._stage_now:
                state, text = "active", f"{order} {name}"
            else:
                state, text = "pending", f"{order} {name}"
            styles = {
                "pending": f"color:{p['subtext']}; border:1px solid {p['border']};"
                           "background:transparent;",
                "active": f"color:#ffffff; background:{qt_theme.ACCENT};"
                          f"border:1px solid {qt_theme.ACCENT}; font-weight:600;",
                "done": f"color:{qt_theme.GREEN_BRIGHT};"
                        f"border:1px solid {qt_theme.GREEN_BRIGHT}; background:transparent;",
            }
            chip.setText(text)
            chip.setStyleSheet("padding:2px 10px; border-radius:13px; font-size:12px;"
                               + styles[state])

    # ------------------------------------------------------- 实时用时 ----
    def set_run_active(self, running):
        """开始/结束一轮运行：驱动整体用时读数。"""
        if running:
            self._run_t0 = time.monotonic()
            self._tick_timer.start()
            self._tick()
        else:
            self._tick_timer.stop()
            if self._run_t0 is not None:
                self._tick(final=True)
                if self.win.det_bar.value() >= 100:
                    # 正常跑完：时间线全绿，别让最后一段停在「进行中」
                    self._stage_now = 10 ** 9
                    self._style_stages()

    def _tick(self, final=False):
        if self._run_t0 is None:
            return
        elapsed = time.monotonic() - self._run_t0
        frac = self.win.det_bar.value() / 100.0
        txt = f"本次已用 {_dur(elapsed)}"
        if frac >= 1:
            txt += " · 已完成"
        elif frac > 0.02 and not final:
            # 按当前速度外推：跨阶段时会偏，所以只作为「约」的参考值
            txt += (f" · 整体 {frac * 100:.0f}%"
                    f" · 按当前速度约还需 {_dur(elapsed * (1 - frac) / frac)}")
        self.win.meta_lab.setText(txt)
