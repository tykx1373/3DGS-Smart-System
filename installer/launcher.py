# -*- coding: utf-8 -*-
"""3DGS 快速管线 —— 安装包启动器。

打包成无控制台的小 exe（约 10 MB）放在安装目录根部，只做一件事：
找到同目录便携环境 env\\vksplat\\pythonw.exe，启动 gui\\quick_gui.py。
GUI 与所有训练逻辑仍由便携 Python 以普通脚本方式运行，避免冻结后
外部子进程（COLMAP / doctor / detect_gpu）的路径问题。
"""
import os
import sys
import subprocess


def app_root():
    # 冻结后 sys.executable 位于安装目录根部；源码运行时位于 installer/ 下
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fail_box(title, text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def main():
    root = app_root()
    pyw = os.path.join(root, "env", "vksplat", "pythonw.exe")
    py = os.path.join(root, "env", "vksplat", "python.exe")
    gui = os.path.join(root, "gui", "quick_gui.py")
    exe = pyw if os.path.exists(pyw) else py
    if not (os.path.exists(exe) and os.path.exists(gui)):
        fail_box("3DGS 快速管线",
                 "安装不完整：未找到便携 Python 或 gui\\quick_gui.py。\n"
                 "请重新运行安装程序并选择修复。")
        return 2
    try:
        # DETACHED_PROCESS 不需要；父进程退出后子进程继续运行即可
        subprocess.Popen([exe, gui], cwd=root, close_fds=True)
    except OSError as e:
        fail_box("3DGS 快速管线", f"启动失败：{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
