"""检测 Vulkan 设备，优先选择独显，返回设备 ID 和类型。

用法: python detect_gpu.py <spv_dir>
输出 JSON: {"device_id": 0, "is_integrated": false, "name": "NVIDIA GeForce RTX 4060 Laptop GPU"}
"""
import sys
import json
import re
import subprocess

def detect(spv_dir):
    # 运行一个只初始化的短脚本，捕获设备列表输出
    code = f"""
import vksplat, os
v = vksplat.VkSplat()
try:
    v.initialize({spv_dir!r}, -1)
except Exception as e:
    pass
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True
    )
    output = result.stdout + result.stderr
    # 去掉 ANSI 颜色码
    ansi = re.compile(r'\x1b\[[0-9;]*m')
    output = ansi.sub('', output)

    # 解析设备列表，格式: [0] NVIDIA GeForce RTX 4060 Laptop GPU - VIABLE
    devices = []
    for line in output.splitlines():
        m = re.match(r"\[(\d+)\]\s+(.+?)\s+-\s+(VIABLE|UNSUPPORTED)", line)
        if m:
            dev_id = int(m.group(1))
            name = m.group(2).strip()
            viable = m.group(3) == "VIABLE"
            if viable:
                devices.append((dev_id, name))

    if not devices:
        # 没解析到，返回默认
        return {"device_id": -1, "is_integrated": False, "name": "unknown"}

    # 判断独显 vs 核显
    integrated_keywords = ["intel", "uhd", "iris", "radeon graphics", "vega", "apu"]
    discrete_keywords = ["nvidia", "geforce", "rtx", "gtx", "amd radeon", "radeon rx", "radeon pro"]

    def is_integrated(name):
        low = name.lower()
        if any(k in low for k in discrete_keywords):
            return False
        if any(k in low for k in integrated_keywords):
            return True
        # 无法判断，默认按核显处理（保守）
        return True

    # 优先选独显
    discrete = [(d, n) for d, n in devices if not is_integrated(n)]
    if discrete:
        dev_id, name = discrete[0]
        return {"device_id": dev_id, "is_integrated": False, "name": name}

    # 没有独显，选第一个可用设备
    dev_id, name = devices[0]
    return {"device_id": dev_id, "is_integrated": is_integrated(name), "name": name}

if __name__ == "__main__":
    spv_dir = sys.argv[1] if len(sys.argv) > 1 else "shader/generated"
    info = detect(spv_dir)
    print(json.dumps(info))
