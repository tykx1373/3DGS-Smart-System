# -*- coding: utf-8 -*-
"""仓库规则检查：挡住“改一处忘另一处”这类跨文件漂移。

这些不是逻辑测试，而是把以前靠人工反复执行的几条检查固化下来。
全部离线运行，不依赖 git（用户可能是下载 ZIP 而非 clone）。
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 第三方二进制、运行时产物与个人笔记：不参与规则检查
# tests/ 也排除：规则的正则本身含有要找的内容（例如下面那行 parents[\d+]），
# 不排除的话规则会匹配到自己。规则要管的是会发布的文件。
SKIP_DIRS = {".git", "env", "tools", "workspaces", "outputs", "logs", "sample",
             "__pycache__", ".venv", ".idea", ".vscode", "notes", "tests"}


def _iter_files(*suffixes):
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.lower().endswith(suffixes):
                yield os.path.join(base, name)


def _rel(path):
    return os.path.relpath(path, ROOT)


class TestScriptEncoding(unittest.TestCase):
    def test_scripts_are_ascii_only(self):
        """Windows PowerShell 5.1 会把无 BOM 的 .ps1 按 ANSI 解码：
        非 ASCII 变乱码，GBK 前导字节还可能吞掉换行、直接损坏脚本。
        （download_tools.ps1 里那句“keep ASCII-only”的注释就是这个原因。）"""
        offenders = []
        for path in _iter_files(".ps1", ".bat", ".cmd"):
            with open(path, "rb") as f:
                if any(b > 127 for b in f.read()):
                    offenders.append(_rel(path))
        self.assertEqual(offenders, [], "这些脚本含非 ASCII 字节: " + ", ".join(offenders))


class TestPortablePaths(unittest.TestCase):
    def test_no_depth_dependent_path_expression(self):
        """曾用 Path(__file__).resolve().parents[4] 反推项目根：
        Windows 布局下正确，Linux 的 lib/python3.X 多一层就指错，
        env 改成 --name 安装也会错。现在改为向上查找标记目录。"""
        pattern = re.compile(r"parents\[\d+\]")
        offenders = []
        for path in _iter_files(".py", ".ps1"):
            with open(path, encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if pattern.search(line):
                        offenders.append(f"{_rel(path)}:{n}")
        self.assertEqual(offenders, [], "不要再用 parents[N] 反推目录层级: " + ", ".join(offenders))


class TestPackagingConsistency(unittest.TestCase):
    """预编译 .pyd 与文档/环境的一致性。

    注意能力边界：这只能发现“承诺了却不存在”，查不出“文件在但内容是旧的”
    —— cp311 上次就是后者，只能靠重新编译避免。
    """

    PYD_DIR = os.path.join(ROOT, "tools", "vksplat", "vksplat")

    def _shipped_tags(self):
        self.assertTrue(os.path.isdir(self.PYD_DIR), f"缺少 {self.PYD_DIR}")
        tags = set()
        for name in os.listdir(self.PYD_DIR):
            m = re.match(r"vksplat\.(cp\d{3})-win_amd64\.pyd$", name)
            if m:
                tags.add(m.group(1))
        return tags

    def test_readme_promises_only_what_is_shipped(self):
        shipped = self._shipped_tags()
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            documented = set(re.findall(r"(cp\d{3})-win_amd64", f.read()))
        self.assertTrue(documented, "README 没有说明提供哪些预编译版本")
        self.assertTrue(documented <= shipped,
                        f"README 承诺了 {sorted(documented - shipped)}，仓库里却没有")

    def test_environment_python_has_a_prebuilt(self):
        """environment.yaml 固定的 Python 版本必须有对应的预编译 .pyd，
        否则按标准流程装完会走到需要自行编译的路径。"""
        with open(os.path.join(ROOT, "environment.yaml"), encoding="utf-8") as f:
            m = re.search(r"python\s*=\s*3\.(\d+)", f.read())
        self.assertIsNotNone(m, "environment.yaml 里没找到 python=3.x")
        tag = "cp3" + m.group(1).zfill(2)
        self.assertIn(tag, self._shipped_tags(),
                      f"environment.yaml 用 Python 3.{m.group(1)}，但没有 {tag} 的预编译文件")


class TestRemovedBackend(unittest.TestCase):
    """OpenSplat 已从项目移除。

    文档与源码注释里保留历史说明是允许的（README 记录了坐标系来源、
    ROADMAP 记录了取舍原因、C++ 注释解释了约定）。但可执行脚本与配置里
    不能残留引用——删了组件却留下引用，运行时就会以“未定义变量”崩掉，
    这正是以前踩过的坑。
    """

    SCANNED = (".ps1", ".bat", ".cmd", ".json", ".yaml", ".yml")

    def test_no_reference_in_scripts_or_configs(self):
        offenders = []
        for path in _iter_files(*self.SCANNED):
            with open(path, encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if "opensplat" in line.lower():
                        offenders.append(f"{_rel(path)}:{n}")
        self.assertEqual(offenders, [], "脚本/配置里残留了 OpenSplat 引用: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()