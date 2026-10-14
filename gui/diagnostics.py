# -*- coding: utf-8 -*-
"""诊断：把"出了什么问题"讲清楚，并把排查所需的材料打包。

两块内容共用一份出处：
* explain_failure()  把子进程的退出码与输出翻译成「原因 + 建议」，避免只丢一个退出码；
* build_zip()        收集最近日志、环境自检结果和配置，打成 zip 供外发排查。

本模块不依赖 GUI，纯文件与子进程操作，可单独导入测试。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime

# 每个日志文件最多收这么多行（取尾部），避免整包过大
LOG_TAIL_LINES = 3000
MAX_LOG_FILES = 3

# 安装版（根目录有启动器）与开发仓库给出不同的修复指引
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_MODE = os.path.isfile(os.path.join(PROJECT_ROOT, "3DGS-Studio.exe"))
REPAIR_HINT = ("请重新运行安装程序并选择修复" if INSTALL_MODE
               else "请重新运行 download_tools.bat")


# ------------------------------------------------------- 失败原因解读 ----
# 正则都对应 VkSplat / COLMAP 里真实存在的报错原文（见 tools/vksplat/vksplat/src），
# 顺序即优先级：越具体的放前面。命中一条即返回，避免一次报错配出互相矛盾的建议。
_FAILURE_HINTS = (
    # RAM 与 VRAM 两条必须互斥：VkSplat 原文分别是
    # "Failed to allocate staging buffer memory ... out of RAM" 和
    # "Failed to allocate buffer memory ... out of VRAM"，注意前者多了 staging。
    (r"Failed to allocate staging buffer memory|running out of RAM",
     "系统内存不够（照片解码后的数据放不下）",
     "关掉其它占内存的程序；图像分辨率改小一档后重试"),
    (r"Failed to allocate buffer memory|Negative VRAM|out of VRAM",
     "显存不够，分配失败",
     "质量档位调低一档、图像分辨率改小，把「图片缓存」改成 cpu，并关掉其它占用显卡的程序"),
    (r"Failed to load image:",
     "训练要用的照片打不开，通常是照片张数和 COLMAP 重建时对不上",
     "重新选择照片文件夹（工作区会按新的张数重建），或删掉该工作区后重跑"),
    (r"Failed to load mask:",
     "掩码文件（mask）缺失或读不到",
     "检查工作区里的 masks/ 目录，或改用不带掩码的训练"),
    (r"(cameras|images|points3D)\.(bin|txt) not found in",
     "工作区里的 sparse/0 不完整，COLMAP 没有正常跑完",
     "在高级选项里点「只用 COLMAP（空间定位）」重跑一次，再回来训练"),
    (r"Failed to (open|read) file:.*\.spv|Failed to create shader module",
     "Vulkan 着色器文件读不到或编译失败：多为安装不完整、路径含中文等非 ASCII 字符，"
     "或显卡驱动过旧",
     ("把项目移到纯英文路径（例如 D:\\3DGS）后重试；仍失败就" + REPAIR_HINT
      + "，并更新显卡驱动（需 Vulkan 1.3+）")),
    (r"Cannot open file:",
     "读不到 COLMAP 的输出文件：重建可能没跑完，或目录权限/路径有问题",
     "删掉该工作区的 sparse 目录后重跑空间定位；避免把项目放在需要管理员权限的目录"),
    (r"ModuleNotFoundError.*\b(torch|torchvision|torchmetrics)\b|"
     r"No module named '(torch|torchvision|torchmetrics)'",
     "环境里缺少 torch / torchvision / torchmetrics，训练结束后的评测会失败",
     (REPAIR_HINT if INSTALL_MODE
      else "在 env/vksplat 里补装（pip install torch torchvision torchmetrics），"
           "或直接重新运行 download_tools.bat")),
    (r"CUDA out of memory",
     "评测阶段显存不够（评测本应走 CPU，出现该报错通常是环境被装成了 CUDA 版 torch）",
     (REPAIR_HINT if INSTALL_MODE
      else "确认 env/vksplat 里装的是 CPU 版 torch（PyPI 的 Windows 轮子即为 CPU 版），"
           "或重跑 download_tools.bat")),
)

# Windows 常见退出码 -> 说明。这些数字直接看毫无意义，至少给个方向。
_EXIT_CODE_HINTS = {
    3221225477: ("进程崩溃：访问违例（0xC0000005）",
                 "多半与显卡驱动或显存有关：更新驱动、把质量档位调低后重试"),
    3221225725: ("进程崩溃：栈溢出（0xC00000FD）", "导出诊断包发出来，便于定位"),
    3221225786: ("进程被中断（0xC000013A，通常是按了 Ctrl+C 或被关闭）",
                 "重新运行即可；若是点「停止」导致的，可忽略"),
}

_COLMAP_FALLBACK = (
    "COLMAP 没能完成这一步",
    "照片重叠不够或纹理太少是常见原因：同一位置多拍几张、相邻照片重叠 60% 以上，"
    "然后删掉工作区的 database.db 与 sparse 目录重跑")


def explain_failure(returncode, output, colmap=False):
    """把退出码 + 输出翻译成人话：返回 (原因, 建议)，识别不出时返回 None。

    colmap=True 时，认不出具体报错就给一条 COLMAP 专属的兜底建议。
    """
    text = output or ""
    for pattern, cause, advice in _FAILURE_HINTS:
        if re.search(pattern, text, re.IGNORECASE):
            return cause, advice
    exit_hint = _EXIT_CODE_HINTS.get(int(returncode or 0))
    if exit_hint:
        return exit_hint
    if colmap:
        return _COLMAP_FALLBACK
    return None


# ------------------------------------------------------------- 打包 ----
def redact(text, home=None):
    """日志里会带用户名路径，外发前统一替换掉。"""
    home = home or os.path.expanduser("~")
    if not home or not text:
        return text
    for variant in (home, home.replace("\\", "\\\\"), home.replace("\\", "/")):
        text = text.replace(variant, "%USERPROFILE%")
    return text


def read_text(path, encoding="utf-8"):
    try:
        with open(path, encoding=encoding, errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def tail_lines(path, limit=LOG_TAIL_LINES, encoding="utf-8"):
    """读文件尾部的若干行。文件不存在或读不动时返回空串。"""
    try:
        with open(path, encoding=encoding, errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return ""
    if len(lines) > limit:
        lines = [f"...（前 {len(lines) - limit} 行已省略，完整内容见本机 logs/）...\n"] + lines[-limit:]
    return "".join(lines)


def collect_logs(logs_dir, limit=MAX_LOG_FILES):
    """取最近修改的几个日志文件，返回 {文件名: 尾部内容}。"""
    if not os.path.isdir(logs_dir):
        return {}
    names = [n for n in os.listdir(logs_dir) if n.lower().endswith(".log")]
    names.sort(key=lambda n: os.path.getmtime(os.path.join(logs_dir, n)), reverse=True)
    out = {}
    for n in names[:limit]:
        out[n] = tail_lines(os.path.join(logs_dir, n))
    return out


def load_gui_config(project_root):
    path = os.path.join(project_root, "gui", "quick_gui_config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def run_doctor(project_root, python_exe=None, timeout=90):
    """调用 doctor.py --json。失败返回 None——诊断包照常导出，不因它失败。"""
    doctor = os.path.join(project_root, "doctor.py")
    if not os.path.isfile(doctor):
        return None
    try:
        r = subprocess.run([python_exe or sys.executable, doctor, "--json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=project_root)
    except Exception:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def _resolve(project_root, path):
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(project_root, path))


def build_report(project_root, doctor_json=None, cfg=None):
    """拼出给人看的纯文本报告。"""
    cfg = cfg or {}
    out = [
        "3DGS 诊断报告",
        "=" * 56,
        f"生成时间   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"项目目录   {project_root}",
        f"Python     {sys.version.split()[0]}  ({sys.executable})",
        f"平台       {sys.platform}",
        "",
        "--- 工具路径 ---",
    ]
    for label, key in (("COLMAP", "colmap_path"),
                       ("VkSplat Python", "vksplat_python"),
                       ("VKGS 查看器", "vkgs_exe")):
        raw = cfg.get(key) or ""
        resolved = _resolve(project_root, raw)
        if not raw:
            out.append(f"{label}：（未配置）")
        else:
            exists = "存在" if resolved and os.path.exists(resolved) else "缺失"
            out.append(f"{label}：{raw}  [{exists}]")

    out += ["", "--- 训练参数 ---"]
    for label, key in (("质量档位", "quality"), ("训练步数", "train_steps"),
                       ("图像分辨率", "res_choice"), ("最大图片尺寸", "max_image_size"),
                       ("允许下载 LPIPS 权重", "lpips_download")):
        out.append(f"{label}：{cfg.get(key, '（未设置）')}")

    out += ["", "--- 环境自检（doctor）---"]
    if not doctor_json:
        out.append("doctor.py 未能执行，请在本机运行：python doctor.py")
    else:
        out.append(f"结论         {'可以跑' if doctor_json.get('can_run') else '跑不动'}")
        if doctor_json.get("blockers"):
            out.append(f"阻塞项       {'、'.join(doctor_json['blockers'])}")
        dev = doctor_json.get("device") or {}
        if dev:
            vram = (dev.get("vram_bytes") or 0) / 1024 ** 3
            out.append(f"设备         {dev.get('name')}（显存 {vram:.1f} GB）")
        out.append(f"笔记本       {doctor_json.get('laptop')}")
        for c in doctor_json.get("checks", []):
            out.append(f"[{str(c.get('status', '')).upper():4}] {c.get('name')}: {c.get('detail')}")
            if c.get("hint"):
                out.append(f"       -> {c['hint']}")

    out += [
        "",
        "--- 说明 ---",
        "本包内含：本报告、doctor.json、GUI 配置、最近几个日志文件的尾部。",
        "其中的用户名路径已替换为 %USERPROFILE%。",
        "请把整个 zip 发给开发者。",
        "",
    ]
    return "\n".join(out)


def default_dest(project_root):
    """默认落盘位置：桌面，取不到就用项目目录。"""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    base = desktop if os.path.isdir(desktop) else project_root
    return os.path.join(base, f"3dgs_diag_{datetime.now():%Y%m%d_%H%M%S}.zip")


def build_zip(dest_zip, project_root, python_exe=None):
    """收集诊断材料并写出 zip，返回 zip 路径。"""
    cfg = load_gui_config(project_root)
    doctor_json = run_doctor(project_root, python_exe)

    files = {"report.txt": build_report(project_root, doctor_json, cfg)}
    if doctor_json is not None:
        files["doctor.json"] = json.dumps(doctor_json, ensure_ascii=False, indent=2)
    cfg_text = read_text(os.path.join(project_root, "gui", "quick_gui_config.json"))
    if cfg_text:
        files["quick_gui_config.json"] = cfg_text
    for name, text in collect_logs(os.path.join(project_root, "logs")).items():
        files[f"logs/{name}"] = text

    parent = os.path.dirname(os.path.abspath(dest_zip))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, redact(text))
    return dest_zip