# -*- coding: utf-8 -*-
"""历史模型仓库：扫描 outputs/、判断路径越界、删除模型目录。

与界面无关；历史模型页只负责展示与交互。
"""
import json
import os
import re
import shutil

from eval_metrics import judge_eval_metrics, load_eval_mean

# 历史模型列表：扫描 outputs/ 用
_HIST_NAME_RE = re.compile(r"^vksplat_(\d+)steps_(fast|standard|high)$", re.I)
_HIST_QUALITY_ZH = {"fast": "快速", "standard": "标准", "high": "高质量"}


def scan_history_models(outputs_dir):
    """扫描 outputs/ 下的模型目录，返回按修改时间倒序的模型信息列表。

    只有目录里至少有一个 .ply 才算一次成功产出（训练中途崩溃只留下
    config/train.json 的目录不进列表）。每个元素：
      name        目录名
      dir         绝对路径
      ply         主模型 PLY 路径（优先 splat.ply）
      splat       同名 .splat 分享版路径（没有则为 None，可由 PLY 现转）
      mtime       目录修改时间戳
      steps/quality  训练步数与档位（从目录名或 config.json 推）
      metrics      eval.json 的 mean（可能为 None）
      level        good/mid/bad/none（复用指标判定）
      size_mb      目录内 PLY 总大小
    """
    items = []
    try:
        names = os.listdir(outputs_dir)
    except OSError:
        return items
    for name in names:
        d = os.path.join(outputs_dir, name)
        if not os.path.isdir(d):
            continue
        try:
            plys = [f for f in os.listdir(d) if f.lower().endswith(".ply")]
        except OSError:
            continue
        if not plys:
            continue
        ply = os.path.join(d, "splat.ply") if "splat.ply" in plys \
            else os.path.join(d, sorted(plys)[0])
        try:
            splats = [f for f in os.listdir(d) if f.lower().endswith(".splat")]
        except OSError:
            splats = []
        want = name + ".splat"
        splat = os.path.join(d, want) if want in splats \
            else (os.path.join(d, sorted(splats)[0]) if splats else None)
        size_mb = 0.0
        for f in plys:
            try:
                size_mb += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
        size_mb = round(size_mb / 1024 / 1024, 1)

        steps, quality = None, None
        m = _HIST_NAME_RE.match(name)
        if m:
            steps, quality = int(m.group(1)), m.group(2).lower()
        else:
            try:
                with open(os.path.join(d, "config.json"), encoding="utf-8") as f:
                    cfg = json.load(f)
                steps = int(cfg.get("train_steps"))
            except (OSError, ValueError, TypeError):
                steps = None

        metrics = load_eval_mean(os.path.join(d, "eval.json"))
        _verdict, level, _rows = judge_eval_metrics(metrics)
        items.append({
            "name": name,
            "dir": d,
            "ply": ply,
            "splat": splat,
            "mtime": os.path.getmtime(d),
            "steps": steps,
            "quality": _HIST_QUALITY_ZH.get(quality) if quality else None,
            "metrics": metrics,
            "level": level,
            "size_mb": size_mb,
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def is_path_within(path, parent):
    """path 是否位于 parent 目录之内（防误删：历史列表只允许删 outputs/ 内目录）。"""
    try:
        path = os.path.abspath(path)
        parent = os.path.abspath(parent)
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def delete_history_model(model_dir, outputs_dir):
    """删除一个历史模型目录；越界或失败返回 (False, 原因)。"""
    if not is_path_within(model_dir, outputs_dir) or not os.path.isdir(model_dir):
        return False, "路径不在模型输出目录内"
    try:
        shutil.rmtree(model_dir)
        return True, ""
    except OSError as e:
        return False, str(e)
