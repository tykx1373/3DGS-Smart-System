# -*- coding: utf-8 -*-
"""syscheck 里纯函数的单元测试：不需要 GPU、不联网、不起 GUI。

跑法：
    env\\vksplat\\python.exe -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))

import syscheck  # noqa: E402


class TestFormatHelpers(unittest.TestCase):
    def test_driver_version_nvidia_uses_its_own_bitfield(self):
        """NVIDIA 不走 Vulkan 规范的位域。曾按规范解码，报出 617.56 而实际是 617.14。"""
        raw = (617 << 22) | (14 << 14) | (0 << 6)
        dev = {"vendor_id": 0x10DE, "driver_version": raw}
        self.assertEqual(syscheck.format_driver_version(dev), "617.14.0")

    def test_driver_version_other_vendor_uses_vulkan_spec(self):
        raw = (25 << 22) | (2 << 12) | 9
        dev = {"vendor_id": 0x8086, "driver_version": raw}
        self.assertEqual(syscheck.format_driver_version(dev), "25.2.9")

    def test_missing_fields_do_not_raise(self):
        self.assertEqual(syscheck.format_driver_version({}), "0.0.0")
        self.assertEqual(syscheck.format_api_version({}), "0.0.0")

    def test_api_version(self):
        raw = (1 << 22) | (4 << 12) | 351
        self.assertEqual(syscheck.format_api_version({"api_version": raw}), "1.4.351")

    def test_duration(self):
        self.assertEqual(syscheck.format_duration(None), "—")
        self.assertEqual(syscheck.format_duration(59), "约 59 秒")
        self.assertEqual(syscheck.format_duration(60), "约 1 分钟")
        self.assertEqual(syscheck.format_duration(3600), "约 1 小时 0 分钟")
        self.assertEqual(syscheck.format_duration(3661), "约 1 小时 1 分钟")


class TestDeviceClassification(unittest.TestCase):
    def test_integrated(self):
        self.assertTrue(syscheck.is_integrated("Intel(R) UHD Graphics 630"))
        self.assertTrue(syscheck.is_integrated("AMD Radeon(TM) Graphics"))
        self.assertFalse(syscheck.is_integrated("NVIDIA GeForce RTX 4060 Laptop GPU"))
        self.assertFalse(syscheck.is_integrated("AMD Radeon RX 6700 XT"))

    def test_unknown_name_is_treated_as_integrated(self):
        """名字认不出来时按核显处理：估时更保守、cap_max 更小，避免 TDR 超时。"""
        self.assertTrue(syscheck.is_integrated("Some Unknown Adapter"))
        self.assertTrue(syscheck.is_integrated(""))
        self.assertTrue(syscheck.is_integrated(None))

    def test_tier(self):
        self.assertEqual(syscheck._device_tier("NVIDIA GeForce RTX 4060 Laptop GPU"),
                         "discrete_high")
        self.assertEqual(syscheck._device_tier("NVIDIA GeForce GTX 1060"), "discrete_mid")
        self.assertEqual(syscheck._device_tier("Intel(R) Iris(R) Xe Graphics"), "integrated")


class TestEstimates(unittest.TestCase):
    DEV = {"name": "NVIDIA GeForce RTX 4060 Laptop GPU",
           "viable": True, "vram_bytes": 8 * 1024 ** 3}

    def test_laptop_penalty_is_applied(self):
        """笔记本比同型号台式机慢很多，首次估算要按系数放大。"""
        desktop = syscheck.estimate_train_seconds(self.DEV, "标准", 15000, laptop=False)
        laptop = syscheck.estimate_train_seconds(self.DEV, "标准", 15000, laptop=True)
        self.assertAlmostEqual(laptop / desktop, syscheck.LAPTOP_PENALTY, places=6)

    def test_measured_ips_wins_and_is_not_penalised_again(self):
        """跑过一次后用实测 it/s，且不再重复叠加笔记本系数。"""
        got = syscheck.estimate_train_seconds(self.DEV, "标准", 3000,
                                              measured_ips=10.0, laptop=True)
        self.assertAlmostEqual(got, 300.0, places=6)

    def test_higher_quality_estimates_more_time(self):
        fast = syscheck.estimate_train_seconds(self.DEV, "快速", 15000, laptop=False)
        high = syscheck.estimate_train_seconds(self.DEV, "高质量", 15000, laptop=False)
        self.assertLess(fast, high)

    def test_colmap_scales_with_images_and_laptop(self):
        self.assertIsNone(syscheck.estimate_colmap_seconds(0))
        self.assertIsNone(syscheck.estimate_colmap_seconds(None))
        one = syscheck.estimate_colmap_seconds(10, laptop=False)
        self.assertAlmostEqual(one, 10 * syscheck.COLMAP_SEC_PER_IMAGE, places=6)
        self.assertAlmostEqual(syscheck.estimate_colmap_seconds(10, laptop=True) / one,
                               syscheck.COLMAP_LAPTOP_PENALTY, places=6)


class TestPickDevice(unittest.TestCase):
    def test_prefers_viable_over_soft_viable(self):
        soft = {"name": "NVIDIA GeForce RTX 3060", "viable": False,
                "soft_viable": True, "vram_bytes": 10 ** 10}
        good = {"name": "Intel(R) UHD Graphics", "viable": True,
                "soft_viable": True, "vram_bytes": 10 ** 9}
        self.assertIs(syscheck.pick_device([soft, good]), good)

    def test_prefers_discrete_at_the_same_level(self):
        igpu = {"name": "Intel(R) UHD Graphics", "viable": True,
                "soft_viable": True, "vram_bytes": 10 ** 10}
        dgpu = {"name": "NVIDIA GeForce RTX 4060 Laptop GPU", "viable": True,
                "soft_viable": True, "vram_bytes": 10 ** 9}
        self.assertIs(syscheck.pick_device([igpu, dgpu]), dgpu)

    def test_empty(self):
        self.assertIsNone(syscheck.pick_device([]))


class TestCache(unittest.TestCase):
    def setUp(self):
        self._orig = syscheck.CACHE_PATH
        self.tmp = tempfile.mkdtemp(prefix="syscheck_test_")
        syscheck.CACHE_PATH = os.path.join(self.tmp, ".syscheck.json")

    def tearDown(self):
        syscheck.CACHE_PATH = self._orig

    def test_first_run_then_roundtrip(self):
        self.assertTrue(syscheck.is_first_run())
        syscheck.save_cache({"measured_ips": {"标准": 4.2}})
        self.assertFalse(syscheck.is_first_run())
        self.assertAlmostEqual(syscheck.load_cache()["measured_ips"]["标准"], 4.2)

    def test_missing_cache_returns_empty_dict(self):
        self.assertEqual(syscheck.load_cache(), {})

    def test_corrupt_cache_does_not_raise(self):
        with open(syscheck.CACHE_PATH, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(syscheck.load_cache(), {})

    def test_cache_is_written_as_ascii(self):
        """ensure_ascii=True：路径含中文时，写盘再用别的编码读会出错。"""
        syscheck.save_cache({"note": "中文"})
        with open(syscheck.CACHE_PATH, "rb") as f:
            f.read().decode("ascii")   # 不是 ASCII 就会抛异常

    def test_record_measured_ips_ignores_non_positive(self):
        for bad in (0, -1, None):
            syscheck.record_measured_ips("标准", bad)
        self.assertEqual(syscheck.load_cache(), {})
        syscheck.record_measured_ips("标准", 3.14159)
        self.assertAlmostEqual(syscheck.load_cache()["measured_ips"]["标准"], 3.1416, places=3)


class TestChecksSurviveWithoutGpu(unittest.TestCase):
    def test_dependency_check_returns_a_result(self):
        r = syscheck.check_dependencies()
        self.assertEqual(r.name, "依赖包")
        self.assertIn(r.status, (syscheck.OK, syscheck.WARN, syscheck.FAIL))

    def test_disk_check_returns_a_result(self):
        self.assertIn(syscheck.check_disk().status, (syscheck.OK, syscheck.WARN))

    def test_vulkan_check_reports_failure_instead_of_raising(self):
        """枚举失败时应给出结论和提示，不能把异常抛给调用方。"""
        r = syscheck.check_vulkan(devices=[], error="RuntimeError: boom")
        self.assertEqual(r.status, syscheck.FAIL)
        self.assertTrue(r.hint)
        r2 = syscheck.check_vulkan(devices=[], error=None)
        self.assertEqual(r2.status, syscheck.FAIL)
        self.assertTrue(r2.hint)

    def test_colmap_autodetects_both_variants(self):
        """新机器上还没有 quick_gui_config.json，自检必须能自己找到 COLMAP。"""
        tmp = tempfile.mkdtemp(prefix="syscheck_colmap_")
        orig = syscheck.PROJECT_ROOT
        syscheck.PROJECT_ROOT = tmp
        try:
            self.assertEqual(syscheck.check_colmap().status, syscheck.FAIL)
            nocuda = os.path.join(tmp, "tools", "colmap-x64-windows-nocuda")
            os.makedirs(nocuda)
            open(os.path.join(nocuda, "COLMAP.bat"), "w").close()
            r = syscheck.check_colmap()
            self.assertEqual(r.status, syscheck.OK)
            self.assertIn("noCUDA", r.detail)
        finally:
            syscheck.PROJECT_ROOT = orig


if __name__ == "__main__":
    unittest.main()