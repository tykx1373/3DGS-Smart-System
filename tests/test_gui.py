# -*- coding: utf-8 -*-
"""pipeline_core 里可离线测试的部分：正则解析、配置读取、文件探测。

不需要 GPU、网络和 Qt 界面。界面层（PySide6）的测试见 test_qt_gui.py。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))

import pipeline_core as q  # noqa: E402

# 测试里沿用旧名 QuickSplatApp 的构造方式（bare 方法测试），
# 现在管线方法都在 PipelineCore 上。
q.QuickSplatApp = q.PipelineCore


class TestProgressParsing(unittest.TestCase):
    # 本轮真实日志：tqdm 用 \r 刷新，把 PROGRESS 标记挤到了行中间，
    # 进度条因此完全不动。
    NOISY = ("Training:   3%|██  | 95/3000 [00:01<00:42, 67.75it/s]"
             "PROGRESS: 100/3000 1.5 43.5 79296")

    def test_marker_found_when_not_at_line_start(self):
        marks = q._PROGRESS_RE.findall(self.NOISY)
        self.assertEqual(marks[-1], ("100", "3000", "1.5", "43.5", "79296"))

    def test_plain_marker(self):
        marks = q._PROGRESS_RE.findall("PROGRESS: 500/5000 12.0 90.0 123456")
        self.assertEqual(marks[0], ("500", "5000", "12.0", "90.0", "123456"))

    def test_line_without_marker(self):
        self.assertEqual(q._PROGRESS_RE.findall("Writing PLY"), [])


class TestTqdmFrame(unittest.TestCase):
    def test_eval_frame(self):
        m = q._TQDM_RE.search("Running eval:  44%|███▍ | 7/16 [02:20<03:04, 20.5s/it]")
        self.assertIsNotNone(m)
        self.assertEqual(m.group("label"), "Running eval")
        self.assertEqual((m.group("n"), m.group("total")), ("7", "16"))
        self.assertEqual((m.group("elapsed"), m.group("eta")), ("02:20", "03:04"))

    def test_frame_without_timing(self):
        m = q._TQDM_RE.search("Loading: 10%|█ | 1/10")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group("elapsed"))

    def test_chinese_text_is_not_taken_as_a_frame(self):
        """只匹配 ASCII 阶段名，避免误吃中文说明或路径。"""
        self.assertIsNone(q._TQDM_RE.search("训练完成：100%|██| 16/16"))


class TestConfigHelpers(unittest.TestCase):
    def test_int_valid(self):
        self.assertEqual(q._cfg_int({"a": 500}, "a", 15000, 100, 10 ** 7), 500)

    def test_int_missing_uses_default(self):
        self.assertEqual(q._cfg_int({}, "a", 15000, 100, 10 ** 7), 15000)

    def test_int_malformed_uses_default(self):
        for bad in ("abc", None, "7.5", [], {}):
            self.assertEqual(q._cfg_int({"a": bad}, "a", 15000, 100, 10 ** 7), 15000)

    def test_int_out_of_range_uses_default(self):
        self.assertEqual(q._cfg_int({"a": 5}, "a", 15000, 100, 10 ** 7), 15000)
        self.assertEqual(q._cfg_int({"a": 10 ** 9}, "a", 15000, 100, 10 ** 7), 15000)

    def test_choice(self):
        self.assertEqual(q._cfg_choice({"q": "快速"}, "q", q.QUALITY_PRESETS, "标准"), "快速")
        self.assertEqual(q._cfg_choice({"q": "乱写"}, "q", q.QUALITY_PRESETS, "标准"), "标准")
        self.assertEqual(q._cfg_choice({}, "q", q.QUALITY_PRESETS, "标准"), "标准")


class TestPresetTables(unittest.TestCase):
    def test_quality_tables_use_the_same_keys(self):
        """三份档位表的键必须一致，否则某个档位会取不到默认分辨率。"""
        self.assertEqual(set(q.QUALITY_PRESETS), set(q.RES_DEFAULT_BY_QUALITY))
        self.assertEqual(set(q.QUALITY_PRESETS), {"快速", "标准", "高质量"})

    def test_default_resolution_dirs_are_valid(self):
        self.assertTrue(set(q.RES_DEFAULT_BY_QUALITY.values())
                        <= {"images", "images_2", "images_4"})
        self.assertTrue(set(q.RES_DIR_MAP.values())
                        <= {"images", "images_2", "images_4"})

    def test_steps_increase_with_quality(self):
        steps = [q.QUALITY_PRESETS[k][0] for k in ("快速", "标准", "高质量")]
        self.assertEqual(steps, sorted(steps))


class TestPathHelpers(unittest.TestCase):
    def test_relative_path_resolves_under_project_root(self):
        self.assertEqual(q.resolve_path(os.path.join("tools", "x.bat")),
                         os.path.join(q.PROJECT_ROOT, "tools", "x.bat"))

    def test_absolute_path_is_kept(self):
        outside = os.path.join(tempfile.gettempdir(), "x.bat")
        self.assertEqual(q.resolve_path(outside), outside)

    def test_relativize_inside_project(self):
        inside = os.path.join(q.PROJECT_ROOT, "tools", "x.bat")
        self.assertEqual(q.relativize_path(inside), os.path.join("tools", "x.bat"))

    def test_relativize_outside_project_stays_absolute(self):
        outside = os.path.join(tempfile.gettempdir(), "x.bat")
        self.assertEqual(q.relativize_path(outside), outside)

    def test_empty_path(self):
        self.assertFalse(q.resolve_path(""))
        self.assertFalse(q.relativize_path(""))


def _bare_app():
    """借方法测纯逻辑，但不跑 __init__（那会建 Tk 窗口）。"""
    return q.QuickSplatApp.__new__(q.QuickSplatApp)


class TestWorkspaceProbing(unittest.TestCase):
    def setUp(self):
        self.app = _bare_app()
        self.tmp = tempfile.mkdtemp(prefix="ws_probe_")

    def test_find_latest_ply_on_missing_dir_returns_none(self):
        """选新数据集时工作区还不存在；这里曾直接 listdir 导致 GUI 崩溃。"""
        self.assertIsNone(self.app._find_latest_ply(os.path.join(self.tmp, "nope_gs")))

    def test_find_latest_ply_picks_newest(self):
        ws = os.path.join(self.tmp, "ws")
        os.makedirs(ws)
        old = os.path.join(ws, "a.ply")
        new = os.path.join(ws, "b.ply")
        for p, t in ((old, 1000), (new, 2000)):
            open(p, "w").close()
            os.utime(p, (t, t))
        self.assertEqual(self.app._find_latest_ply(ws), new)

    def test_find_latest_ply_without_any_ply(self):
        ws = os.path.join(self.tmp, "ws2")
        os.makedirs(ws)
        open(os.path.join(ws, "readme.txt"), "w").close()
        self.assertIsNone(self.app._find_latest_ply(ws))

    def test_new_output_ply_detection(self):
        """退出码非 0 但模型已训好时，靠它决定要不要保留 PLY。"""
        out = os.path.join(self.tmp, "outputs")
        os.makedirs(os.path.join(out, "run1"))
        self.assertFalse(self.app._find_new_output_ply(out, set()))
        open(os.path.join(out, "run1", "splat.ply"), "w").close()
        self.assertTrue(self.app._find_new_output_ply(out, set()))
        # 训练前就存在的旧目录不算“本次产物”
        self.assertFalse(self.app._find_new_output_ply(out, {"run1"}))

    def test_new_output_ply_on_missing_dir(self):
        self.assertFalse(self.app._find_new_output_ply(os.path.join(self.tmp, "nope"), set()))

    def test_count_images_only_counts_supported_extensions(self):
        d = os.path.join(self.tmp, "imgs")
        os.makedirs(d)
        for name in ("a.jpg", "b.PNG", "c.txt", "d.bmp", "e.png"):
            open(os.path.join(d, name), "w").close()
        self.assertEqual(self.app._count_images(d), 4)
        self.assertEqual(self.app._count_images(os.path.join(self.tmp, "nope")), 0)
        self.assertEqual(self.app._count_images(""), 0)


try:
    import cv2 as _cv2  # noqa: E402
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False  # 未装 opencv 时相关用例跳过


class TestExifOrientation(unittest.TestCase):
    """手机竖拍照片带 EXIF 旋转标记：COLMAP 应用方向而 cv2/stb_image 不会，
    训练图必须预旋转，否则与位姿差 90°、模型悄悄训废。"""

    def setUp(self):
        self.app = _bare_app()
        self.logs = []
        self.app._log = self.logs.append
        self.tmp = tempfile.mkdtemp(prefix="exif_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "src")
        self.dst = os.path.join(self.tmp, "dst")
        os.makedirs(self.src)

    def _write_jpeg(self, name, size, orientation=None):
        from PIL import Image
        im = Image.new("RGB", size, (120, 30, 200))
        if orientation is not None:
            exif = im.getexif()
            exif[274] = orientation  # Orientation
            im.save(os.path.join(self.src, name), exif=exif)
        else:
            im.save(os.path.join(self.src, name))

    def test_scan_missing_pillow_returns_empty(self):
        """扫描对坏文件/缺失 Pillow 都必须安静返回，绝不阻断训练。"""
        self.assertEqual(
            q.QuickSplatApp._scan_exif_rotations(self.src, ["nope.jpg"]), set())

    @unittest.skipUnless(_HAVE_CV2, "CI 环境未安装 opencv")
    def test_scan_finds_only_rotated(self):
        self._write_jpeg("a.jpg", (40, 20), orientation=6)
        self._write_jpeg("b.jpg", (40, 20))
        rotated = q.QuickSplatApp._scan_exif_rotations(self.src, ["a.jpg", "b.jpg"])
        self.assertEqual(rotated, {"a.jpg"})

    @unittest.skipUnless(_HAVE_CV2, "CI 环境未安装 opencv")
    def test_downscaled_applies_exif_transpose(self):
        """40x20 横放传感器 + orientation=6：COLMAP 看到 20x40 竖图，
        纠偏后的降采样副本必须是竖的，未标记的图不受影响。"""
        self._write_jpeg("a.jpg", (40, 20), orientation=6)
        self._write_jpeg("b.jpg", (40, 20))
        self.assertTrue(self.app._make_downscaled(
            self.dst, self.src, 2, rotated_names={"a.jpg"}))
        a = _cv2.imread(os.path.join(self.dst, "a.jpg"))
        b = _cv2.imread(os.path.join(self.dst, "b.jpg"))
        self.assertEqual(a.shape, (20, 10, 3))  # 竖：EXIF 已应用
        self.assertEqual(b.shape, (10, 20, 3))  # 横：原样
        self.assertTrue(os.path.isfile(os.path.join(self.dst, q.EXIF_MARKER)))

    @unittest.skipUnless(_HAVE_CV2, "CI 环境未安装 opencv")
    def test_factor_1_normalizes_without_resize(self):
        """高质量档的方向归一化副本：转方向、不缩放。"""
        self._write_jpeg("a.jpg", (40, 20), orientation=6)
        self.assertTrue(self.app._make_downscaled(
            self.dst, self.src, 1, rotated_names={"a.jpg"}))
        a = _cv2.imread(os.path.join(self.dst, "a.jpg"))
        self.assertEqual(a.shape, (40, 20, 3))

    @unittest.skipUnless(_HAVE_CV2, "CI 环境未安装 opencv")
    def test_stale_copy_without_marker_is_rebuilt_then_skipped(self):
        """旧版无纠偏副本（无 marker）必须被重建；重建后第二次运行跳过。"""
        self._write_jpeg("a.jpg", (40, 20), orientation=6)
        self._write_jpeg("b.jpg", (40, 20))
        os.makedirs(self.dst)
        for n in ("a.jpg", "b.jpg"):  # 模拟旧副本：张数对、方向错、无 marker
            shutil.copyfile(os.path.join(self.src, n), os.path.join(self.dst, n))
        self.assertTrue(self.app._make_downscaled(
            self.dst, self.src, 2, rotated_names={"a.jpg"}))
        a = _cv2.imread(os.path.join(self.dst, "a.jpg"))
        self.assertEqual(a.shape, (20, 10, 3))
        # 第二次：有 marker → 走“跳过生成”
        self.logs.clear()
        self.assertTrue(self.app._make_downscaled(
            self.dst, self.src, 2, rotated_names={"a.jpg"}))
        self.assertTrue(any("跳过生成" in t for t in self.logs))


class TestEvalReport(unittest.TestCase):
    """训练结束后的指标弹窗：阈值判定、缺失 LPIPS、坏文件都不能炸。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evalrep_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, payload, name="eval.json"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def test_good_psnr(self):
        verdict, level, rows = q.judge_eval_metrics(
            {"psnr": 27.5, "ssim": 0.9, "lpips_vgg": 0.08})
        self.assertEqual(level, "good")
        self.assertIn("质量不错", verdict)
        names = [r[0] for r in rows]
        self.assertEqual(names, ["PSNR", "SSIM", "LPIPS VGG"])

    def test_mid_and_bad_thresholds(self):
        self.assertEqual(q.judge_eval_metrics({"psnr": 22.0})[1], "mid")
        self.assertEqual(q.judge_eval_metrics({"psnr": 15.0})[1], "bad")
        self.assertIn("档位", q.judge_eval_metrics({"psnr": 15.0})[0])

    def test_missing_lpips_is_fine(self):
        """LPIPS 权重未下载时 eval.json 只有 PSNR/SSIM，弹窗不能缺行报错。"""
        verdict, level, rows = q.judge_eval_metrics({"psnr": 26.0, "ssim": 0.8})
        self.assertEqual(level, "good")
        self.assertEqual([r[0] for r in rows], ["PSNR", "SSIM"])

    def test_broken_or_missing_mean_is_neutral(self):
        for mean in (None, {}, {"ssim": 0.9}, "junk", 42):
            verdict, level, rows = q.judge_eval_metrics(mean)
            self.assertEqual(level, "none")
            self.assertEqual(rows, [])

    def test_load_eval_mean(self):
        good = self._write({"mean": {"psnr": 26.0}, "images": [1, 2]})
        self.assertEqual(q.load_eval_mean(good), {"psnr": 26.0})
        # 结构不符 / 损坏 / 不存在 → None
        self.assertIsNone(q.load_eval_mean(self._write({"images": []}, "bad1.json")))
        self.assertIsNone(q.load_eval_mean(self._write("not dict", "bad2.json")))
        self.assertIsNone(q.load_eval_mean(os.path.join(self.tmp, "nope.json")))


