# -*- coding: utf-8 -*-
"""工作区元数据：COLMAP 结果与训练结果的指纹/记录。

两类记录：
- COLMAP 结果复用：照片 + 最大图像尺寸没变时，可以直接用上次的 sparse/0
- 重复训练识别：照片 + 训练设置都相同时，提醒用户已经产出过模型

只读写工作区里的 JSON，不依赖 Qt 与管线编排，可单独测试。
"""
import hashlib
import json
import os
from datetime import datetime

from dataset_tools import IMAGE_EXTS

# 工作区里记一份「这批照片 + 这个参数」的指纹。COLMAP 是整条管线最耗时的一段，
# 照片和参数都没变时没有理由重跑；但也不能只看 sparse/0 在不在——工作区可能
# 被拿去装了别的照片，复用错的位姿会让训练直接训废。
COLMAP_META_FILE = ".colmap_meta.json"
COLMAP_META_VERSION = 1

# 训练成功后在工作区和模型目录各记一份快照：这组照片 + 这套训练设置已经
# 产出过模型。下次点开始时如果完全一样，先提醒一句，免得白等一遍。
TRAIN_CONFIG_FILE = "train_config.json"
TRAIN_CONFIG_VERSION = 1


def _image_fingerprint(folder):
    """照片集合的轻量指纹：文件名 + 大小 + 修改时间。

    不读内容（128 张也只要几毫秒）：改图、换图、删图都会让这三个字段变化。
    目录读不了返回 None，调用方按「不能复用」处理。
    """
    fp = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if not name.lower().endswith(IMAGE_EXTS):
            continue
        try:
            st = os.stat(os.path.join(folder, name))
        except OSError:
            return None
        fp[name] = [int(st.st_size), int(st.st_mtime_ns)]
    return fp


def write_colmap_meta(ws_dir, img_dir, max_image_size):
    """COLMAP 成功后记下照片指纹与参数，供下次判断能否复用。"""
    fp = _image_fingerprint(img_dir)
    if fp is None:
        return
    meta = {
        "version": COLMAP_META_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "max_image_size": int(max_image_size),
        "image_count": len(fp),
        "images": fp,
    }
    try:
        with open(os.path.join(ws_dir, COLMAP_META_FILE), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=True, indent=2)
    except OSError:
        pass      # 记不下就不复用，不影响本次结果


def colmap_meta_matches(ws_dir, img_dir, max_image_size):
    """返回 (能否复用, 原因)。原因只进日志，帮排查「为什么又重算了」。"""
    sparse_zero = os.path.join(ws_dir, "sparse", "0")
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        if not os.path.isfile(os.path.join(sparse_zero, name)):
            return False, "工作区里没有完整的稀疏重建结果"
    try:
        with open(os.path.join(ws_dir, COLMAP_META_FILE), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return False, "没有上次重建的参数记录"
    if meta.get("version") != COLMAP_META_VERSION:
        return False, "参数记录来自旧版本，无法确认"
    try:
        old_max = int(meta.get("max_image_size"))
    except (TypeError, ValueError):
        return False, "参数记录不完整"
    if old_max != int(max_image_size):
        return False, "最大图像尺寸改过"
    if meta.get("images") != _image_fingerprint(img_dir):
        return False, "照片有变化"
    return True, ""


def _image_digest(folder):
    """照片集合的摘要（不读内容），用于判断「还是上次那批照片」。"""
    fp = _image_fingerprint(folder)
    if fp is None:
        return None
    raw = json.dumps(sorted(fp.items()), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def write_train_config(ws_dir, img_dir, settings, ply, model_dir=None, actual=None):
    """训练成功后记录设置与产物；工作区一份用于识别重复训练，模型目录一份留档。"""
    digest = _image_digest(img_dir)
    if digest is None:
        return
    cfg = {
        "version": TRAIN_CONFIG_VERSION,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "images_digest": digest,
        "settings": settings,
        "ply": os.path.abspath(ply),
        "actual": actual or {},
    }
    for dest in (ws_dir, model_dir):
        if not dest:
            continue
        try:
            with open(os.path.join(dest, TRAIN_CONFIG_FILE), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=True, indent=2)
        except OSError:
            pass      # 记录失败不影响模型本身


def train_config_matches(ws_dir, img_dir, settings):
    """返回 (是否已用相同照片+设置训练过, 记录)。

    模型文件被删掉/搬走时不算「训练过」——否则提示里的「查看已有模型」会是死路。
    """
    try:
        with open(os.path.join(ws_dir, TRAIN_CONFIG_FILE), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return False, None
    if cfg.get("version") != TRAIN_CONFIG_VERSION:
        return False, None
    if cfg.get("settings") != settings:
        return False, None
    if cfg.get("images_digest") != _image_digest(img_dir):
        return False, None
    ply = cfg.get("ply")
    if not ply or not os.path.isfile(ply):
        return False, None
    return True, cfg
