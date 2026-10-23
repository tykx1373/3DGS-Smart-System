# -*- coding: utf-8 -*-
"""数据集与采集质量：照片格式、匹配器选择、定位率/清晰度预检。

这里只做纯计算与文件解析，不依赖 Qt，也不依赖管线编排；pipeline_core
与界面都从这里取规则，避免同一套阈值散落在多处。
"""
import os
import re

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

# exhaustive 匹配是 O(n²)：超过约 100 张后（尤其 noCUDA 版）会慢到不可用。
SEQUENTIAL_MATCHER_THRESHOLD = 100
# mapper 后注册率（成功定位的照片占比）低于此值时提示补拍——
# 提前诊断比等训练阶段报 "Failed to load image" 好得多。
LOW_REGISTRATION_RATE = 0.7

# ---- 采集质量预检 ----
# 注册率低于 LOW_REGISTRATION_RATE 属于「多半要失败」，介于两者之间算提醒。
CAPTURE_WARN_RATE = 0.85
BLUR_CHECK_MAX_EDGE = 640    # 清晰度打分前先缩图，控制耗时
BLUR_RATIO = 0.4             # 低于本批中位数 40% 的算「发虚/细节太少」
BLUR_ABS_FLOOR = 12.0        # 绝对下限：整批都很糊时也不至于一张都不报
BLUR_MAX_LIST = 12           # 最多列几张，多了没人看
BLUR_MIN_SAMPLES = 8         # 少于 8 张时中位数没有意义，跳过模糊判定
CAPTURE_ASK_TIMEOUT = 300    # 等用户回答补拍与否的秒数上限
MIN_PHOTOS_RECOMMENDED = 30  # 少于这个张数，稀疏重建很容易失败（选照片时就提醒）


def pick_colmap_matcher(n_imgs):
    """按照片数选匹配器：大图集用 sequential（要求文件名按拍摄顺序命名，
    手机相机默认如此），小图集仍用最稳的 exhaustive。"""
    return "sequential" if n_imgs > SEQUENTIAL_MATCHER_THRESHOLD else "exhaustive"


def parse_registered_images(analyzer_output):
    """从 `colmap model_analyzer` 输出解析 Registered images 数；解析不到返回 None。

    注意 COLMAP 把这类统计写到 **stderr**，调用方要把 stdout 和 stderr 拼起来再传进来。
    """
    m = re.search(r"Registered images:\s*(\d+)", analyzer_output or "")
    return int(m.group(1)) if m else None


def _walk_images_bin(blob, pt_bytes):
    """按 COLMAP images.bin 布局走一遍；走不通就返回 None。

    每个 2D 点在 COLMAP 3.x 占 32 字节（含 point2D_id），4.x 起只存
    x / y / point3D_id 共 24 字节，所以调用方两种尺寸都要试一次。
    只有「文件名全是可打印 ASCII」且「刚好走到文件末尾」才算解析成功，
    宁可返回 None 什么都不提醒，也不能拿半截错位的结果去让用户补拍。
    """
    import struct
    try:
        (n_img,), off = struct.unpack_from("<q", blob, 0), 8
        names = set()
        for _ in range(n_img):
            off += 4 + 8 * 7 + 4          # image_id + qvec(4×f64) + tvec(3×f64) + camera_id
            end = blob.index(b"\x00", off)
            raw = blob[off:end]
            if not raw or not all(32 <= c < 127 for c in raw):
                return None
            names.add(raw.decode("ascii"))
            off = end + 1
            (n2d,), off = struct.unpack_from("<Q", blob, off), off + 8
            off += n2d * pt_bytes
        return names if off == len(blob) else None
    except (OSError, ValueError, IndexError, struct.error):
        return None


def read_registered_names(sparse_zero):
    """读 COLMAP sparse/0/images.bin，返回定位成功的照片文件名集合；解析不出返回 None。

    images.bin 里只写定位成功的图像，所以「全部照片名 − 这个集合」就是没对上的那些。
    检查失败绝不能影响训练，调用方一律按 None 跳过。
    """
    try:
        with open(os.path.join(sparse_zero, "images.bin"), "rb") as f:
            blob = f.read()
    except OSError:
        return None
    for pt_bytes in (24, 32):
        names = _walk_images_bin(blob, pt_bytes)
        if names is not None:
            return names
    return None


