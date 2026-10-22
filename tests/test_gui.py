# -*- coding: utf-8 -*-
"""pipeline_core 里可离线测试的部分：正则解析、配置读取、文件探测。

不需要 GPU、网络和 Qt 界面。界面层（PySide6）的测试见 test_qt_gui.py。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
        # 末尾的显存字段是可选的，旧版训练器不给这一项，匹配到空串
        self.assertEqual(marks[-1], ("100", "3000", "1.5", "43.5", "79296", ""))

    def test_plain_marker(self):
        marks = q._PROGRESS_RE.findall("PROGRESS: 500/5000 12.0 90.0 123456")
        self.assertEqual(marks[0], ("500", "5000", "12.0", "90.0", "123456", ""))

    def test_marker_carries_vram(self):
        """训练器额外报一项显存占用（MB）；旧版没有这一项，解析要兼容。"""
        marks = q._PROGRESS_RE.findall("PROGRESS: 500/5000 12.0 90.0 123456 3276")
        self.assertEqual(marks[0], ("500", "5000", "12.0", "90.0", "123456", "3276"))

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


def _images_bin(names, pt_bytes=24, n2d=3):
    """按 COLMAP images.bin 布局造假数据：每张图只写定位成功的那些。"""
    import struct
    buf = bytearray(struct.pack("<q", len(names)))
    for i, name in enumerate(names):
        buf += struct.pack("<i", i + 1)              # image_id
        buf += struct.pack("<7d", *([0.0] * 7))      # qvec(4) + tvec(3)
        buf += struct.pack("<i", 1)                  # camera_id
        buf += name.encode("ascii") + b"\x00"
        buf += struct.pack("<Q", n2d)
        buf += b"\x00" * (n2d * pt_bytes)            # 每个 2D 点 24（4.x）或 32（3.x）字节
    return bytes(buf)


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
    def test_rename_retries_when_file_locked(self):
        """Windows 上刚写出的 jpg 会被杀软/索引服务短暂占用，重命名偶发 WinError 5；
        必须重试而不是把异常抛上去（这条也钉住曾经让本文件偶发失败的竞态）。"""
        from unittest import mock
        self._write_jpeg("a.jpg", (40, 20))
        real_rename = os.rename
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise OSError(13, "Permission denied")
            return real_rename(src, dst)

        with mock.patch.object(q.os, "rename", side_effect=flaky), \
                mock.patch.object(q.time, "sleep", lambda _s: None):
            ok = self.app._make_downscaled(self.dst, self.src, 2, rotated_names=set())
        self.assertTrue(ok)
        # 只要求「失败后重试并最终成功」：第 3 次走的是真 rename，
        # 它自己也可能再被挡一次，所以钉死次数反而不稳。
        self.assertGreaterEqual(len(calls), 3)
        self.assertTrue(os.path.isfile(os.path.join(self.dst, "a.jpg")))

    @unittest.skipUnless(_HAVE_CV2, "CI 环境未安装 opencv")
    def test_rename_exhausted_fails_cleanly(self):
        """重试耗尽要返回 False 并说清下一步，不能抛异常。"""
        from unittest import mock
        self._write_jpeg("a.jpg", (40, 20))
        with mock.patch.object(q.os, "rename", side_effect=OSError(13, "denied")), \
                mock.patch.object(q.time, "sleep", lambda _s: None):
            ok = self.app._make_downscaled(self.dst, self.src, 2, rotated_names=set())
        self.assertFalse(ok)
        self.assertTrue(any("重命名" in t for t in self.logs))

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


class TestSplatShare(unittest.TestCase):
    """.splat 分享版：默认落在 PLY 同名处，历史模型要能被找回来。"""

    PROPS = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
             "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3")

    def setUp(self):
        self.app = _bare_app()
        self.lines = []
        self.app._log = self.lines.append
        self.tmp = tempfile.mkdtemp(prefix="splat_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_ply(self, name, n=2, nan_index=None):
        import struct
        path = os.path.join(self.tmp, name)
        header = ("ply\nformat binary_little_endian 1.0\n"
                  f"element vertex {n}\n"
                  + "".join(f"property float {p}\n" for p in self.PROPS)
                  + "end_header\n")
        body = b""
        for i in range(n):
            vals = [1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 2.0,
                    -2.0, -2.0, -2.0, 1.0, 0.0, 0.0, 0.0]
            if nan_index == i:
                vals[0] = float("nan")
            body += struct.pack("<14f", *vals)
        with open(path, "wb") as f:
            f.write(header.encode("ascii"))
            f.write(body)
        return path

    def test_default_dest_matches_ply_stem(self):
        ply = self._write_ply("vksplat_5000steps_fast.ply", n=2)
        out = self.app._export_splat(ply)
        self.assertEqual(out, os.path.join(self.tmp, "vksplat_5000steps_fast.splat"))
        self.assertEqual(os.path.getsize(out), 2 * 32)

    def test_explicit_dest_avoids_splat_splat(self):
        """outputs 里的模型都叫 splat.ply，默认命名会变成 "splat.splat"，
        所以分享历史模型时必须按目录名指定 dest。"""
        ply = self._write_ply("splat.ply", n=1)
        dest = os.path.join(self.tmp, "vksplat_15000steps_standard.splat")
        out = self.app._export_splat(ply, dest=dest)
        self.assertEqual(out, dest)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "splat.splat")))

    def test_nan_gaussians_are_dropped(self):
        ply = self._write_ply("bad.ply", n=3, nan_index=1)
        out = self.app._export_splat(ply)
        self.assertEqual(os.path.getsize(out), 2 * 32)
        self.assertTrue(any("NaN" in t for t in self.lines))

    def test_not_a_3dgs_ply_returns_none_without_raising(self):
        path = os.path.join(self.tmp, "plain.ply")
        with open(path, "w", encoding="ascii") as f:
            f.write("ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
                    "property float x\nend_header\n")
            f.write("\x00" * 4)
        self.assertIsNone(self.app._export_splat(path))
        self.assertTrue(any("导出失败" in t for t in self.lines))

    def test_scan_history_finds_share_version_by_dir_name(self):
        out = os.path.join(self.tmp, "outputs")
        d = os.path.join(out, "vksplat_5000steps_fast")
        os.makedirs(d)
        shutil.copy(self._write_ply("vksplat_5000steps_fast.ply"),
                    os.path.join(d, "splat.ply"))
        self.assertIsNone(q.scan_history_models(out)[0]["splat"])
        want = os.path.join(d, "vksplat_5000steps_fast.splat")
        with open(want, "wb") as f:
            f.write(b"\x00" * 32)
        self.assertEqual(q.scan_history_models(out)[0]["splat"], want)


class TestFailureSurface(unittest.TestCase):
    """失败原因除了进日志，还必须送到主面板回调（新手不翻折叠日志）。"""

    def setUp(self):
        self.app = _bare_app()
        self.app._last_failure_hint = None
        self.lines = []
        self.cards = []
        self.app._log = self.lines.append
        self.app.show_failure = lambda cause, advice: self.cards.append((cause, advice))

    def test_known_error_reaches_the_panel(self):
        self.app._explain_failure(1, "ERROR: Failed to allocate buffer memory (out of VRAM)")
        self.assertEqual(len(self.cards), 1)
        self.assertIn("显存", self.cards[0][0])
        self.assertTrue(any("原因:" in t for t in self.lines))

    def test_unrecognized_error_still_reaches_the_panel(self):
        """认不出原因时也要有兜底卡片，不能让主面板一片空白。"""
        self.app._explain_failure(1, "some output nobody taught us about")
        self.assertEqual(len(self.cards), 1)
        self.assertIn("诊断包", self.cards[0][1])

    def test_same_reason_is_not_shown_twice(self):
        """自动续训会反复撞上同一个错误，卡片只说一次。"""
        out = "Failed to allocate staging buffer memory (out of RAM)"
        self.app._explain_failure(1, out)
        self.app._explain_failure(1, out)
        self.assertEqual(len(self.cards), 1)

    def test_host_without_the_callback_still_works(self):
        """宿主没实现 show_failure 时（比如无界面跑批）不能因此崩掉管线。"""
        del self.app.show_failure
        self.app._explain_failure(1, "out of VRAM")
        self.assertTrue(any("原因:" in t for t in self.lines))


class TestCaptureReportHelpers(unittest.TestCase):
    """P7 的纯函数：images.bin 解析、清晰度阈值、报告与文案。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="caphelp_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, tmp, blob, name="images.bin"):
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, name), "wb") as f:
            f.write(blob)
        return tmp

    def test_parses_both_point2d_record_sizes(self):
        """COLMAP 3.x 每个 2D 点 32 字节，4.x 起是 24 字节，两种都要认。"""
        names = ["a.jpg", "b.jpg", "c.jpg"]
        for pt in (24, 32):
            d = self._write(os.path.join(self.tmp, "sparse_%d" % pt),
                            _images_bin(names, pt))
            self.assertEqual(q.read_registered_names(d), set(names))

    def test_truncated_file_is_not_guessed(self):
        """解析不出来就返回 None；拿半截错位结果去劝用户补拍更糟。"""
        blob = _images_bin(["a.jpg", "b.jpg"], 24)
        d = self._write(os.path.join(self.tmp, "sparse_bad"), blob[:-5])
        self.assertIsNone(q.read_registered_names(d))

    def test_missing_file_returns_none(self):
        self.assertIsNone(q.read_registered_names(os.path.join(self.tmp, "nope")))

    def test_blur_needs_enough_samples(self):
        scores = [("a.jpg", 5.0), ("b.jpg", 500.0)]
        self.assertEqual(q.pick_blurry(scores), [])
        many = [("x%d.jpg" % i, 500.0) for i in range(10)]
        many[0] = ("blurry.jpg", 3.0)
        self.assertEqual([n for n, _s in q.pick_blurry(sorted(many))], ["blurry.jpg"])

    def test_report_none_when_photos_look_fine(self):
        allp = ["a.jpg", "b.jpg"]
        self.assertIsNone(q.build_capture_report(allp, set(allp), []))

    def test_report_lists_which_photos_failed(self):
        allp = ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]
        rep = q.build_capture_report(allp, {"a.jpg", "b.jpg"}, [])
        self.assertEqual(rep["level"], "bad")          # 50% 定位成功
        self.assertEqual(rep["missing"], ["c.jpg", "d.jpg"])

    def test_text_avoids_jargon_and_offers_redo(self):
        allp = ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]
        rep = q.build_capture_report(allp, {"a.jpg", "b.jpg", "c.jpg"}, [])
        text = q.capture_report_text(rep)
        self.assertIn("1 张照片没能对上位置", text)
        self.assertIn("d.jpg", text)
        self.assertIn("重叠", text)
        for jargon in ("注册率", "COLMAP", "Registered"):
            self.assertNotIn(jargon, text)


