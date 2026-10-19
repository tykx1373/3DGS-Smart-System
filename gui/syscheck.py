# -*- coding: utf-8 -*-
"""环境自检：GUI 首次运行向导与 doctor CLI 共用。

判定原则：机器能不能跑，由 vksplat 自身的 C++ 判定给出（enumerate_devices），
与训练时选设备的逻辑完全一致，避免出现第二份判定标准。

本模块不依赖 GUI，可直接 import，也可独立运行（python syscheck.py）。
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VKSPLAT_SRC = os.path.join(PROJECT_ROOT, "tools", "vksplat", "vksplat")
CACHE_PATH = os.path.join(PROJECT_ROOT, ".syscheck.json")
# 安装版根目录有启动器；开发仓库没有。缺失组件时的修复提示据此区分
INSTALL_MODE = os.path.isfile(os.path.join(PROJECT_ROOT, "3DGS-Studio.exe"))
REPAIR_HINT = ("请重新运行安装程序并选择修复" if INSTALL_MODE
               else "请重新运行 download_tools.bat")

OK, WARN, FAIL = "ok", "warn", "fail"

STATUS_COLOR = {OK: "#22c55e", WARN: "#f59e0b", FAIL: "#ef4444"}
STATUS_LABEL = {OK: "通过", WARN: "注意", FAIL: "失败"}
STATUS_MARK = {OK: "OK", WARN: "WARN", FAIL: "FAIL"}

# 耗时估算的笔记本惩罚系数：只作用于"首次估算"，训练过一次后用实测 it/s 覆盖。
# 笔记本受功耗/散热限制，比同型号台式机慢很多，这里保守取高。
LAPTOP_PENALTY = 2.5
COLMAP_LAPTOP_PENALTY = 2.0
COLMAP_SEC_PER_IMAGE = 4.0

# 保守基准：标准档(images_2)下每秒训练步数，越低越保守
_BASE_IT_PER_SEC = {
    "discrete_high": 6.0,
    "discrete_mid": 3.0,
    "discrete_low": 1.5,
    "integrated": 0.8,
    "unknown": 1.0,
}
_QUALITY_FACTOR = {"快速": 1.3, "标准": 1.0, "高质量": 0.75}

_INTEGRATED_KEYS = ("intel", "uhd", "iris", "vega", "radeon graphics", "apu")
_DISCRETE_KEYS = ("nvidia", "geforce", "rtx", "gtx", "radeon rx", "radeon pro", "arc a")


@dataclass
class CheckResult:
    name: str
    status: str          # ok / warn / fail
    detail: str = ""
    hint: str = ""


# --------------------------------------------------------------- utilities ----
# GUI 由 pythonw 启动，子进程默认各弹一个控制台窗口（用户看到的就是"每跑一步闪一个
# 黑框"）。所有纯后台探测一律不显示窗口；需要用户看的（VKGS 查看器、资源管理器）不加。
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW)


def _powershell(script, timeout=12):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def is_integrated(name):
    """按名称判断是否核显。未知时保守按核显处理。"""
    low = (name or "").lower()
    if any(k in low for k in _DISCRETE_KEYS):
        return False
    if any(k in low for k in _INTEGRATED_KEYS):
        return True
    return True


def format_duration(seconds):
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"约 {seconds} 秒"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"约 {minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    return f"约 {hours} 小时 {minutes} 分钟"


def format_driver_version(dev):
    """解码 driverVersion → x.y.z。NVIDIA 使用自有位域，其余按 Vulkan 规范。"""
    v = int(dev.get("driver_version") or 0)
    if int(dev.get("vendor_id") or 0) == 0x10DE:  # NVIDIA
        return f"{(v >> 22) & 0x3FF}.{(v >> 14) & 0xFF}.{(v >> 6) & 0xFF}"
    return f"{(v >> 22) & 0x3FF}.{(v >> 12) & 0x3FF}.{v & 0xFFF}"


def format_api_version(dev):
    v = int(dev.get("api_version") or 0)
    return f"{(v >> 22) & 0x7F}.{(v >> 12) & 0x3FF}.{v & 0xFFF}"


# ------------------------------------------------------------ vulkan devices ----
_devices_cache = None
_devices_error = None


def enumerate_vulkan_devices(force=False):
    """返回 (devices, error)。devices 为 vksplat 给出的物理设备能力列表。"""
    global _devices_cache, _devices_error
    if _devices_cache is not None and not force:
        return _devices_cache, _devices_error

    devices, error = [], None
    try:
        if VKSPLAT_SRC not in sys.path:
            sys.path.insert(0, VKSPLAT_SRC)
        import vksplat
        devices = list(vksplat.VkSplat().enumerate_devices())
    except Exception as e:  # 驱动缺失 / .pyd 不匹配 / 无 Vulkan 设备
        error = f"{type(e).__name__}: {e}"

    _devices_cache, _devices_error = devices, error
    return devices, error


def pick_device(devices):
    """在候选设备中挑一个"最好"的：可训练 > 勉强可训练 > 其它；独显优先、显存大优先。"""
    if not devices:
        return None

    def rank(d):
        if d.get("viable"):
            level = 2
        elif d.get("soft_viable"):
            level = 1
        else:
            level = 0
        return (level, 0 if is_integrated(d.get("name", "")) else 1, int(d.get("vram_bytes") or 0))

    return max(devices, key=rank)


# ------------------------------------------------------------ laptop detect ----
_laptop_cache = None


def detect_laptop(devices=None):
    """是否笔记本：有电池 / 机身类型为笔记本 / GPU 名称含 Laptop。"""
    global _laptop_cache
    if _laptop_cache is not None:
        return _laptop_cache

    laptop = False
    try:
        r = _powershell("(Get-CimInstance Win32_Battery | Measure-Object).Count")
        if r.returncode == 0 and int((r.stdout or "0").strip() or 0) > 0:
            laptop = True
    except Exception:
        pass

    if not laptop:
        try:
            r = _powershell("(Get-CimInstance Win32_SystemEnclosure).ChassisTypes")
            if r.returncode == 0:
                for tok in re.findall(r"\d+", r.stdout or ""):
                    if int(tok) in (8, 9, 10, 11, 12, 14):  # notebook..subnotebook, docking
                        laptop = True
                        break
        except Exception:
            pass

    if not laptop:
        if devices is None:
            devices, _ = enumerate_vulkan_devices()
        for d in devices or []:
            if "laptop" in (d.get("name", "") or "").lower():
                laptop = True
                break

    _laptop_cache = laptop
    return laptop


# --------------------------------------------------------- time estimation ----
def _device_tier(name):
    if is_integrated(name):
        return "integrated"
    low = (name or "").lower()
    if re.search(r"rtx\s*(20|30|40|50)\d{2}", low) or "quadro rtx" in low:
        return "discrete_high"
    if "gtx" in low or "rtx" in low or "arc a" in low or "quadro" in low or "radeon pro" in low:
        return "discrete_mid"
    return "discrete_low"


def estimate_train_seconds(device, quality="标准", steps=15000, measured_ips=None, laptop=None):
    """估算训练秒数。measured_ips 为实测每秒步数（跑过一次后写入缓存），优先级最高。"""
    if measured_ips and measured_ips > 0:
        ips = measured_ips
    else:
        tier = _device_tier((device or {}).get("name", ""))
        ips = _BASE_IT_PER_SEC.get(tier, 1.0) * _QUALITY_FACTOR.get(quality, 1.0)
        if laptop is None:
            laptop = detect_laptop()
        if laptop:
            ips /= LAPTOP_PENALTY
    return steps / max(ips, 1e-6)


def estimate_colmap_seconds(num_images, laptop=None):
    if not num_images:
        return None
    if laptop is None:
        laptop = detect_laptop()
    sec = num_images * COLMAP_SEC_PER_IMAGE
    return sec * (COLMAP_LAPTOP_PENALTY if laptop else 1.0)


# ------------------------------------------------------------------- checks ----
def check_python():
    v = sys.version_info
    detail = f"{sys.version.split()[0]}  ({sys.executable})"
    if v < (3, 9):
        return CheckResult("Python 版本", FAIL, detail, "需要 Python 3.9 及以上（推荐 3.10）")
    if v[:2] != (3, 10):
        return CheckResult("Python 版本", WARN, detail,
                           "预编译 vksplat 只提供 cp310 / cp311；其它版本需自行编译")
    return CheckResult("Python 版本", OK, detail)


def check_vksplat_module():
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    pyds = glob.glob(os.path.join(VKSPLAT_SRC, "vksplat.cp*-win_amd64.pyd"))
    if not pyds:
        return CheckResult("vksplat 模块", FAIL, "未找到预编译 .pyd",
                           REPAIR_HINT + ("，或自行编译 tools/vksplat/vksplat" if not INSTALL_MODE else ""))
    names = [os.path.basename(p) for p in pyds]
    if not any(tag in n for n in names):
        return CheckResult("vksplat 模块", FAIL, f"ABI 不匹配，现有 {', '.join(names)}",
                           f"当前 Python 为 {tag}，请改用 3.10/3.11 环境或重新编译")
    if VKSPLAT_SRC not in sys.path:
        sys.path.insert(0, VKSPLAT_SRC)
    try:
        import vksplat  # noqa: F401
        return CheckResult("vksplat 模块", OK, f"{tag} 已加载")
    except Exception as e:
        return CheckResult("vksplat 模块", FAIL, f"import 失败: {e}",
                           REPAIR_HINT)


def check_dependencies():
    required = {"numpy": "numpy", "cv2": "opencv-python-headless", "tqdm": "tqdm"}
    optional = {"torch": "torch", "torchvision": "torchvision", "torchmetrics": "torchmetrics"}
    missing_req, missing_opt = [], []
    for mod, pkg in required.items():
        try:
            if importlib.util.find_spec(mod) is None:
                missing_req.append(pkg)
        except Exception:
            missing_req.append(pkg)
    for mod, pkg in optional.items():
        try:
            if importlib.util.find_spec(mod) is None:
                missing_opt.append(pkg)
        except Exception:
            missing_opt.append(pkg)
    if missing_req:
        return CheckResult("依赖包", FAIL, "缺少: " + ", ".join(missing_req),
                           "在 env/vksplat 中 pip install 缺失的包")
    if missing_opt:
        return CheckResult("依赖包", WARN, f"缺少: {', '.join(missing_opt)}",
                           "缺少会让训练结束后的评测崩溃（退出码 1）；缺 torchvision 时 LPIPS 无法构建")
    return CheckResult("依赖包", OK, "numpy / opencv / tqdm / torch / torchvision / torchmetrics 齐全")


def _vulkan_fail_reasons(d):
    reasons = []
    if not d.get("valid_subgroup_size"):
        reasons.append("subgroup<32")
    if not d.get("valid_group_count"):
        reasons.append("工作组数量不足")
    if not d.get("valid_group_size"):
        reasons.append("工作组尺寸不足")
    if not d.get("valid_shared_size"):
        reasons.append("共享内存不足")
    if not d.get("valid_queue_family"):
        reasons.append("缺少计算队列")
    if not d.get("has_int16"):
        reasons.append("不支持 int16")
    if not d.get("has_int64"):
        reasons.append("不支持 int64")
    if not d.get("has_float32_atomic_add"):
        reasons.append("不支持 float32 原子加")
    return reasons


def check_vulkan(devices=None, error=None):
    if devices is None:
        devices, error = enumerate_vulkan_devices()
    if error:
        return CheckResult("Vulkan 设备", FAIL, f"枚举失败: {error}",
                           "确认显卡驱动已安装并支持 Vulkan 1.2+（Windows 一般随驱动自带）")
    if not devices:
        return CheckResult("Vulkan 设备", FAIL, "未发现任何 Vulkan 物理设备",
                           "更新显卡驱动；笔记本可在 BIOS/驱动面板中启用独立显卡")
    best = pick_device(devices)
    detail = (f"{best['name']}（{best['vram_bytes'] / 1024 ** 3:.1f} GB，"
              f"Vulkan {format_api_version(best)}，驱动 {format_driver_version(best)}）")
    if best.get("viable"):
        return CheckResult("Vulkan 设备", OK, detail)
    if best.get("soft_viable"):
        return CheckResult("Vulkan 设备", WARN, detail,
                           "勉强可用：缺少部分特性，训练可能不稳定，不建议跑高质量档")
    return CheckResult("Vulkan 设备", FAIL, detail,
                       "不满足要求: " + "、".join(_vulkan_fail_reasons(best)))


def check_cuda():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return CheckResult("CUDA (nvidia-smi)", WARN, "未找到 nvidia-smi",
                           "非 NVIDIA 显卡属正常；COLMAP 将使用 noCUDA 版本（效果相同，稍慢）")
    try:
        r = _run([exe, "--query-gpu=driver_version", "--format=csv,noheader"], timeout=15)
    except Exception as e:
        return CheckResult("CUDA (nvidia-smi)", WARN, f"执行失败: {e}", "COLMAP 将使用 noCUDA 版本")
    if r.returncode != 0:
        return CheckResult("CUDA (nvidia-smi)", WARN, "nvidia-smi 返回非零", "COLMAP 将使用 noCUDA 版本")
    version = (r.stdout or "").strip().splitlines()
    return CheckResult("CUDA (nvidia-smi)", OK, f"驱动 {version[0].strip()}" if version else "可用")


def check_colmap(colmap_path=None):
    candidates = [colmap_path] if colmap_path else []
    candidates += [
        os.path.join(PROJECT_ROOT, "tools", "colmap-x64-windows-cuda", "COLMAP.bat"),
        os.path.join(PROJECT_ROOT, "tools", "colmap-x64-windows-nocuda", "COLMAP.bat"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            variant = "noCUDA" if "nocuda" in c.lower() else "CUDA"
            try:
                rel = os.path.relpath(c, PROJECT_ROOT)
            except ValueError:
                rel = c
            return CheckResult("COLMAP", OK, f"{rel}（{variant}）")
    return CheckResult("COLMAP", FAIL, "未找到 COLMAP.bat",
                       REPAIR_HINT + (" 下载 COLMAP" if not INSTALL_MODE else ""))


def find_vkgs_exe():
    tools = os.path.join(PROJECT_ROOT, "tools")
    if os.path.isdir(tools):
        for root, _dirs, files in os.walk(tools):
            if "vk_gaussian_splatting.exe" in files:
                return os.path.join(root, "vk_gaussian_splatting.exe")
    return None


def check_vkgs(vkgs_exe=None):
    p = vkgs_exe if (vkgs_exe and os.path.isfile(vkgs_exe)) else find_vkgs_exe()
    if p:
        try:
            return CheckResult("VKGS 查看器", OK, os.path.relpath(p, PROJECT_ROOT))
        except ValueError:
            return CheckResult("VKGS 查看器", OK, p)
    return CheckResult("VKGS 查看器", WARN, "未找到 vk_gaussian_splatting.exe",
                       REPAIR_HINT + (" 下载" if not INSTALL_MODE else "")
                       + "；缺失仅影响第③步查看结果")


def check_disk(min_free_gb=5.0):
    try:
        _total, _used, free = shutil.disk_usage(PROJECT_ROOT)
    except Exception as e:
        return CheckResult("磁盘空间", WARN, f"无法读取: {e}")
    free_gb = free / 1024 ** 3
    detail = f"{PROJECT_ROOT} 所在盘剩余 {free_gb:.1f} GB"
    if free_gb < min_free_gb:
        return CheckResult("磁盘空间", WARN, detail, f"建议至少保留 {min_free_gb:.0f} GB")
    return CheckResult("磁盘空间", OK, detail)


def check_tdr_delay(devices=None):
    """Windows TDR：GPU 单个命令挂起超过 TdrDelay 秒会被驱动重置（默认 2 秒）。
    核显跑 Vulkan 长 kernel 时尤其容易触发，表现为训练崩溃 / 设备丢失。"""
    if sys.platform != "win32":
        return CheckResult("TdrDelay", OK, "非 Windows，不适用")
    if devices is None:
        devices, _ = enumerate_vulkan_devices()
    best = pick_device(devices)
    integrated = is_integrated(best.get("name", "")) if best else True

    value = None
    try:
        import winreg
        sub_key = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub_key) as k:
            try:
                raw, _typ = winreg.QueryValueEx(k, "TdrDelay")
                value = int(raw)
            except FileNotFoundError:
                value = None  # 未设置：系统按默认 2 秒处理
    except Exception:
        value = None  # 读不到也不阻断自检，按默认对待

    seconds = value if value is not None else 2
    detail = f"TdrDelay = {seconds} 秒" if value is not None else "TdrDelay 未设置（默认 2 秒）"
    fix_hint = (
        "核显长训练容易触发显卡重置。修复：注册表定位到 "
        r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers，"
        "新建/修改 DWORD（32 位）值 TdrDelay，基数选十进制填 60，重启后生效。")
    if integrated:
        if seconds < 10:
            return CheckResult("TdrDelay", WARN, detail, fix_hint)
        return CheckResult("TdrDelay", OK, detail)
    # 独显：默认值一般够用，不制造噪声阻断自检的"全部通过"
    if seconds >= 10:
        return CheckResult("TdrDelay", OK, detail)
    return CheckResult("TdrDelay", OK, detail + "（独显通常够用）")


def run_all(colmap_path=None, vkgs_exe=None):
    return [
        check_python(),
        check_vksplat_module(),
        check_dependencies(),
        check_vulkan(),
        check_tdr_delay(),
        check_cuda(),
        check_colmap(colmap_path),
        check_vkgs(vkgs_exe),
        check_disk(),
    ]


# -------------------------------------------------------------- conclusion ----
def summarize(colmap_path=None, vkgs_exe=None, quality="标准", steps=15000, num_images=None,
              results=None, devices=None, error=None):
    """汇总自检结论 + 耗时估算。返回 dict。"""
    if results is None:
        results = run_all(colmap_path=colmap_path, vkgs_exe=vkgs_exe)
    if devices is None:
        devices, error = enumerate_vulkan_devices()
    best = pick_device(devices)
    laptop = detect_laptop(devices)

    blockers = [r.name for r in results if r.status == FAIL]
    can_run = not blockers and best is not None

    cache = load_cache()
    measured = (cache.get("measured_ips") or {}).get(quality)
    est_train = estimate_train_seconds(best, quality, steps, measured_ips=measured, laptop=laptop) if best else None
    est_colmap = estimate_colmap_seconds(num_images, laptop=laptop)
    est_total = None
    if est_train is not None:
        est_total = est_train + (est_colmap or 0)

    return {
        "results": results,
        "blockers": blockers,
        "can_run": can_run,
        "device": best,
        "is_integrated": is_integrated(best["name"]) if best else None,
        "laptop": laptop,
        "measured": bool(measured),
        "est_train_sec": est_train,
        "est_colmap_sec": est_colmap,
        "est_total_sec": est_total,
    }


# ------------------------------------------------------------------- cache ----
def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
    except Exception:
        pass


def is_first_run():
    return not os.path.exists(CACHE_PATH)


def record_check(devices=None):
    """把本次检查结论写入缓存（供"环境是否变化需重检"与耗时估算使用）。"""
    if devices is None:
        devices, _ = enumerate_vulkan_devices()
    dev = pick_device(devices)
    cache = load_cache()
    cache["last_check"] = datetime.now().isoformat(timespec="seconds")
    cache["laptop"] = detect_laptop(devices)
    if dev:
        cache["gpu_name"] = dev["name"]
        cache["gpu_viable"] = bool(dev.get("viable"))
        cache["gpu_vram_bytes"] = int(dev.get("vram_bytes") or 0)
    save_cache(cache)
    return cache


def record_measured_ips(quality, ips):
    """训练中/结束后记录实测每秒步数，供下次估算使用。"""
    if not ips or ips <= 0:
        return
    cache = load_cache()
    measured = cache.get("measured_ips") or {}
    measured[quality] = round(float(ips), 4)
    cache["measured_ips"] = measured
    save_cache(cache)


if __name__ == "__main__":
    summary = summarize()
    for res in summary["results"]:
        print(f"[{STATUS_MARK[res.status]:4}] {res.name:16} {res.detail}"
              + (f"  -> {res.hint}" if res.hint else ""))
    print()
    if summary["can_run"]:
        print(f"结论：可以跑。预计耗时 {format_duration(summary['est_total_sec'])}"
              f"（笔记本系数已计入：{'是' if summary['laptop'] else '否'}）")
    else:
        print("结论：跑不动。原因：" + "、".join(summary["blockers"] or ["无可用 Vulkan 设备"]))