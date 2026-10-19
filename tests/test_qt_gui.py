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
        self.win = qg.MainWindow()

    def tearDown(self):
        self.win.close()
        _app.processEvents()
        pc.CONFIG_PATH = self._orig_cfg

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
        card = self.win.train_page.fail_card
        self.assertFalse(card.isVisibleTo(self.win))
        self.win.show_failure("显存不够，分配失败", "把质量档位调低一档后重试")
        _app.processEvents()   # 同线程信号是直连的，这里只是保险
        self.assertTrue(card.isVisibleTo(self.win))
        self.assertIn("显存", self.win.train_page.fail_cause.text())
        self.assertIn("质量档位", self.win.train_page.fail_advice.text())
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
        # 工作区要叫 south-building_...，不是照目录名取到的 images_...
        self.assertIn("south-building_25imgs_gs", self.win.ws_var.get())
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
        d = os.path.join(qg.PROJECT_ROOT, "sample", "south-building", "images")
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
        self.win._train_span = (0.0, 1.0)
        self.win._set_span(0.0, 1.0)
        self.win._log("PROGRESS: 7500/15000 300.0 300.0 123456")
        self.assertEqual(got[-1][0], 0.5)
        self.assertIn("训练 50%", got[-1][1])
        self.assertNotIn("总进度", got[-1][1])
        # 与 COLMAP 同跑（训练只占后 70%）时才补一句整条管线走到哪
        self.win._train_span = (0.30, 1.0)
        self.win._set_span(*self.win._train_span)
        self.win._log("PROGRESS: 7500/15000 300.0 300.0 123456")
        self.assertEqual(got[-1][0], 0.65)
        self.assertIn("总进度 65%", got[-1][1])

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
        self.assertTrue(os.path.isfile(qg.find_app_icon()))

    def test_apply_app_identity_sets_window_icon(self):
        from PySide6.QtGui import QIcon
        _app.setWindowIcon(QIcon())                        # 先清成空图标
        qg.apply_app_identity(_app)
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