class TestCaptureGate(unittest.TestCase):
    """训练前的这道提醒：只提醒不拦截，任何失败都必须照常训练。"""

    def setUp(self):
        self.app = q.PipelineCore.__new__(q.PipelineCore)
        self.app._log = lambda t: None
        self.app._capture_report = None
        self.tmp = tempfile.mkdtemp(prefix="capgate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_no_report_means_train(self):
        self.assertTrue(self.app._confirm_capture_quality())

    def test_headless_host_without_callback_still_trains(self):
        self.app._capture_report = {"level": "warn", "missing": ["a.jpg"]}
        self.assertTrue(self.app._confirm_capture_quality())

    def test_host_answer_is_respected(self):
        self.app._capture_report = {"level": "bad", "missing": ["a.jpg"]}
        self.app.ask_capture_report = lambda report: False
        self.assertFalse(self.app._confirm_capture_quality())

    def test_host_exception_does_not_stop_training(self):
        self.app._capture_report = {"level": "bad", "missing": ["a.jpg"]}

        def boom(report):
            raise RuntimeError("弹窗挂了")
        self.app.ask_capture_report = boom
        self.assertTrue(self.app._confirm_capture_quality())

    def test_report_is_consumed_once(self):
        self.app._capture_report = {"level": "bad", "missing": ["a.jpg"]}
        self.app.ask_capture_report = lambda report: True
        self.assertTrue(self.app._confirm_capture_quality())
        self.assertIsNone(self.app._capture_report)

    def _make_scene(self, registered_n, total_n=10):
        names = ["p%02d.jpg" % i for i in range(total_n)]
        sparse = os.path.join(self.tmp, "sparse", "0")
        os.makedirs(sparse, exist_ok=True)
        with open(os.path.join(sparse, "images.bin"), "wb") as f:
            f.write(_images_bin(names[:registered_n]))
        img_dir = os.path.join(self.tmp, "imgs")
        os.makedirs(img_dir, exist_ok=True)
        for n in names:
            open(os.path.join(img_dir, n), "wb").close()
        return names, sparse, img_dir

    def test_stats_written_to_stderr_are_noticed(self):
        """COLMAP 把 model_analyzer 的统计写到 stderr。只看 stdout 时永远解析不到，
        注册率检查曾经整轮静默失效——这条钉住合并两个流的行为。"""
        from unittest import mock
        names, sparse, img_dir = self._make_scene(6)
        fake = mock.Mock(stdout="", stderr="Images: 10\nRegistered images: 6\n")
        with mock.patch.object(q.subprocess, "run", return_value=fake):
            self.app._check_registration("colmap.exe", {}, sparse, 10, img_dir)
        rep = self.app._capture_report
        self.assertEqual(rep["missing"], names[6:])
        self.assertEqual(rep["level"], "bad")

    def test_healthy_batch_stays_quiet(self):
        from unittest import mock
        _names, sparse, img_dir = self._make_scene(10)
        fake = mock.Mock(stdout="", stderr="Registered images: 10\n")
        with mock.patch.object(q.subprocess, "run", return_value=fake):
            self.app._check_registration("colmap.exe", {}, sparse, 10, img_dir)
        self.assertIsNone(self.app._capture_report)

    def test_check_failure_leaves_pipeline_untouched(self):
        from unittest import mock
        _names, sparse, img_dir = self._make_scene(6)
        with mock.patch.object(q.subprocess, "run", side_effect=OSError("colmap 没了")):
            self.app._check_registration("colmap.exe", {}, sparse, 10, img_dir)
        self.assertIsNone(self.app._capture_report)
        self.assertTrue(self.app._confirm_capture_quality())


class TestFirstRunMessage(unittest.TestCase):
    """示例首跑的那句里程碑话只说一次，之后恢复正常文案。"""

    def setUp(self):
        self.app = _bare_app()
        self.app.init_core()

    def test_milestone_then_normal(self):
        self.app._from_sample = True
        self.assertIn("第一个模型", self.app._done_message())
        self.assertIn("历史记录", self.app._done_message())

    def test_plain_run_is_not_called_first_time(self):
        self.assertIn("历史记录", self.app._done_message())


class TestProgressSpans(unittest.TestCase):
    """一根进度条跑完整条管线：阶段内 0~1 要映射到整条进度的对应区间。"""

    def setUp(self):
        self.app = _bare_app()
        self.app.init_core()
        self.got = []
        self.app.set_progress = lambda f, d: self.got.append((round(f, 3), d))
        self.app._log = lambda t: None

    def test_train_span_offset(self):
        self.app._set_span(0.30, 1.0)
        self.app._progress(0.5, "训练一半")
        self.assertEqual(self.got[-1][0], 0.65)

    def test_clamped_out_of_range(self):
        self.app._set_span(0.0, 0.3)
        self.app._progress(1.7, "越界")
        self.assertEqual(self.got[-1][0], 0.3)

    def test_colmap_registration_line_drives_progress(self):
        """真实日志行格式（对照 colmap.exe 的格式串核实过的那种）必须能认出来。

        括号里的 num_reg_frames 才是已定位张数，所以分子取 96 而不是 #64。
        """
        self.app._set_span(0.5, 1.0)
        self.app._colmap_t0 = time.time() - 120
        self.app._colmap_line_progress(
            "I20260930 15:20:26.003764 28524 incremental_pipeline.cc:620]"
            " Registering image #64 (num_reg_frames=96)", 128)
        frac, detail = self.got[-1]
        self.assertAlmostEqual(frac, 0.5 + 0.5 * (96 / 128.0), places=3)
        self.assertIn("96/128", detail)
        self.assertIn("预计还需", detail)

    def test_image_id_is_not_confused_with_registered_count(self):
        """#N 是图像 id，不能当进度：刚定位第 3 张时 id 可能已经很大。"""
        self.app._colmap_line_progress("Registering image #97 (num_reg_frames=3)", 128)
        _frac, detail = self.got[-1]
        self.assertIn("3/128", detail)
        self.assertNotIn("97/128", detail)

    def test_progress_never_goes_backward(self):
        """多段重建（场景不连通）另起子模型时计数从头开始，进度也只许前进。"""
        self.app._colmap_line_progress("Registering image #90 (num_reg_frames=90)", 128)
        self.app._colmap_line_progress("Registering image #2 (num_reg_frames=2)", 128)
        self.assertEqual(self.got[-1][0], self.got[-2][0])
        self.assertIn("90/128", self.got[-1][1])

    def test_other_lines_are_ignored(self):
        self.app._colmap_line_progress("=> Reading images", 128)
        self.assertEqual(self.got, [])

    def test_first_line_only_starts_the_clock(self):
        """头几张不稳，第一条只记时间、不给剩余时间估算。"""
        self.app._colmap_line_progress("Registering image #7 (num_reg_frames=1)", 128)
        self.assertEqual(len(self.got), 1)
        self.assertNotIn("预计还需", self.got[0][1])
        self.assertIsNotNone(self.app._colmap_t0)


class TestPhotoPrecheck(unittest.TestCase):
    """选完照片就地给的本地结论。"""

    def test_too_few_photos(self):
        text, level = q.photo_precheck_text(12, [])
        self.assertEqual(level, "warn")
        self.assertIn("12 张", text)
        self.assertIn("30", text)

    def test_blurry_photos_are_named(self):
        _text, level = q.photo_precheck_text(120, [])
        self.assertEqual(level, "ok")
        text, level = q.photo_precheck_text(120, [("p9.jpg", 3.0), ("p8.jpg", 5.0)])
        self.assertEqual(level, "warn")
        self.assertIn("p9.jpg", text)
        self.assertIn("不一定是问题", text)   # 低纹理会误报，措辞要留余地

    def test_clean_batch_is_encouraging(self):
        text, level = q.photo_precheck_text(128, [])
        self.assertEqual(level, "ok")
        self.assertIn("128", text)


class TestNoConsoleWindows(unittest.TestCase):
    """GUI 启动的后台子进程不许弹控制台窗口 —— 用户看到的"每跑一步闪一个黑框"
    就是 pythonw 启动子进程时默认带出来的控制台。"""

    def test_run_cmd_passes_no_window_flag(self):
        app = _bare_app()
        app._log = lambda t: None
        app.stop_flag = False
        seen = {}

        class FakeProc:
            returncode = 0
            stdout = iter([])

            def wait(self):
                return 0

        def fake_popen(cmd, **kw):
            seen.update(kw)
            return FakeProc()

        orig = q.subprocess.Popen
        q.subprocess.Popen = fake_popen
        try:
            self.assertTrue(app.run_cmd(["colmap.exe", "mapper"]))
        finally:
            q.subprocess.Popen = orig
        self.assertIn("creationflags", seen)
        expect = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
        self.assertEqual(seen["creationflags"], expect)

    def test_syscheck_constant_matches_platform(self):
        import syscheck
        self.assertEqual(syscheck.NO_WINDOW,
                         0x08000000 if sys.platform == "win32" else 0)

    def test_viewer_launch_is_not_hidden(self):
        """VKGS 查看器和资源管理器是要用户看的，不能顺手一起藏掉。"""
        with open(os.path.join(ROOT, "gui", "pipeline_core.py"), encoding="utf-8") as f:
            src = f.read()
        line = [l for l in src.splitlines() if "Popen([vkgs" in l]
        self.assertEqual(len(line), 1)
        self.assertNotIn("NO_WINDOW", line[0])


class TestMakeJunction(unittest.TestCase):
    """工作区照片接入：重跑必须复用，绝不删真实目录，联接读不通要能退回复制。"""

    def setUp(self):
        self.app = _bare_app()
        self.app.init_core()
        self.logs = []
        self.app._log = self.logs.append
        self.app._notify_failure = lambda c, a: self.logs.append(("CARD", c, a))
        self.tmp = tempfile.mkdtemp(prefix="link_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        open(os.path.join(self.photos, "a.jpg"), "w").close()

    def _link(self, name="images"):
        return os.path.join(self.tmp, name)

    def _mklink(self, link):
        subprocess.run(["cmd", "/c", "mklink", "/J", link, self.photos],
                       capture_output=True)

    @unittest.skipIf(sys.platform != "win32", "目录联接是 Windows 特性")
    def test_same_target_is_reused_not_failed(self):
        """用户报的场景：训练过一次再点开始，旧代码在这里报「mklink 失败：文件已存在」
        并把整个 COLMAP 阶段中止。"""
        link = self._link()
        self._mklink(link)
        self.assertTrue(self.app._ensure_images_dir(link, self.photos))
        self.assertEqual(self.logs, [])
        self.assertEqual(os.listdir(self.photos), ["a.jpg"])

    @unittest.skipIf(sys.platform != "win32", "目录联接是 Windows 特性")
    def test_reuse_does_not_traverse_the_link(self):
        """别人电脑上的现场：系统禁止遍历程序建的联接（WinError 448）。

        os.path.realpath 会真的去遍历，448 不在 CPython 容忍的错误码里、直接抛异常，
        于是「选好照片就崩」。复用判断必须走 os.readlink，所以这里让 realpath 一被
        调用就抛，跑通才说明数据通路没押在联接可用性上。
        """
        link = self._link()
        self._mklink(link)
        real_realpath = os.path.realpath

        def boom(path, *a, **kw):
            raise OSError(448, "无法遍历路径，因为它包含不受信任的装入点。", path)

        os.path.realpath = boom
        try:
            self.assertTrue(self.app._ensure_images_dir(link, self.photos))
        finally:
            os.path.realpath = real_realpath
        self.assertEqual(os.listdir(self.photos), ["a.jpg"])

    @unittest.skipIf(sys.platform != "win32", "目录联接是 Windows 特性")
    def test_unreadable_link_falls_back_to_copying_photos(self):
        link = self._link()
        self._mklink(link)
        self.app._dir_readable = lambda path: False
        self.assertTrue(self.app._ensure_images_dir(link, self.photos))
        self.assertFalse(q.PipelineCore._is_reparse(link))
        self.assertIn("a.jpg", os.listdir(link))
        self.assertEqual(os.listdir(self.photos), ["a.jpg"])    # 原照片夹不能被动
        self.assertTrue(any("复制" in t for t in self.logs if isinstance(t, str)))

    @unittest.skipIf(sys.platform != "win32", "目录联接是 Windows 特性")
    def test_copied_photos_dir_is_reused_on_rerun(self):
        """复制出来的 images 是普通文件夹：第二次要认得出是自己建的，不能要求用户
        换工作区名，也不能再复制一遍。"""
        link = self._link()
        self._mklink(link)
        self.app._dir_readable = lambda path: False
        self.assertTrue(self.app._ensure_images_dir(link, self.photos))
        del self.app._dir_readable                              # 这台机器恢复正常
        self.logs.clear()
        self.assertTrue(self.app._ensure_images_dir(link, self.photos))
        self.assertEqual(self.logs, [])

    @unittest.skipIf(sys.platform != "win32", "目录联接是 Windows 特性")
    def test_switching_dataset_rebuilds_link_and_keeps_sources(self):
        link = self._link()
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        open(os.path.join(other, "b.jpg"), "w").close()
        self._mklink(link)
        self.assertTrue(self.app._ensure_images_dir(link, other))
        self.assertEqual(os.listdir(self.photos), ["a.jpg"])   # 两个源目录都不能被删
        self.assertEqual(os.listdir(other), ["b.jpg"])
        self.assertTrue(any("换了" in t for t in self.logs if isinstance(t, str)))

    def test_real_directory_is_never_deleted(self):
        """link 位置是真实文件夹时可能装着用户自己的照片，删不得。"""
        link = self._link()
        os.makedirs(link)
        open(os.path.join(link, "mine.jpg"), "w").close()
        self.assertFalse(self.app._ensure_images_dir(link, self.photos))
        self.assertEqual(os.listdir(link), ["mine.jpg"])
        self.assertTrue(any(isinstance(t, tuple) for t in self.logs))

    def test_run_text_returns_decodable_output(self):
        """基本路径：返回值必须能安全解码，不会把 None 交回调用方去 .strip()。"""
        r = q.PipelineCore._run_text(["cmd", "/c", "echo", "hello_diag"])
        self.assertIsNotNone(r)
        self.assertEqual(r.returncode, 0)
        self.assertIsInstance(r.stdout, str)
        self.assertIn("hello_diag", r.stdout)

    def test_run_text_decodes_non_utf8_bytes(self):
        """非 UTF-8 输出（cmd 很常见）必须解成字符串，而不是抛异常。

        不能断言 `cmd /c echo 中文` 的结果：GitHub runner 的 OEM 代码页表示不了中文，
        cmd 自己就先输出成 '????' —— 那是环境差异，不是解码能力问题。所以这里自己
        喂确定的 GBK 字节。
        """
        code = "import sys; sys.stdout.buffer.write(b'\\xd6\\xd0\\xce\\xc4')"  # GBK「中文」
        r = q.PipelineCore._run_text([sys.executable, "-c", code])
        self.assertIsNotNone(r)
        self.assertIsInstance(r.stdout, str)
        self.assertIn("中文", r.stdout)


class TestVersionSingleSource(unittest.TestCase):
    """版本号只有一个来源 gui/app_version.py，界面/日志/打包脚本都读它。

    起因：同号多个构建真实发生过（2.3.0 收回重发），装机版却读不到自己的版本
    —— 因为安装包不分发 installer/，版本号写在那里的话程序看不见。
    """

    def test_version_is_semver(self):
        sys.path.insert(0, os.path.join(ROOT, "gui"))
        from app_version import APP_VERSION
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")

    def test_build_script_reads_it_instead_of_hardcoding(self):
        with open(os.path.join(ROOT, "installer", "build_setup.ps1"),
                  encoding="utf-8") as f:
            ps = f.read()
        self.assertNotIn("$AppVersion = '", ps)
        self.assertIn("gui\\app_version.py", ps)

    def test_changelog_top_entry_is_current_version(self):
        """CHANGELOG 最上面一节必须就是当前版本号。

        版本号同时活在 app_version.py、CHANGELOG 标题、git 标签和 release 名上，
        少改任何一处都会让人对不上账：发出去的包说是 2.3.2，发布说明还停在上一版。
        """
        from app_version import APP_VERSION
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            heads = [ln[3:].strip() for ln in f if ln.startswith("## ")]
        self.assertTrue(heads, "CHANGELOG 里找不到「## 版本号」小节标题")
        self.assertEqual(heads[0].split()[0], APP_VERSION)

    def test_diagnostics_report_carries_version(self):
        import diagnostics as d
        from app_version import APP_VERSION
        report = d.build_report(ROOT, doctor_json=None, cfg={})
        self.assertIn(f"版本       {APP_VERSION}", report.splitlines()[:5][2])


if __name__ == "__main__":
    unittest.main()