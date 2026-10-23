# -*- coding: utf-8 -*-
"""eval.json 的指标读取与判读。

纯数据逻辑：不依赖 Qt、不依赖管线状态，界面和 diagnostics 都可以直接用。
"""
import json


def load_eval_mean(json_path):
    """安全读取 eval.json 的 mean 指标；文件缺失/损坏返回 None。"""
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        mean = data.get("mean")
        return mean if isinstance(mean, dict) else None
    except Exception:
        return None


def judge_eval_metrics(mean_obj):
    """把 eval.json 的 mean 指标转成给用户看的人话。

    返回 (判定文案, 等级, 明细行)。等级 good / mid / bad / none，
    PSNR 是主判定（最直观）。LPIPS 权重未下载时 eval.json 里没有这两项，
    缺哪行就不显示哪行。明细行形如 (指标名, 数值串, 判读)。
    """
    if not isinstance(mean_obj, dict):
        return "未拿到评测指标", "none", []
    try:
        psnr = float(mean_obj["psnr"])
    except (KeyError, TypeError, ValueError):
        return "未拿到评测指标", "none", []
    try:
        ssim = float(mean_obj.get("ssim"))
    except (TypeError, ValueError):
        ssim = None

    if psnr >= 25:
        verdict, level = "质量不错", "good"
    elif psnr >= 20:
        verdict, level = "质量一般，可尝试更高档位或更多训练步数", "mid"
    else:
        verdict, level = "质量偏低：检查照片是否清晰、重叠是否足够，或提高档位重训", "bad"

    rows = [("PSNR", f"{psnr:.2f} dB",
             "像素误差，越高越好（>25 不错，<20 通常有问题）")]
    if ssim is not None:
        rows.append(("SSIM", f"{ssim:.3f}",
                     "结构相似度，越高越好（0~1）"))
    for key, label in (("lpips_vgg", "LPIPS VGG"), ("lpips_alex", "LPIPS Alex")):
        try:
            v = float(mean_obj[key])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((label, f"{v:.3f}", "感知相似度，越低越好"))
    return verdict, level, rows
