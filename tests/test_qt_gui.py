# -*- coding: utf-8 -*-
"""quick_gui（PySide6/Fluent 界面层）测试。

未安装 PySide6/qfluentwidgets 时整体跳过（纯管线逻辑在 test_gui.py 覆盖）。
CI 用 offscreen 平台，不需要真实显示器。
"""
import json
import os
import sys
import tempfile
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
