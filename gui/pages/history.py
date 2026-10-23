# -*- coding: utf-8 -*-
"""历史模型：列出 outputs/ 里训好的模型，支持打开、分享、删除。"""
import os
from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
)

from model_store import delete_history_model, scan_history_models
from qt_theme import Toast, confirm, make_label


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
        outputs = self.win.outputs_dir()
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
        outputs = self.win.outputs_dir()
        ok, err = delete_history_model(it["dir"], outputs)
        if ok:
            Toast.show_toast(self, "已删除", it["name"], "success", 2500)
            self.reload()
        else:
            Toast.show_toast(self, "删除失败", err or "未知错误", "error", 3500)