class TestColmapMatching(unittest.TestCase):
    """大图集匹配器自动切换与注册率解析。"""

    def test_matcher_selection_threshold(self):
        self.assertEqual(q.pick_colmap_matcher(50), "exhaustive")
        self.assertEqual(q.pick_colmap_matcher(100), "exhaustive")  # 边界：不超过不切换
        self.assertEqual(q.pick_colmap_matcher(101), "sequential")
        self.assertEqual(q.pick_colmap_matcher(300), "sequential")

    def test_parse_registered_images(self):
        """model_analyzer 的真实输出格式（多行、冒号后带空格）。"""
        out = "Cameras: 2\nImages: 49\nRegistered images: 46\nPoints: 61387\n"
        self.assertEqual(q.parse_registered_images(out), 46)
        self.assertIsNone(q.parse_registered_images("no match here"))
        self.assertIsNone(q.parse_registered_images(""))
        self.assertIsNone(q.parse_registered_images(None))


class TestHistoryModels(unittest.TestCase):
    """历史模型扫描：只有含 PLY 的目录才算模型，指标/步数从文件推。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hist_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "outputs")
        os.makedirs(self.out)

    def _model_dir(self, name, ply=True, eval_json=None, config_json=None,
                   ply_size=200 * 1024):
        d = os.path.join(self.out, name)
        os.makedirs(d)
        if ply:
            with open(os.path.join(d, "splat.ply"), "wb") as f:
                f.write(b"x" * ply_size)
        if eval_json is not None:
            with open(os.path.join(d, "eval.json"), "w", encoding="utf-8") as f:
                json.dump({"mean": eval_json, "images": []}, f)
        if config_json is not None:
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
                json.dump(config_json, f)
        return d

    def test_missing_dir_returns_empty(self):
        self.assertEqual(q.scan_history_models(os.path.join(self.tmp, "nope")), [])

    def test_dirs_without_ply_are_ignored(self):
        self._model_dir("20260101_000000_dead", ply=False,
                        config_json={"train_steps": 5000})  # 训练崩溃残留
        self.assertEqual(q.scan_history_models(self.out), [])

    def test_named_dir_parses_steps_quality_and_metrics(self):
        self._model_dir("vksplat_15000steps_standard",
                        eval_json={"psnr": 26.0, "ssim": 0.85})
        items = q.scan_history_models(self.out)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["steps"], 15000)
        self.assertEqual(it["quality"], "标准")
        self.assertEqual(it["metrics"]["psnr"], 26.0)
        self.assertEqual(it["level"], "good")
        self.assertGreater(it["size_mb"], 0)

    def test_timestamp_dir_falls_back_to_config_steps(self):
        d = self._model_dir("20260101_120000_scene",
                            eval_json={"psnr": 15.0},
                            config_json={"train_steps": 30000})
        items = q.scan_history_models(self.out)
        self.assertEqual(items[0]["steps"], 30000)
        self.assertIsNone(items[0]["quality"])
        self.assertEqual(items[0]["level"], "bad")
        self.assertEqual(items[0]["dir"], d)

    def test_sorted_newest_first(self):
        d1 = self._model_dir("vksplat_5000steps_fast")
        d2 = self._model_dir("vksplat_15000steps_standard")
        os.utime(d1, (1000, 1000))
        os.utime(d2, (2000, 2000))
        items = q.scan_history_models(self.out)
        self.assertEqual([os.path.basename(i["dir"]) for i in items],
                         ["vksplat_15000steps_standard", "vksplat_5000steps_fast"])

    def test_delete_guardrails(self):
        d = self._model_dir("vksplat_5000steps_fast")
        # 越界路径拒绝
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        ok, _ = q.delete_history_model(other, self.out)
        self.assertFalse(ok)
        self.assertTrue(os.path.isdir(other))
        # 界内正常删除
        ok, _ = q.delete_history_model(d, self.out)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(d))


if __name__ == "__main__":
    unittest.main()