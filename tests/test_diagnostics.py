# -*- coding: utf-8 -*-
"""诊断模块：失败原因解读与诊断包。不需要 GPU / 网络 / Tk。"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))

import diagnostics as d  # noqa: E402


class TestExplainFailure(unittest.TestCase):
    """正则都对应 VkSplat / COLMAP 的报错原文，写错一个字就再也匹配不上。"""

    def test_vram(self):
        hint = d.explain_failure(1, "Failed to allocate buffer memory. "
                                    "You are likely running out of VRAM.")
        self.assertIn("显存", hint[0])

    def test_ram_is_not_reported_as_vram(self):
        """'staging buffer memory' 与 'buffer memory' 必须互斥，否则给出矛盾建议。"""
        hint = d.explain_failure(1, "Failed to allocate staging buffer memory. "
                                    "You are likely running out of RAM.")
        self.assertIn("内存", hint[0])
        self.assertNotIn("显存", hint[0])

    def test_image_count_mismatch(self):
        hint = d.explain_failure(1, "RuntimeError: Failed to load image: "
                                    "D:/ws/images/0007.jpg")
        self.assertIn("照片", hint[0])

    def test_incomplete_sparse(self):
        hint = d.explain_failure(1, "cameras.bin or cameras.txt not found in `sparse/0`")
        self.assertIn("sparse", hint[0])

    def test_shader_file(self):
        hint = d.explain_failure(1, "RuntimeError: Failed to open file: "
                                    "D:/proj/shader/generated/x.spv")
        self.assertIn("着色器", hint[0])

    def test_missing_torch(self):
        hint = d.explain_failure(1, "ModuleNotFoundError: No module named 'torchvision'")
        self.assertIn("torch", hint[0])

    def test_colmap_output_unreadable(self):
        hint = d.explain_failure(1, "Cannot open file: D:/ws/sparse/0/cameras.bin")
        self.assertIn("COLMAP", hint[0])

    def test_unknown_output_has_no_opinion(self):
        self.assertIsNone(d.explain_failure(1, "something odd happened"))

    def test_windows_crash_code_alone_is_explained(self):
        hint = d.explain_failure(3221225477, "")
        self.assertIn("0xC0000005", hint[0])

    def test_colmap_falls_back_to_retry_not_photo_blame(self):
        """COLMAP 认不出原因的失败，第一建议是重跑，不是"你照片不行"。

        真实教训：安装版里 COLMAP 崩在特征提取（0xC0000409），旧兜底文案
        开口就是"照片重叠不够或纹理太少"，而同一批照片第二次跑注册率 100%。
        """
        hint = d.explain_failure(1, "", colmap=True)
        self.assertIn("重跑", hint[1])
        self.assertIn("重叠", hint[1])          # 照片因素仍在，但排在后面
        self.assertNotIn("照片重叠不够或纹理太少是常见原因", hint[1])

    def test_colmap_crash_code_says_it_is_not_the_photos(self):
        """0xC0000409 是 COLMAP 自己崩了，必须明说跟照片无关。"""
        hint = d.explain_failure(3221226505, "", colmap=True)
        self.assertIn("0xC0000409", hint[0])
        self.assertIn("照片无关", hint[0])
        self.assertIn("noCUDA", hint[1])

    def test_vkgs_failure_gets_no_colmap_advice(self):
        self.assertIsNone(d.explain_failure(1, "", colmap=False))


class TestRedact(unittest.TestCase):
    def test_replaces_plain_and_escaped_home(self):
        home = r"C:\Users\tester"
        text = (f"raw {home}\\logs\n"
                f"json C:\\\\Users\\\\tester\\\\logs\n"
                f"slash C:/Users/tester/logs")
        out = d.redact(text, home=home)
        self.assertNotIn("tester", out)
        self.assertEqual(out.count("%USERPROFILE%"), 3)

    def test_other_paths_untouched(self):
        self.assertEqual(d.redact(r"see D:\Desktop\3DGS", home=r"C:\Users\tester"),
                         r"see D:\Desktop\3DGS")


class TestLogTail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diag_")

    def test_missing_file_returns_empty(self):
        self.assertEqual(d.tail_lines(os.path.join(self.tmp, "nope.log")), "")

    def test_truncates_from_the_head(self):
        path = os.path.join(self.tmp, "a.log")
        with open(path, "w", encoding="utf-8") as f:
            for i in range(50):
                f.write(f"line{i}\n")
        out = d.tail_lines(path, limit=10)
        self.assertIn("line49", out)
        self.assertNotIn("line0\n", out)
        self.assertIn("已省略", out)

    def test_short_file_keeps_everything(self):
        path = os.path.join(self.tmp, "b.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write("only line\n")
        self.assertEqual(d.tail_lines(path, limit=10), "only line\n")

    def test_collect_logs_takes_newest_first(self):
        logs = os.path.join(self.tmp, "logs")
        os.makedirs(logs)
        for i, name in enumerate(("old.log", "new.log")):
            p = os.path.join(logs, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{name}\n")
            os.utime(p, (1000 + i * 1000, 1000 + i * 1000))
        got = d.collect_logs(logs, limit=1)
        self.assertEqual(list(got), ["new.log"])

    def test_collect_logs_on_missing_dir(self):
        self.assertEqual(d.collect_logs(os.path.join(self.tmp, "nope")), {})


class TestBuildZip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diagzip_")
        os.makedirs(os.path.join(self.tmp, "gui"))
        os.makedirs(os.path.join(self.tmp, "logs"))
        with open(os.path.join(self.tmp, "gui", "quick_gui_config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"quality": "标准", "train_steps": 15000, "colmap_path": "tools/x.bat"}, f)
        with open(os.path.join(self.tmp, "logs", "20261007.log"), "w", encoding="utf-8") as f:
            f.write("INFO hello\n")
        self.dest = os.path.join(self.tmp, "out", "diag.zip")

    def test_zip_contents(self):
        d.build_zip(self.dest, self.tmp, python_exe=sys.executable)
        with zipfile.ZipFile(self.dest) as z:
            names = set(z.namelist())
            self.assertIn("report.txt", names)
            self.assertIn("quick_gui_config.json", names)
            self.assertIn("logs/20261007.log", names)

    def test_report_lists_tool_paths_and_training_params(self):
        d.build_zip(self.dest, self.tmp, python_exe=sys.executable)
        with zipfile.ZipFile(self.dest) as z:
            report = z.read("report.txt").decode("utf-8")
        self.assertIn("工具路径", report)
        self.assertIn("质量档位", report)
        self.assertIn("标准", report)

    def test_build_zip_works_without_doctor(self):
        """临时项目里没有 doctor.py，诊断包仍要能生成。"""
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, "doctor.py")))
        d.build_zip(self.dest, self.tmp, python_exe=sys.executable)
        with zipfile.ZipFile(self.dest) as z:
            self.assertNotIn("doctor.json", z.namelist())


class TestDesktopDir(unittest.TestCase):
    """桌面被重定向时，诊断包不该悄悄落到项目目录里。"""

    def test_returns_existing_dir_or_none(self):
        p = d.desktop_dir()
        self.assertTrue(p is None or os.path.isdir(p))

    def test_default_dest_uses_resolved_desktop(self):
        dest = d.default_dest(r"C:\project")
        home = d.desktop_dir()
        self.assertTrue(os.path.basename(dest).startswith("3dgs_diag_"))
        if home:
            self.assertEqual(os.path.dirname(dest), home)

    def test_falls_back_to_project_root(self):
        orig = d.desktop_dir
        d.desktop_dir = lambda: None
        try:
            self.assertTrue(d.default_dest(r"C:\proj").startswith(r"C:\proj"))
        finally:
            d.desktop_dir = orig


if __name__ == "__main__":
    unittest.main()