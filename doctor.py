# -*- coding: utf-8 -*-
"""doctor：一次性环境健康检查，排查"为什么跑不起来"。

用法：
    python doctor.py
    python doctor.py --images 60 --quality 标准 --steps 15000
    python doctor.py --json          # 供 CI / 脚本使用

退出码：0 = 无阻塞项（可训练）；1 = 存在阻塞项。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.insert(0, os.path.join(PROJECT_ROOT, "gui"))

import syscheck  # noqa: E402

_C = {"ok": "\033[32m", "warn": "\033[33m", "fail": "\033[31m", "dim": "\033[90m", "reset": "\033[0m"}


def _enable_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        pass


def _make_output_safe():
    """stdout 编码不一定是 UTF-8：CI runner 与英文版 Windows 上是 cp1252，
    这时 print 中文会 UnicodeEncodeError 直接把整个进程带走。人读的输出改成
    "编不出的字符替换掉"，显示成 ? 也比中途崩掉强；--json 那边则用
    ensure_ascii=True 输出纯 ASCII，见 main()。"""
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def _resolve(path):
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))


def _load_gui_config():
    cfg_path = os.path.join(PROJECT_ROOT, "gui", "quick_gui_config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description="3DGS 环境自检")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（供脚本/CI 使用）")
    parser.add_argument("--images", type=int, default=None, help="照片数量，用于估算 COLMAP 耗时")
    parser.add_argument("--quality", default="标准", choices=["快速", "标准", "高质量"])
    parser.add_argument("--steps", type=int, default=15000, help="训练步数，用于估算训练耗时")
    args = parser.parse_args(argv)
    _make_output_safe()

    cfg = _load_gui_config()
    colmap = _resolve(cfg.get("colmap_path"))
    vkgs = _resolve(cfg.get("vkgs_exe"))

    results = syscheck.run_all(colmap_path=colmap, vkgs_exe=vkgs)
    summary = syscheck.summarize(colmap_path=colmap, vkgs_exe=vkgs, quality=args.quality,
                                 steps=args.steps, num_images=args.images, results=results)

    if args.json:
        payload = {
            "can_run": summary["can_run"],
            "blockers": summary["blockers"],
            "laptop": summary["laptop"],
            "device": summary["device"],
            "est_train_sec": summary["est_train_sec"],
            "est_colmap_sec": summary["est_colmap_sec"],
            "est_total_sec": summary["est_total_sec"],
            "checks": [
                {"name": r.name, "status": r.status, "detail": r.detail, "hint": r.hint}
                for r in results
            ],
        }
        # ensure_ascii=True：这台机器的 stdout 未必是 UTF-8（CI 是 cp1252、英文版
        # Windows 也是），中文直接打出去会 UnicodeEncodeError。转义成 \uXXXX 后
        # 整份输出是纯 ASCII，经任何编码读写都不会坏。这与配置文件的做法一致。
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0 if summary["can_run"] else 1

    _enable_ansi()
    print()
    print(f"3DGS 环境自检  {_C['dim']}{PROJECT_ROOT}{_C['reset']}")
    print("=" * 64)
    for r in results:
        mark = f"{_C[r.status]}[{syscheck.STATUS_MARK[r.status]:4}]{_C['reset']}"
        print(f"{mark} {r.name:16} {r.detail}")
        if r.hint:
            print(f"       {_C['dim']}-> {r.hint}{_C['reset']}")
    print("=" * 64)

    if summary["can_run"]:
        print(f"{_C['ok']}结论：你的机器可以跑。{_C['reset']}")
        dev = summary["device"]
        if dev:
            kind = "核显" if summary["is_integrated"] else "独显"
            print(f"  设备: {dev['name']}（{kind}，{dev['vram_bytes'] / 1024 ** 3:.1f} GB）")
        if summary["laptop"]:
            print(f"  机型: 笔记本（耗时估算已按 {syscheck.LAPTOP_PENALTY}x 保守放大）")
        if summary["est_total_sec"] is not None:
            note = "实测" if summary["measured"] else "估算"
            print(f"  预计耗时（{note}）: {syscheck.format_duration(summary['est_total_sec'])}"
                  f"（训练 {args.steps} 步，{args.quality}档）")
            print(f"  {_C['dim']}跑过一次后会用实测速度自动修正{_C['reset']}")
    else:
        print(f"{_C['fail']}结论：跑不动。{_C['reset']}")
        if summary["blockers"]:
            print("  阻塞项：" + "、".join(summary["blockers"]))
        else:
            print("  阻塞项：无可用 Vulkan 设备")
    print()
    return 0 if summary["can_run"] else 1


if __name__ == "__main__":
    sys.exit(main())