# -*- coding: utf-8 -*-
"""quick_gui（PySide6/Fluent 界面层）测试。

未安装 PySide6/qfluentwidgets 时整体跳过（纯管线逻辑在 test_gui.py 覆盖）。
CI 用 offscreen 平台，不需要真实显示器。
"""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import pipeline_core as pc
    import quick_gui as qg
    _HAVE_QT = True
except Exception:
    _HAVE_QT = False

_app = None


@unittest.skipUnless(_HAVE_QT, "未安装 PySide6 / qfluentwidgets")
class QtGuiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _app
        _app = QApplication.instance() or QApplication(sys.argv)
        # 首次运行自检弹窗用 QTimer 触发，测试里一律关掉
        cls._orig_first = qg.syscheck.is_first_run
        qg.syscheck.is_first_run = staticmethod(lambda: False)

    @classmethod
    def tearDownClass(cls):
        qg.syscheck.is_first_run = cls._orig_first

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qtgui_")
        self.cfg_path = os.path.join(self.tmp, "cfg.json")
        self._orig_cfg = pc.CONFIG_PATH
        pc.CONFIG_PATH = self.cfg_path
        # MainWindow 会把日志写到 PROJECT_ROOT/logs/，不重定向的话测试就会往
        # 真实项目的日志里灌垃圾，而这些日志又会被「导出诊断包」收进去。
        self._orig_root_qg, self._orig_root_pc = qg.PROJECT_ROOT, pc.PROJECT_ROOT
        qg.PROJECT_ROOT = pc.PROJECT_ROOT = self.tmp
        self.win = qg.MainWindow()

    def tearDown(self):
        self.win.close()
        _app.processEvents()
        pc.CONFIG_PATH = self._orig_cfg
        qg.PROJECT_ROOT, pc.PROJECT_ROOT = self._orig_root_qg, self._orig_root_pc

    def _saved(self):
        with open(pc.CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_inherits_pipeline_core(self):
        self.assertIsInstance(self.win, pc.PipelineCore)

    # ------------------------------------------------- 配置恢复 / 持久化 ----
    def test_defaults_saved_every_option(self):
        self.win.save_options()
        saved = self._saved()
        self.assertEqual(saved["quality"], "标准")
        self.assertEqual(saved["train_steps"], 15000)
        self.assertEqual(saved["max_image_size"], 1600)
        self.assertTrue(saved["vs_mcmc"])
        self.assertTrue(saved["run_eval"])
        self.assertEqual(saved["mask_dir"], "")
        for key in ("colmap_path", "vkgs_exe", "vksplat_python",
                    "res_choice", "image_cache", "lpips_download"):
            self.assertIn(key, saved)

    def test_restored_values_survive_startup(self):
        """配置里的值必须原样恢复，不能被档位默认步数覆盖（历史回归）。"""
        self.win.close()
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump({"quality": "高质量", "train_steps": 7777,
                       "max_image_size": 2048, "res_choice": "1/4（images_4）",
                       "lpips_download": True}, f, ensure_ascii=True)
        w = qg.MainWindow()
        try:
            self.assertEqual(w.quality_var.get(), "高质量")
            self.assertEqual(w.vs_steps_var.get(), 7777)
            self.assertEqual(w.max_img_var.get(), 2048)
            self.assertEqual(w.res_var.get(), "1/4（images_4）")
            self.assertTrue(w.lpips_dl_var.get())
            self.assertTrue(w.quality_hint.text())
        finally:
            w.close()

    def test_switching_quality_applies_default_steps(self):
        for rb in self.win.quality_group.buttons():
            if rb.text() == "快速":
                rb.setChecked(True)
                break
        _app.processEvents()
        self.assertEqual(self.win.vs_steps_var.get(), pc.QUALITY_PRESETS["快速"][0])
        self.assertEqual(self.win.steps_spin.value(), 5000)

    def test_widget_changes_written_back(self):
        self.win.maximg_spin.setValue(1200)
        self.win.steps_spin.setValue(9000)
        self.win.mask_edit.setText(r"D:\tmp\masks  ")
        self.win.mcmc_chk.setChecked(False)
        self.win.eval_chk.setChecked(False)
        _app.processEvents()
        self.win.save_options()
        saved = self._saved()
        self.assertEqual(saved["max_image_size"], 1200)
        self.assertEqual(saved["train_steps"], 9000)
        self.assertEqual(saved["mask_dir"], r"D:\tmp\masks")  # 尾随空格 strip
        self.assertFalse(saved["vs_mcmc"])
        self.assertFalse(saved["run_eval"])

    def test_config_is_ascii_encoded(self):
        """ensure_ascii=True：中文路径也必须能按 ascii 读回。"""
        self.win.mask_edit.setText(os.path.join(self.tmp, "遮罩"))
        self.win.save_options()
        with open(pc.CONFIG_PATH, "rb") as f:
            f.read().decode("ascii")

    # ----------------------------------------------------------- 历史页 ----
    def test_history_page_lists_only_models_with_ply(self):
        out_root = tempfile.mkdtemp(prefix="qtout_")
        outputs = os.path.join(out_root, "outputs")
        good = os.path.join(outputs, "vksplat_15000steps_standard")
        os.makedirs(good)
        with open(os.path.join(good, "splat.ply"), "wb") as f:
            f.write(b"x" * 2048)
        with open(os.path.join(good, "eval.json"), "w", encoding="utf-8") as f:
            json.dump({"mean": {"psnr": 26.0, "ssim": 0.85}}, f)
        dead = os.path.join(outputs, "20260101_000000_failed")
        os.makedirs(dead)  # 只有目录，没 PLY，不该出现
        orig_root = qg.PROJECT_ROOT
        qg.PROJECT_ROOT = out_root
        try:
            self.win.history_page.reload()
            self.assertEqual(self.win.history_page.table.rowCount(), 1)
            # 第 1 列时间、第 2 列模型名、第 4 列 PSNR
            self.assertEqual(self.win.history_page.table.item(0, 1).text(),
                             "vksplat_15000steps_standard")
            self.assertEqual(self.win.history_page.table.item(0, 4).text(), "26.00")
        finally:
            qg.PROJECT_ROOT = orig_root


    def test_history_share_uses_dir_named_splat(self):
        """「发给别人」要按目录名指定分享版（免得变成 splat.splat），
        并把请求转给 share_splat；没转过的模型大小列显示「—」。"""
        out_root = tempfile.mkdtemp(prefix="qtout_")
        outputs = os.path.join(out_root, "outputs")
        d = os.path.join(outputs, "vksplat_5000steps_fast")
        os.makedirs(d)
        with open(os.path.join(d, "splat.ply"), "wb") as f:
            f.write(b"x" * 2048)
        calls = []
        self.win.share_splat = lambda ply, splat_path=None: calls.append((ply, splat_path))
        orig_root = qg.PROJECT_ROOT
        qg.PROJECT_ROOT = out_root
        try:
            page = self.win.history_page
            page.reload()
            self.assertEqual(page.table.item(0, 8).text(), "—")
            page.table.selectRow(0)
            page.share_selected()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1],
                             os.path.join(d, "vksplat_5000steps_fast.splat"))
            with open(calls[0][1], "wb") as f:
                f.write(b"\x00" * 32)
            page.reload()
            self.assertEqual(page.table.item(0, 8).text(), "0.0")
        finally:
            qg.PROJECT_ROOT = orig_root

    def test_eval_share_button_follows_host_support(self):
        """完成弹窗只在宿主支持分享时才出现「准备分享文件」。"""
        mean = {"psnr": 26.0, "ssim": 0.85}
        with_share = qg.EvalDialog(mean, on_view=lambda: None, on_share=lambda: None)
        texts = [b.text() for b in with_share.findChildren(qg.QPushButton)]
        self.assertTrue(any("分享" in t for t in texts))
        without = qg.EvalDialog(mean, on_view=lambda: None)
        texts2 = [b.text() for b in without.findChildren(qg.QPushButton)]
        self.assertFalse(any("分享" in t for t in texts2))

    def test_failure_card_shows_on_panel_and_resets_on_next_run(self):
        """失败卡片要真的出现在训练页，且下一轮开始时收起。"""
        # 失败只会发生在跑起来之后；先让第 1 步有照片，运行页才进得去
        d = tempfile.mkdtemp(prefix="photo_")
        open(os.path.join(d, "p.jpg"), "w").close()
        self.win.img_edit.setText(d)
        card = self.win.run_page.fail_card
        self.assertFalse(card.isVisibleTo(self.win))
        self.win.show_failure("显存不够，分配失败", "把质量档位调低一档后重试")
        _app.processEvents()   # 同线程信号是直连的，这里只是保险
        self.assertTrue(card.isVisibleTo(self.win))
        self.assertIn("显存", self.win.run_page.fail_cause.text())
        self.assertIn("质量档位", self.win.run_page.fail_advice.text())
        # 新一轮运行：卡片收起，但求助按钮不能被禁用扫描误伤
        self.win._apply_running(True, True)
        self.assertFalse(card.isVisibleTo(self.win))
        self.assertTrue(self.win.diag_btn.isEnabled())

    def test_show_log_page_jumps_to_log_tab(self):
        self.win.show_log_page()
        self.assertEqual(self.win.nav.currentRow(), self.win.NAV.index("日志"))

    def test_version_visible_in_title_and_sidebar(self):
        """版本号要能在界面上一眼看到（标题栏 + 侧栏品牌区），不必去翻设置或日志。"""
        from app_version import APP_VERSION
        self.assertIn(f"v{APP_VERSION}", self.win.windowTitle())
        labels = [l.text() for l in self.win.findChildren(qg.QLabel)]
        self.assertTrue(any(APP_VERSION in t for t in labels),
                        "侧栏品牌区应显示版本号")
        self.assertTrue(any("3DGS 快速管线" in t for t in labels))

    def test_capture_dialog_answers_the_caller(self):
        """采集质量弹窗：用户点「去补拍」时 ask_capture_report 必须返回 False，
        且文案里真的点名了失败的照片。"""
        report = {"level": "bad", "rate": 0.33, "n_total": 3, "n_registered": 1,
                  "missing": ["img001.jpg", "img002.jpg"], "blurry": []}
        seen = []
        orig = qg.confirm
        qg.confirm = lambda parent, title, text, yes, no: (
            seen.append((title, text, yes, no)), False)[1]
        try:
            self.assertFalse(self.win.ask_capture_report(report))
        finally:
            qg.confirm = orig
        self.assertEqual(seen[0][0], "照片检查结果")
        self.assertIn("img001.jpg", seen[0][1])
        self.assertEqual(seen[0][2:4], ("先训练看看", "去补拍"))

    def test_capture_dialog_continue_choice_trains(self):
        report = {"level": "warn", "rate": 0.8, "n_total": 5, "n_registered": 4,
                  "missing": ["img005.jpg"], "blurry": []}
        orig = qg.confirm
        qg.confirm = lambda *a, **k: True
        try:
            self.assertTrue(self.win.ask_capture_report(report))
        finally:
            qg.confirm = orig

    def test_sample_entry_selects_dataset_and_workspace(self):
        """示例入口：选中内置照片、按数据集目录命名工作区，然后交给原流程开跑。"""
        root = tempfile.mkdtemp(prefix="sample_")
        imgs = os.path.join(root, "sample", "south-building", "images")
        os.makedirs(imgs)
        for i in range(25):
            open(os.path.join(imgs, "p%02d.jpg" % i), "w").close()
        started = []
        self.win.start_pipeline = lambda: started.append(True)
        orig = pc.PROJECT_ROOT
        pc.PROJECT_ROOT = root
        try:
            self.assertTrue(self.win.sample_ready())
            self.win.use_sample()
        finally:
            pc.PROJECT_ROOT = orig
        self.assertEqual(started, [True])
        self.assertTrue(self.win.img_var.get().endswith(
            os.path.join("sample", "south-building", "images")))
        # 工作区要叫 south-building-1600_...，不是照目录名取到的 images_...
        # （名字带长边像素：示例图降过分辨率，同名会复用旧内参的工作区）
        self.assertIn("south-building-1600_25imgs_gs", self.win.ws_var.get())
        self.assertTrue(self.win._from_sample)

    def test_use_sample_without_dataset_does_not_start(self):
        """没装示例时不能给一个会点了没反应的按钮。"""
        orig = pc.PROJECT_ROOT
        pc.PROJECT_ROOT = tempfile.mkdtemp(prefix="nosample_")
        started = []
        self.win.start_pipeline = lambda: started.append(True)
        try:
            self.assertFalse(self.win.sample_ready())
            self.win.use_sample()
        finally:
            pc.PROJECT_ROOT = orig
        self.assertEqual(started, [])
        self.assertFalse(self.win.sample_btn.isVisibleTo(self.win))

    def test_precheck_label_and_stale_result_dropped(self):
        """预检结论显示在照片卡片下方；换文件夹后旧结论不能覆盖新的。

        序号是 start_photo_precheck 递增的，所以测试也照这个顺序设。
        """
        self.win._precheck_seq = 1
        self.win._on_precheck("128 张照片清晰度都正常，可以开始生成。", "ok", 1)
        self.assertIn("清晰度都正常", self.win.photo_note.text())
        self.assertTrue(self.win.photo_note.isVisibleTo(self.win))
        # 序号不是当前最新的（用户已经换了目录）→ 丢弃
        self.win._precheck_seq = 2
        self.win._on_precheck("过期结论", "warn", 1)
        self.assertNotIn("过期", self.win.photo_note.text())

    def test_photo_precheck_runs_in_background(self):
        """真跑一遍本地预检：结果回来并显示。"""
        d = os.path.join(ROOT, "sample", "south-building", "images")
        if not os.path.isdir(d):
            self.skipTest("本机没有示例数据集")
        names = [f for f in os.listdir(d) if f.lower().endswith(".JPG")]
        self.win.start_photo_precheck(d, len(names))
        deadline = time.time() + 30
        while time.time() < deadline:
            _app.processEvents()
            if "正在检查" not in self.win.photo_note.text():
                break
            time.sleep(0.1)
        self.assertIn("张", self.win.photo_note.text())
        self.assertNotIn("正在检查", self.win.photo_note.text())

    def test_train_progress_text_avoids_duplicate_total(self):
        """进度文案随分段变化：只训练时不必重复「总进度」。"""
        got = []
        self.win.sig.progress.connect(lambda f, d: got.append((round(f, 3), d)))
        self.win._ips_recorded = True        # 别让测试写进耗时统计
        self.win.progress.train_span = (0.0, 1.0)
        self.win._set_span(0.0, 1.0)
        self.win._log("PROGRESS: 7500/15000 300.0 300.0 123456")
        self.assertEqual(got[-1][0], 0.5)
        self.assertIn("训练 50%", got[-1][1])
        self.assertNotIn("总进度", got[-1][1])
        # 与 COLMAP 同跑（训练只占后 70%）时才补一句整条管线走到哪
        self.win.progress.train_span = (0.30, 1.0)
        self.win._set_span(*self.win.progress.train_span)
        self.win._log("PROGRESS: 7500/15000 300.0 300.0 123456")
        self.assertEqual(got[-1][0], 0.65)
        self.assertIn("总进度 65%", got[-1][1])

    def test_train_progress_shows_vram(self):
        """显存占用要出现在进度文案里；拿不到可信总量时只显示占用值。"""
        got = []
        self.win.sig.progress.connect(lambda f, d: got.append(d))
        self.win._ips_recorded = True
        self.win._set_span(0.0, 1.0)
        # 能给出总量（独显）→ 显示 X/Y
        self.win._vram_total_mb = 8192
        self.win._log("PROGRESS: 3000/15000 120.0 500.0 200000 3276")
        self.assertIn("模型显存 3.2/8.0 GB", got[-1])
        # 核显/读不到总量 → 只给占用值，避免分子分母口径不一致
        self.win._vram_total_mb = None
        self.win._log("PROGRESS: 3000/15000 120.0 500.0 200000 3276")
        self.assertIn("模型显存 3.2 GB", got[-1])
        self.assertNotIn("/", got[-1].split("模型显存")[-1])
        # 旧版训练器不给这一项 → 文案里不该冒出「显存 None」
        self.win._log("PROGRESS: 3000/15000 120.0 500.0 200000")
        self.assertNotIn("显存", got[-1])

    def test_log_file_strips_prefix_and_keeps_semantic_level(self):
        """文件里不该出现「[INFO] [FAIL]」这种自相矛盾的行：级别归 logger，
        正文只留内容。界面仍显示带前缀的原文（色盲用户靠前缀分级）。"""
        import logging
        from unittest import mock
        with mock.patch.object(self.win.logger, "log") as m:
            self.win._log("[FAIL] 图片文件夹无效。")
        level, msg = m.call_args[0]
        self.assertEqual(level, logging.ERROR)
        self.assertEqual(msg, "图片文件夹无效。")

        got = []
        self.win.sig.log.connect(lambda t, lv: got.append((t, lv)))
        with mock.patch.object(self.win.logger, "log"):
            self.win._log("[WARN] 注册率 60%")
        self.assertEqual(got[-1], ("[WARN] 注册率 60%", "warn"))

    def test_tqdm_is_bucketed_and_training_is_skipped(self):
        """tqdm 每 10% 才写一行；训练阶段由 PROGRESS 驱动，完全不写。"""
        from unittest import mock
        calls = []
        with mock.patch.object(self.win.logger, "info", side_effect=lambda m: calls.append(m)):
            for pct in (0, 3, 6, 9, 10, 15, 20):
                self.win._log(f"Running eval: {pct:3d}%|## | {pct}/16 [00:01<00:10, 2.0s/it]")
            self.win._log("Training:  50%|####| 2500/5000 [00:20<00:20, 100.0it/s]")
        self.assertEqual(len(calls), 3)          # 0% / 10% / 20% 各一行
        self.assertFalse(any("Training" in c for c in calls))

    def test_colmap_per_image_lines_stay_out_of_ui(self):
        """逐张配准行只进文件：进度条已经在逐张推进，界面不该被它刷屏。"""
        from unittest import mock
        got = []
        self.win.sig.log.connect(lambda t, lv: got.append(t))
        with mock.patch.object(self.win.logger, "info") as m:
            self.win._log("I20261022 21:06:41.3 35616 incremental_pipeline.cc:620]"
                          " Registering image #12 (num_reg_frames=123)")
            self.win._log("I20261022 21:06:41.3 35616 incremental_pipeline.cc:623]"
                          " => Image sees 796 / 1919 points")
        self.assertEqual(got, [])                # 界面一条都不显示
        self.assertEqual(m.call_count, 2)        # 文件仍保留原文，排查要用

    def test_feature_detail_lines_only_reach_the_file(self):
        """特征提取每张图 6 行明细：界面只留每 10 张一个节点。"""
        from unittest import mock
        got = []
        self.win.sig.log.connect(lambda t, lv: got.append(t))
        with mock.patch.object(self.win.logger, "info"):
            self.win._log("I20261022 21:03:17.6 21584 feature_extraction.cc:273]"
                          "   Name:            P1180141.JPG")
            self.win._log("I20261022 21:03:17.6 21584 feature_extraction.cc:294]"
                          "   Features:        8728 (SIFT)")
            for n in (1, 5, 10, 17, 128):
                self.win._log(f"I20261022 21:03:17.6 21584 feature_extraction.cc:270]"
                              f" Processed file [{n}/128]")
        # 1/5/17 不显示；10（整十）与 128（最后一张）各显示一次
        self.assertEqual(len(got), 2)
        self.assertIn("[10/128]", got[0])
        self.assertIn("[128/128]", got[1])

    def test_log_view_caps_block_count(self):
        """日志页有行数上限，长时间训练不会把内存堆爆。"""
        self.assertEqual(self.win.log_page.view.document().maximumBlockCount(), 5000)

    def test_train_parameters_live_on_one_page(self):
        """训练参数必须集中在「训练设置」页，不必为改分辨率跑去设置页。"""
        page = self.win.train_settings_page
        for w in (self.win.steps_spin, self.win.mcmc_chk, self.win.eval_chk,
                  self.win.lpips_chk, self.win.exposure_chk, self.win.res_combo,
                  self.win.cache_combo, self.win.maximg_spin, self.win.mask_edit,
                  self.win.ws_edit):
            self.assertTrue(page.isAncestorOf(w), "该控件不在训练设置页")
        # 设置页只留工具路径
        self.assertFalse(self.win.settings_page.isAncestorOf(self.win.res_combo))
        # 照片相关只在照片页
        self.assertTrue(self.win.photo_page.isAncestorOf(self.win.img_edit))
        self.assertFalse(page.isAncestorOf(self.win.img_edit))

    def test_start_switches_to_run_page(self):
        """点开始后自动切到运行页：进度与排错都在那里。"""
        from unittest import mock
        d = tempfile.mkdtemp(prefix="photo_")
        open(os.path.join(d, "p.jpg"), "w").close()
        self.win.img_edit.setText(d)
        self.win.nav.setCurrentRow(self.win.NAV.index("训练设置"))
        with mock.patch.object(self.win, "start") as m:
            self.win.start_pipeline()
        self.assertEqual(self.win.nav.currentRow(), self.win.NAV.index("运行"))
        m.assert_called_once()

    def test_next_button_requires_photos(self):
        """没选到可用照片时「下一步」不可点。"""
        self.assertFalse(self.win.next_btn.isEnabled())
        d = tempfile.mkdtemp(prefix="photo_")
        open(os.path.join(d, "p.jpg"), "w").close()
        self.win.img_edit.setText(d)
        _app.processEvents()
        self.assertTrue(self.win.next_btn.isEnabled())
        self.win.img_edit.setText("")
        _app.processEvents()
        self.assertFalse(self.win.next_btn.isEnabled())

    def test_nav_blocks_later_steps_without_photos(self):
        """侧栏也按顺序走：没照片进不了训练设置/运行页，但设置页随时能进。"""
        toasts = []
        orig = qg.Toast.show_toast
        qg.Toast.show_toast = staticmethod(
            lambda parent, title, msg, kind, ms: toasts.append(title))
        try:
            self.win.nav.setCurrentRow(self.win.NAV.index("训练设置"))
            _app.processEvents()
            self.assertEqual(self.win.nav.currentRow(), self.win.NAV.index("照片"))
            self.assertEqual(self.win.stack.currentIndex(), self.win.NAV.index("照片"))
            self.assertIn("先选照片", toasts)
            # 设置页不受影响
            self.win.nav.setCurrentRow(self.win.NAV.index("设置"))
            self.assertEqual(self.win.stack.currentIndex(), self.win.NAV.index("设置"))
            # 选好照片后，训练设置可进
            d = tempfile.mkdtemp(prefix="photo_")
            open(os.path.join(d, "p.jpg"), "w").close()
            self.win.img_edit.setText(d)
            self.win.nav.setCurrentRow(self.win.NAV.index("照片"))
            self.win.nav.setCurrentRow(self.win.NAV.index("训练设置"))
            self.assertEqual(self.win.stack.currentIndex(),
                             self.win.NAV.index("训练设置"))
        finally:
            qg.Toast.show_toast = orig

    def test_nav_highlight_returns_to_photo_after_real_click(self):
        """真实点击被拦时，侧栏高亮也要退回照片页（曾出现内容回去了、高亮没回）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        toasts = []
        orig = qg.Toast.show_toast
        qg.Toast.show_toast = staticmethod(lambda *a, **k: toasts.append(a[1]))
        try:
            self.win.show()
            _app.processEvents()
            item = self.win.nav.item(self.win.NAV.index("运行"))
            rect = self.win.nav.visualItemRect(item)
            QTest.mouseClick(self.win.nav.viewport(), Qt.LeftButton,
                             pos=rect.center())
            for _ in range(5):
                _app.processEvents()
            self.assertEqual(self.win.nav.currentRow(), self.win.NAV.index("照片"))
            self.assertEqual(self.win.stack.currentIndex(), self.win.NAV.index("照片"))
            self.assertIn("先选照片", "".join(toasts))
        finally:
            qg.Toast.show_toast = orig

    def test_start_without_photos_stays_on_photo_page(self):
        from unittest import mock
        toasts = []
        orig = qg.Toast.show_toast
        qg.Toast.show_toast = staticmethod(
            lambda parent, title, msg, kind, ms: toasts.append(title))
        try:
            with mock.patch.object(self.win, "start") as m:
                self.win.start_pipeline()
            m.assert_not_called()
        finally:
            qg.Toast.show_toast = orig
        self.assertEqual(self.win.nav.currentRow(), self.win.NAV.index("照片"))
        self.assertIn("还没有照片", toasts)

    def test_syscheck_entry_belongs_to_the_first_step(self):
        """环境自检是开跑前的预备动作：在照片页，不与运行页的控制按钮混在一起。"""
        self.assertTrue(self.win.photo_page.isAncestorOf(self.win.check_btn))
        self.assertFalse(self.win.run_page.isAncestorOf(self.win.check_btn))

    def _wait_syscheck(self, dlg, timeout=6.0):
        deadline = time.time() + timeout
        while dlg._busy and time.time() < deadline:
            _app.processEvents()
            time.sleep(0.02)
        _app.processEvents()
        self.assertFalse(dlg._busy, "自检线程没有在超时内结束")

    def test_syscheck_reuses_one_dialog_and_one_detection(self):
        """连点自检只允许一个窗口、一个检测线程（之前会叠出多个）。"""
        from unittest import mock
        started = []

        def slow_summarize(**kwargs):
            started.append(1)
            time.sleep(0.6)
            return {"results": [], "can_run": False, "blockers": ["测试"],
                    "device": None, "is_integrated": None, "laptop": False,
                    "measured": False, "est_train_sec": None,
                    "est_colmap_sec": None, "est_total_sec": None}

        with mock.patch.object(qg.syscheck, "summarize", slow_summarize), \
                mock.patch.object(qg.syscheck, "record_check", lambda: None):
            self.win.open_syscheck()
            dlg = self.win._syscheck_dlg
            self.assertIsNotNone(dlg)
            self.assertTrue(dlg.isVisible())
            self.win.open_syscheck()      # 窗口已打开：只前置，不再新建
            self.assertIs(self.win._syscheck_dlg, dlg)
            dlg.detect()                  # 检测进行中：忽略，不叠线程
            self.assertEqual(len(started), 1)
            self._wait_syscheck(dlg)
        dlg.close()

    def test_syscheck_thread_failure_is_reported(self):
        """检测线程抛异常也要有结果：不能把按钮永远卡在「检测中」。"""
        from unittest import mock

        def boom(**kwargs):
            raise RuntimeError("枚举炸了")

        with mock.patch.object(qg.syscheck, "summarize", boom):
            self.win.open_syscheck()
            dlg = self.win._syscheck_dlg
            self._wait_syscheck(dlg)
        self.assertIn("自检失败", dlg.conclusion.text())
        self.assertIn("枚举炸了", dlg.conclusion.text())
        self.assertTrue(dlg.recheck.isEnabled())
        dlg.close()

    def test_stage_timeline_hides_unused_stages_and_renumbers(self):
        """只训练且不做评估时，时间线只留 准备/训练/导出，并重新编号。"""
        page = self.win.run_page
        chips = {idx: chip for idx, _name, chip in page.stage_chips}
        page.set_stage_plan([4, 5, 7])
        for idx in (1, 2, 3, 6):
            self.assertTrue(chips[idx].isHidden(), f"第 {idx} 段应隐藏")
        self.assertEqual(chips[4].text(), "1 准备")
        self.assertEqual(chips[5].text(), "2 训练")
        self.assertEqual(chips[7].text(), "3 导出")
        # 走到训练：准备打勾，训练高亮；倒退和计划外的段都不接受
        page.set_stage(5)
        self.assertEqual(chips[4].text(), "✓ 准备")
        self.assertIn(qg.qt_theme.ACCENT, chips[5].styleSheet())
        page.set_stage(4)
        page.set_stage(1)
        self.assertEqual(chips[5].text(), "2 训练")
        self.assertIn(qg.qt_theme.ACCENT, chips[5].styleSheet())

    def test_run_context_lists_photos_resolution_and_steps(self):
        """开跑时把「这次是怎么跑的」摆出来，免得用户回训练设置页核对。"""
        d = tempfile.mkdtemp(prefix="ctx_")
        for i in range(3):
            open(os.path.join(d, "p%d.jpg" % i), "w").close()
        self.win.img_edit.setText(d)
        self.win.steps_spin.setValue(8000)
        self.win._sync_edits_to_vars()
        self.win._apply_running(True, False)
        txt = self.win.ctx_lab.text()
        self.assertIn("3 张照片", txt)
        self.assertIn("8000 步", txt)
        self.assertIn("分辨率", txt)

    def test_meta_line_reports_elapsed_and_estimate(self):
        """秒级的整体用时：只靠阶段文字看不出「一共跑了多久」。"""
        self.win.det_bar.setValue(50)
        self.win.run_page._run_t0 = time.monotonic() - 65
        self.win.run_page._tick()
        txt = self.win.meta_lab.text()
        self.assertIn("1 分 05 秒", txt)
        self.assertIn("整体 50%", txt)
        self.assertIn("约还需", txt)

    def test_toast_fades_in_and_cleans_up_after_fade_out(self):
        """提示条要淡入（从透明开始），停留结束后淡出并回收，不留空壳。"""
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget
        qg.Toast.show_toast(self.win, "标题", "内容", "info", 150)
        holders = [w for w in self.win.findChildren(QWidget)
                   if isinstance(w.graphicsEffect(), QGraphicsOpacityEffect)]
        self.assertEqual(len(holders), 1)
        self.assertLess(holders[0].graphicsEffect().opacity(), 0.5,
                        "淡入应从接近透明开始，不能一出现就满不透明")
        QTest.qWait(800)
        holders = [w for w in self.win.findChildren(QWidget)
                   if isinstance(w.graphicsEffect(), QGraphicsOpacityEffect)]
        self.assertEqual(holders, [], "淡出结束后应把提示条回收")

    def _make_reusable_workspace(self, n=3):
        root = tempfile.mkdtemp(prefix="reuse_")
        imgs = os.path.join(root, "photos")
        ws = os.path.join(root, "ws")
        os.makedirs(imgs)
        os.makedirs(os.path.join(ws, "sparse", "0"))
        for name in ("cameras.bin", "images.bin", "points3D.bin"):
            open(os.path.join(ws, "sparse", "0", name), "wb").close()
        for i in range(n):
            with open(os.path.join(imgs, "p%d.jpg" % i), "wb") as f:
                f.write(b"x")
        pc.write_colmap_meta(ws, imgs, 1600)
        return imgs, ws

    def test_start_asks_before_reusing_colmap(self):
        """照片/参数没变时先问一句；选复用则跳过 COLMAP，时间线也相应收起。"""
        imgs, ws = self._make_reusable_workspace()
        self.win.img_edit.setText(imgs)
        self.win.ws_edit.setText(ws)
        self.win._sync_edits_to_vars()
        seen, cont = [], []
        orig_confirm, orig_thread = qg.confirm, self.win.pipeline_thread
        qg.confirm = lambda parent, title, text, yes, no: (
            seen.append((title, text, yes)), True)[1]
        self.win.pipeline_thread = lambda **kw: None
        self.win.ask_resume = lambda: None
        self.win.ask_continue = lambda do: (cont.append(do), True)[1]
        try:
            self.win.start(True, True)
        finally:
            qg.confirm = orig_confirm
            self.win.pipeline_thread = orig_thread
            self.win.set_running(False, True)
        self.assertEqual(len(seen), 1, "没有询问复用")
        self.assertIn("复用上次的空间定位", seen[0][0])
        self.assertIn("3 张照片", seen[0][1])
        self.assertEqual(seen[0][2], "复用（快）")
        self.assertEqual(cont, [False], "复用后的耗时预估不应再算 COLMAP")
        self.assertTrue(self.win.progress.reuse)
        self.assertIn("复用上次定位", self.win.ctx_lab.text())
        chips = {idx: chip for idx, _name, chip in self.win.run_page.stage_chips}
        self.assertTrue(chips[1].isHidden(), "复用时不该再显示 COLMAP 三段")
        self.assertFalse(chips[4].isHidden())

    def test_colmap_only_entry_forces_recompute(self):
        """「只用 COLMAP」入口的语义是重做定位，不能顺手复用旧结果。"""
        from unittest import mock
        with mock.patch.object(self.win, "start") as m:
            self.win.start_colmap_only()
        m.assert_called_once_with(True, False, force_colmap=True)

    def test_completion_dialog_shows_training_settings_when_eval_off(self):
        """评测关掉后训练完成弹窗仍要出现，并展示这次是怎么跑的。"""
        dlg = qg.EvalDialog(None, on_view=lambda: None,
                            stats={"quality": "快速", "steps": 5000,
                                   "res_label": "原分辨率", "n_imgs": 128,
                                   "mcmc": False, "seconds": 80.0,
                                   "num_splats": 123456, "peak_vram_gb": 0.43})
        texts = "\n".join(lab.text() for lab in dlg.findChildren(qg.QLabel))
        for want in ("5,000 步", "原分辨率", "128 张", "1 分 20 秒",
                     "123,456 个", "0.43 GB", "没有质量评估分数"):
            self.assertIn(want, texts)
        dlg.close()

    def _prepare_trained_workspace(self):
        imgs, ws = self._make_reusable_workspace()
        # 这组测试只关心「训练过没有」；把 COLMAP 复用记录去掉，免得再弹复用窗
        meta = os.path.join(ws, pc.COLMAP_META_FILE)
        if os.path.isfile(meta):
            os.remove(meta)
        ply = os.path.join(ws, "splat.ply")
        open(ply, "wb").close()
        self.win.img_edit.setText(imgs)
        self.win.ws_edit.setText(ws)
        self.win._sync_edits_to_vars()
        pc.write_train_config(ws, imgs, self.win._train_settings(), ply,
                              model_dir=os.path.join(ws, "out"))
        return imgs, ws, ply

    def test_start_warns_when_same_settings_already_trained(self):
        """照片和设置都一致时先提醒；选取消则不启动任何工作线程。"""
        self._prepare_trained_workspace()
        asked, ran = [], []
        self.win.ask_retrain_existing = lambda w, cfg: (asked.append(cfg), "cancel")[1]
        self.win.ask_resume = lambda: None
        self.win.ask_continue = lambda do: True
        self.win.pipeline_thread = lambda **kw: ran.append(kw)
        self.win.start(True, True)
        self.assertEqual(len(asked), 1)
        self.assertIn("settings", asked[0])
        self.assertEqual(ran, [])

    def test_no_retrain_prompt_after_settings_change(self):
        self._prepare_trained_workspace()
        self.win.steps_spin.setValue(8000)   # 设置变了，不该再提示「训练过」
        asked, cont = [], []
        self.win.ask_retrain_existing = lambda *a: asked.append(1) or "cancel"
        self.win.ask_resume = lambda: None
        self.win.ask_continue = lambda do: (cont.append(do), False)[1]
        self.win.start(True, True)
        self.assertEqual(asked, [])
        self.assertEqual(cont, [True], "应继续走正常的耗时确认流程")

    def test_resuming_does_not_warn_about_duplicate_training(self):
        """有未完成训练恢复点时应走续训，不该说「已经训练过」。"""
        _imgs, ws, _ply = self._prepare_trained_workspace()
        open(os.path.join(ws, "checkpoint.ply"), "wb").close()
        with open(os.path.join(ws, "checkpoint.ply.step"), "w", encoding="utf-8") as f:
            f.write("1000")
        asked = []
        self.win.ask_retrain_existing = lambda *a: asked.append(1) or "cancel"
        self.win.ask_resume = lambda: None
        self.win.ask_continue = lambda do: False
        self.win.start(True, True)
        self.assertEqual(asked, [])

    def test_share_splat_actually_generates_file(self):
        """端到端跑 share_splat 本身。

        之前的测试把 win.share_splat 整个换成假函数，结果它一调用就
        UnboundLocalError（嵌套函数里给 target 赋值，使它变成局部变量）
        也没被抓到 —— 这条就是钉住那个真实路径。
        """
        import struct
        root = tempfile.mkdtemp(prefix="share_")
        ply = os.path.join(root, "vksplat_5000steps_fast.ply")
        props = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                 "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
        with open(ply, "wb") as f:
            f.write(("ply\nformat binary_little_endian 1.0\nelement vertex 2\n"
                     + "".join("property float %s\n" % p for p in props)
                     + "end_header\n").encode("ascii"))
            for _ in range(2):
                f.write(struct.pack("<14f", 1, 2, 3, .5, .5, .5, 2, -2, -2, -2, 1, 0, 0, 0))
        toasts = []
        orig_toast, orig_popen = qg.Toast.show_toast, qg.subprocess.Popen
        qg.Toast.show_toast = staticmethod(lambda parent, title, msg, kind, ms: toasts.append((title, msg)))
        qg.subprocess.Popen = lambda *a, **k: None
        called = {"n": 0}

        def fake_confirm(*a, **k):
            called["n"] += 1
            return True

        orig_confirm = qg.confirm
        qg.confirm = fake_confirm
        try:
            self.win.share_splat(ply)
            deadline = time.time() + 20
            while time.time() < deadline and not called["n"]:
                _app.processEvents()
                time.sleep(0.02)
            self.assertEqual(called["n"], 1, "分享成功的提示没出现")
            # 必须在这里把队列里的事件跑完再恢复 confirm：share_done 是排队信号，
            # 若留到 tearDown 才投递，就会弹出真模态框把整个测试会话卡死。
            for _ in range(5):
                _app.processEvents()
        finally:
            qg.Toast.show_toast, qg.subprocess.Popen = orig_toast, orig_popen
            qg.confirm = orig_confirm
        self.assertEqual([t for t in toasts if t[0] == "分享失败"], [])
        self.assertTrue(os.path.isfile(os.path.join(root, "vksplat_5000steps_fast.splat")))

    def test_find_app_icon_prefers_installed_layout(self):
        root = tempfile.mkdtemp(prefix="icon_")
        self.assertIsNone(qg.find_app_icon(root))          # 哪儿都没有
        os.makedirs(os.path.join(root, "installer"))
        dev = os.path.join(root, "installer", "app.ico")
        open(dev, "wb").close()
        self.assertEqual(qg.find_app_icon(root), dev)      # 开发树
        os.makedirs(os.path.join(root, "gui"))
        shipped = os.path.join(root, "gui", "app.ico")
        open(shipped, "wb").close()
        self.assertEqual(qg.find_app_icon(root), shipped)  # 装机版优先读 gui/

    def test_repo_has_icon_for_dev_tree(self):
        """开发树里图标必须存在，否则本地跑根本看不到任务栏图标问题。"""
        self.assertTrue(os.path.isfile(qg.find_app_icon(ROOT)))

    def test_apply_app_identity_sets_window_icon(self):
        from PySide6.QtGui import QIcon
        _app.setWindowIcon(QIcon())                        # 先清成空图标
        qg.apply_app_identity(_app, ROOT)
        self.assertFalse(_app.windowIcon().isNull())

    def test_picking_images_prefills_workspace_name(self):
        root = tempfile.mkdtemp(prefix="wsfill_")
        imgs = os.path.join(root, "garden")
        os.makedirs(imgs)
        for n in ("a.jpg", "b.png", "c.bmp"):
            open(os.path.join(imgs, n), "w").close()
        orig = pc.PROJECT_ROOT
        pc.PROJECT_ROOT = root
        try:
            self.win._fill_workspace_from_images(imgs, 3)
            self.assertEqual(self.win.ws_var.get(),
                             os.path.join("workspaces", "garden_3imgs_gs").replace("/", os.sep))
        finally:
            pc.PROJECT_ROOT = orig


if __name__ == "__main__":
    unittest.main()
