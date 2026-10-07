# -*- coding: utf-8 -*-
"""quick_gui 里可离线测试的部分：正则解析、配置读取、文件探测。

不需要 GPU 和网络。涉及 Tk 窗口的那一组会在无法建立 Tk 时自动跳过。
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))

import quick_gui as q  # noqa: E402


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


class _FakeVar:
    """最小替身：只有 get()。用来在不建窗口的情况下测 _save_options。"""

    def __init__(self, value=None, raises=False):
        self._value, self._raises = value, raises

    def get(self):
        if self._raises:
            raise ValueError("expected integer but got ''")
        return self._value


class TestSaveOptions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="saveopts_")
        self._orig = q.CONFIG_PATH
        q.CONFIG_PATH = os.path.join(self.tmp, "cfg.json")

    def tearDown(self):
        q.CONFIG_PATH = self._orig

    def _app(self, steps=9000, maximg=1600, steps_raises=False):
        app = _bare_app()
        app.cfg = {}
        app.quality_var = _FakeVar("快速")
        app.res_var = _FakeVar("1/2（images_2）")
        app.lpips_dl_var = _FakeVar(True)
        app.vs_steps_var = _FakeVar(None, raises=True) if steps_raises else _FakeVar(steps)
        app.max_img_var = _FakeVar(maximg)
        return app

    def _saved(self):
        with open(q.CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_writes_every_option(self):
        self._app()._save_options()
        saved = self._saved()
        self.assertEqual(saved["quality"], "快速")
        self.assertEqual(saved["res_choice"], "1/2（images_2）")
        self.assertTrue(saved["lpips_download"])
        self.assertEqual(saved["train_steps"], 9000)
        self.assertEqual(saved["max_image_size"], 1600)

    def test_config_is_written_as_ascii(self):
        """ensure_ascii=True：中文路径在部分环境下会被读错。"""
        self._app()._save_options()
        with open(q.CONFIG_PATH, "rb") as f:
            f.read().decode("ascii")

    def test_half_typed_value_is_skipped_without_corrupting_the_rest(self):
        """输入框被清空时 get() 会抛错：那一次保存跳过，其余项照常写入。"""
        self._app(steps_raises=True)._save_options()
        saved = self._saved()
        self.assertNotIn("train_steps", saved)
        self.assertEqual(saved["max_image_size"], 1600)


def _destroy_root(root):
    """销毁窗口前取消挂起的 after 回调。

    customtkinter 在建根时会排几个 after（update / _windows_set_titlebar_icon），
    直接 destroy 会让它们变成“invalid command name ...”往 stderr 刷噪声。
    """
    try:
        for aid in root.tk.call("after", "info"):
            root.after_cancel(aid)
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def _tk_available():
    try:
        import customtkinter as ctk
        root = ctk.CTk()
        root.withdraw()
        _destroy_root(root)
        return True
    except Exception:
        return False


@unittest.skipUnless(_tk_available(), "需要可用的 Tk 显示环境")
class TestAppRestoresSettings(unittest.TestCase):
    """本轮 bug：_build_ui 末尾无条件调用 _apply_quality_preset()，
    把刚从配置恢复出来的训练步数覆盖成了档位默认值（7777 → 30000）。"""

    def setUp(self):
        # 用 ctk.CTk() 而不是 tkinter.Tk()：生产环境就是这个根，
        # 纯 Tk 根上 CTk 控件会缺属性（block_update_dimensions_event）。
        import customtkinter as ctk
        self.tmp = tempfile.mkdtemp(prefix="cfg_restore_")
        self._orig_cfg = q.CONFIG_PATH
        q.CONFIG_PATH = os.path.join(self.tmp, "cfg.json")
        with open(q.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"quality": "高质量", "train_steps": 7777, "max_image_size": 2048,
                       "res_choice": "1/4（images_4）", "lpips_download": True},
                      f, ensure_ascii=False)
        self.root = ctk.CTk()
        self.root.withdraw()
        self.app = q.QuickSplatApp(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        for win in (getattr(self.app, "adv_window", None),
                    getattr(self.app, "log_window", None)):
            try:
                win.destroy()
            except Exception:
                pass
        _destroy_root(self.root)
        q.CONFIG_PATH = self._orig_cfg

    def test_restored_values_survive_startup(self):
        self.assertEqual(self.app.quality_var.get(), "高质量")
        self.assertEqual(self.app.vs_steps_var.get(), 7777)
        self.assertEqual(self.app.max_img_var.get(), 2048)
        self.assertEqual(self.app.res_var.get(), "1/4（images_4）")
        self.assertTrue(self.app.lpips_dl_var.get())

    def test_quality_hint_is_filled_at_startup(self):
        self.assertTrue(self.app.quality_hint.cget("text"))

    def test_switching_quality_applies_its_default_steps(self):
        self.app.quality_var.set("快速")
        self.assertEqual(self.app.vs_steps_var.get(), q.QUALITY_PRESETS["快速"][0])

    def test_changes_are_written_back(self):
        self.app.max_img_var.set(1200)
        self.app.vs_steps_var.set(9000)
        with open(q.CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["max_image_size"], 1200)
        self.assertEqual(saved["train_steps"], 9000)

    def test_no_duplicate_tooltip_texts(self):
        """一行里的标签、输入框、浏览按钮会各自匹配到同一段说明文字。
        以前没按文字去重，同一行会冒出两三个内容完全一样的「?」。"""
        texts = [t.text for t in getattr(self.app, "_tips", [])]
        self.assertTrue(texts, "应该挂上悬浮说明")
        dupes = {t for t in texts if texts.count(t) > 1}
        self.assertEqual(dupes, set(), f"同一段说明被挂了多次: {dupes}")


if __name__ == "__main__":
    unittest.main()