def blur_scores(folder, names):
    """给照片打清晰度分（缩小图上算 Laplacian 方差），按分数升序返回 [(文件名, 分数)]。

    用 IMREAD_REDUCED_GRAYSCALE_8 按 1/8 解码，上百张也就一两秒。
    cv2 用不了或某张读不出来一律跳过——只做提醒，不能影响主流程。
    """
    try:
        import cv2
    except ImportError:
        return []
    out = []
    for name in names:
        try:
            img = cv2.imread(os.path.join(folder, name), cv2.IMREAD_REDUCED_GRAYSCALE_8)
            if img is None:
                continue
            h, w = img.shape[:2]
            edge = max(h, w)
            if edge > BLUR_CHECK_MAX_EDGE:
                s = BLUR_CHECK_MAX_EDGE / float(edge)
                img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                                 interpolation=cv2.INTER_AREA)
            out.append((name, float(cv2.Laplacian(img, cv2.CV_64F).var())))
        except Exception:
            continue
    out.sort(key=lambda x: x[1])
    return out


def pick_blurry(scores, ratio=BLUR_RATIO, floor=BLUR_ABS_FLOOR, cap=BLUR_MAX_LIST):
    """从清晰度分数里挑出「明显比同批照片差」的几张。

    只用绝对阈值会在白墙/天空这类低纹理场景大面积误报，所以以本批中位数为基准；
    floor 只保证「整批都很糊」时也能报出几张。
    """
    if len(scores) < BLUR_MIN_SAMPLES:
        return []
    vals = sorted(s for _n, s in scores)
    bar = max(floor, ratio * vals[len(vals) // 2])
    return [(n, s) for n, s in scores if s < bar][:cap]


def build_capture_report(all_names, registered_names, blurry):
    """汇总成采集质量报告；没什么可提醒的（或信息不全）时返回 None。"""
    n_total = len(all_names or ())
    if not n_total or registered_names is None:
        return None
    missing = sorted(set(all_names) - set(registered_names))
    rate = (n_total - len(missing)) / float(n_total)
    if rate < LOW_REGISTRATION_RATE:
        level = "bad"
    elif rate < CAPTURE_WARN_RATE or blurry:
        level = "warn"
    else:
        return None
    return {"n_total": n_total, "n_registered": n_total - len(missing),
            "rate": rate, "missing": missing, "blurry": list(blurry or ()),
            "level": level}


def photo_precheck_text(n_imgs, blurry, min_imgs=MIN_PHOTOS_RECOMMENDED):
    """选完照片时的本地预检结论：只说能确定的事，措辞留余地。

    清晰度低有两种原因（拍糊了 / 场景本来就没纹理），这里分不开，
    所以只能说"这几张值得再看一眼"，不能断言照片不合格。
    """
    if n_imgs < min_imgs:
        return (f"只有 {n_imgs} 张照片，比建议的 {min_imgs} 张少：绕着物体多拍几圈，"
                f"相邻照片重叠 60% 以上更容易成功。", "warn")
    if blurry:
        head = "、".join(n for n, _s in blurry[:6])
        more = f" 等 {len(blurry)} 张" if len(blurry) > 6 else ""
        return (f"{n_imgs} 张照片里有 {len(blurry)} 张偏虚或细节很少：{head}{more}。"
                f"（白墙、天空这类本来细节就少，不一定是问题）", "warn")
    return (f"{n_imgs} 张照片清晰度都正常，可以开始生成。", "ok")


def capture_report_text(report, max_names=8):
    """把报告写成新手能照做的句子：只说现象和怎么办，不出「注册率」这类词。"""
    def _listing(items):
        head = "、".join(items[:max_names])
        return head + (f" 等 {len(items)} 张" if len(items) > max_names else "")

    lines = []
    if report["missing"]:
        lines.append(f"有 {len(report['missing'])} 张照片没能对上位置："
                     f"{_listing(report['missing'])}。")
    if report["blurry"]:
        lines.append("这几张看起来发虚或没什么细节："
                     f"{_listing([n for n, _s in report['blurry']])}。")
    lines.append("")
    lines.append("怎么办：")
    # 补拍建议按「有没有照片没对上」给，而不是只看等级：75% 注册率同样该绕一圈重拍。
    if report["missing"]:
        lines.append("· 绕着同一个物体再多走一圈补拍，每张跟上一张重叠一大半；")
    if report["blurry"]:
        lines.append("· 拿稳了再按快门，别边走边拍；光线暗就开灯或换个时间；")
    lines.append("· 白墙、天空这类没细节的画面少拍，多拍旁边有特征的部分。")
    return "\n".join(lines)
