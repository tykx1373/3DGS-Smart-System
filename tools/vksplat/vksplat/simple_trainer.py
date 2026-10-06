# 基于 Huawei VkSplat (Apache License 2.0) 修改，原始许可证见同目录上级 LICENSE。
# Modifications (this project, Apache-2.0): checkpoint save/resume via PLY,
# PROGRESS output for GUI, STOP-file based graceful stop, UTF-8 safe image I/O
# (cv2.imread/imwrite fail on non-ASCII Windows paths), LPIPS skipped when its
# pretrained weights are not cached (avoids a ~760 MB download hang).
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Literal, Optional

import os
import math
import random
import numpy as np
import cv2

import json
from tqdm import tqdm
from datetime import datetime
from time import perf_counter

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext


# --- UTF-8 safe OpenCV I/O -------------------------------------------------
# cv2.imread / cv2.imwrite resolve the path through the Windows ANSI codepage,
# so on a system whose ACP is not UTF-8 a non-ASCII path (e.g. a project folder
# named "科研立项") silently fails - imread returns None, imwrite returns False.
# These wrappers let Python (which handles Unicode paths) do the file I/O and
# only encode/decode the bytes in memory.
def _imread_utf8(path, flags=cv2.IMREAD_COLOR):
    with open(path, "rb") as f:
        buf = np.frombuffer(f.read(), dtype=np.uint8)
    return cv2.imdecode(buf, flags)


def _imwrite_utf8(path, img):
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return True


# Device used for actual training, -1 for auto
# At start of training, a list of devices and their IDs are printed in terminal
TRAIN_DEVICE = -1


@dataclass
class TrainerConfig:

    enable_viewer: bool = False  # can affect resource usage, disable during benchmark
    viewer_port: int = 7007

    output_dir: str = "D:\\Desktop\\3DGS\\tools for 3DGS\\vksplat\\outputs"
    output_ply: str = "splat.ply"
    train_steps: int = 15000
    save_train_renders: bool = False

    # dataset
    dataset_dir: str = "D:\\Desktop\\3DGS\\tools for 3DGS\\south-building\\test_ws"
    image_dir: str = "../images"
    mask_dir: Optional[str] = None
    sparse_dir: str = "sparse/0"
    eval_interval: int = 8

    image_cache_device: Literal['cpu', 'gpu'] = 'cpu'

    global_scale: float = 1.0
    init_scale: float = 1.0  # 0.1 for MCMC
    init_opacity: float = 0.1  # 0.5 for MCMC

    # densification strategy
    # to use MCMC, you must train with MCMCTrainerConfig instead of only changing this field to reproduce paper results
    strategy: Literal['default', 'mcmc'] = "default"

    # optimizer
    max_steps: int = 30000  # used for lr scheduling, not the same as train_steps
    ssim_lambda: float = 0.2  # 0.2 in most works, increase for better visual quality (SSIM/LPIPS) but potentially worse PSNR
    means_lr: float = 1.6e-4  # adjust for large scenes
    means_lr_final: float = 1.6e-6  # adjust for large scenes
    features_dc_lr: float = 0.0025
    features_rest_lr: float = 0.0025 / 20
    opacities_lr: float = 0.05  # 0.05 in gsplat, 0.025 in inria; 0.025 seems better for Mip-NeRF 360 outdoor scenes with default densification
    scales_lr: float = 0.005
    quats_lr: float = 0.001
    scale_reg: float = 0.0  # 0.01 for MCMC
    opacity_reg: float = 0.0  # 0.01 for MCMC

    # strategy
    refine_start_iter: int = 500
    refine_stop_iter: int = 15000  # 25000 for MCMC
    refine_every: int = 100

    # default strategy
    prune_opa: float = 0.005
    grow_grad2d: float = 0.0002  # 0.0002, increase if VRAM is tight
    grow_scale3d: float = 0.01
    grow_scale2d: float = 0.05  # 0.05 in gsplat, none (inf) in inria
    prune_scale3d: float = 0.1
    prune_scale2d: float = 0.15
    refine_scale2d_stop_iter: int = 0  # 0 in gsplat, always (inf) in inria, 4000 in nerfstudio
    reset_every: int = 3000  # 3000 in most works
    stop_reset_at: int = -1  # -1 (inf) in most works, 12000 in older version of nerfstudio
    pause_refine_after_reset: int = 0  # 0 in inria and gsplat, num_train+refine_every in nerfstudio, leave -1 to use nerfstudio

    # MCMC strategy
    noise_lr: float = 5e5
    min_opacity: float = 0.005
    grow_factor: float = 1.05
    cap_max: int = 1000000


@dataclass
class MCMCTrainerConfig(TrainerConfig):

    strategy: Literal['default', 'mcmc'] = "mcmc"

    init_scale: float = 0.1
    init_opacity: float = 0.5

    opacities_lr: float = 0.05

    scale_reg: float = 0.01
    opacity_reg: float = 0.01  # adjust for large scenes

    refine_stop_iter: int = 25000


def join_dir(dir0, dir1):
    dir = os.path.join(dir0, dir1)
    if not dir.endswith(os.path.sep):
        dir += os.path.sep
    return dir


CHECKPOINT_FILE = "checkpoint.ply"
CHECKPOINT_STEP_FILE = "checkpoint.ply.step"
CHECKPOINT_INTERVAL = 1000  # 每 1000 步存一次
STOP_FILE = "STOP"  # GUI 安全停止标志文件

# write_ply 输出的 SH 字段排列（内部 flat 索引 -> 文件列偏移）
_PLY_SH_PERMUTE = [0, 1, 2, 3, 18, 33, 4, 19, 34, 5, 20, 35, 6, 21, 36,
                   7, 22, 37, 8, 23, 38, 9, 24, 39, 10, 25, 40, 11, 26, 41,
                   12, 27, 42, 13, 28, 43, 14, 29, 44, 15, 30, 45, 16, 31, 46,
                   17, 32, 47]


def save_checkpoint(module, step, output_dir):
    """用 write_ply 保存完整高斯状态，断点续训用。"""
    ckpt_path = os.path.join(output_dir, CHECKPOINT_FILE)
    try:
        module.write_ply(ckpt_path)
        with open(os.path.join(output_dir, CHECKPOINT_STEP_FILE), "w") as f:
            f.write(str(step))
        return True
    except Exception as e:
        PRINT(f"[WARN] checkpoint 保存失败: {e}")
        return False


def _parse_ply_vertices(path):
    """解析 binary_little_endian PLY，返回 (N, n_props) float32 数组。"""
    with open(path, "rb") as f:
        header = []
        while True:
            line = f.readline()
            if not line:
                raise ValueError("PLY header 不完整")
            header.append(line)
            if line.strip() == b"end_header":
                break
        n_verts = 0
        n_props = 0
        for l in header:
            if l.startswith(b"element vertex"):
                n_verts = int(l.split()[-1])
            elif l.startswith(b"property float"):
                n_props += 1
        data = np.fromfile(f, dtype="<f4", count=n_verts * n_props)
    return data.reshape(n_verts, n_props)


def load_checkpoint(module, output_dir):
    """如果存在 checkpoint，恢复高斯参数和起始步数。"""
    ckpt_path = os.path.join(output_dir, CHECKPOINT_FILE)
    step_path = os.path.join(output_dir, CHECKPOINT_STEP_FILE)
    if not (os.path.isfile(ckpt_path) and os.path.isfile(step_path)):
        return 0
    try:
        step = int(open(step_path).read().strip())
        data = _parse_ply_vertices(ckpt_path)  # (N, 59): xyz(3) sh(48) opacity scale(3) rot(4)
        if data.shape[1] != 59:
            raise ValueError(f"意外的 PLY 字段数: {data.shape[1]}")
        n = len(data)
        xyz_ws = np.ascontiguousarray(data[:, 0:3], dtype=np.float32)
        # 反变换 SH 排列
        sh_flat = np.zeros((n, 48), dtype=np.float32)
        for i, col in enumerate(_PLY_SH_PERMUTE):
            sh_flat[:, i] = data[:, 3 + col]
        sh_coeffs = np.ascontiguousarray(sh_flat.reshape(n, 16, 3))
        rotations = np.ascontiguousarray(data[:, 55:59], dtype=np.float32)
        # write_ply 存的是 log(scale) 和 logit(opacity)，反变换回去
        scales = np.ascontiguousarray(np.exp(data[:, 52:55]), dtype=np.float32)
        opacities = np.ascontiguousarray(
            1.0 / (1.0 + np.exp(-data[:, 51:52])), dtype=np.float32)
        # 注意：必须按 C++ 签名顺序位置传参 (xyz, rotations, scales, opacities, sh)。
        # .def 里声明的 py::arg 名字与 C++ 参数顺序错位，不能用关键字传参！
        module.set_gauss_params(xyz_ws, rotations, scales, opacities, sh_coeffs)
        PRINT(f"[INFO] 从 checkpoint 恢复，继续训练 step={step}")
        return step
    except Exception as e:
        PRINT(f"[WARN] checkpoint 加载失败，从头开始: {e}")
        return 0


def remove_checkpoint(output_dir):
    for f in (CHECKPOINT_FILE, CHECKPOINT_STEP_FILE, "checkpoint.npz"):
        try:
            p = os.path.join(output_dir, f)
            if os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass


def PRINT(*args, **kargs):
    print(*args, **kargs, flush=True)


def train(config: TrainerConfig, resume_output_dir: str = None):
    # from build import vksplat  # or build.Debug, build.Release for MSVC
    import vksplat

    # create and initialize module
    module = vksplat.VkSplat()
    spv_dir = join_dir(os.path.dirname(__file__), 'shader')
    module.initialize(spv_dir, TRAIN_DEVICE)

    # load training data
    train_meta = module.set_train_config(asdict(config))
    for key, value in train_meta.items():
        if isinstance(value, np.ndarray):
            train_meta[key] = value.tolist()
    PRINT()

    # save config
    os.makedirs(config.output_dir, exist_ok=True)
    with open(os.path.join(config.output_dir, 'config.json'), 'w') as fp:
        json.dump(asdict(config), fp, indent=4)
    with open(os.path.join(config.output_dir, 'train.json'), 'w') as fp:
        json.dump(train_meta, fp, indent=4)  # do this so we can get relevant info if training crashes

    # 尝试从 checkpoint 恢复
    ckpt_dir = resume_output_dir if resume_output_dir else config.output_dir
    start_step = load_checkpoint(module, ckpt_dir)
    # 清理上次残留的 STOP 文件
    stale_stop = os.path.join(ckpt_dir, STOP_FILE)
    if os.path.isfile(stale_stop):
        try:
            os.remove(stale_stop)
        except Exception:
            pass

    lock = nullcontext()
    module_alive = True
    if config.enable_viewer:
        from viewer.server import ViewerServer
        import asyncio
        import threading
        lock = threading.Lock()

        def render(c2w, fx, fy, cx, cy, w, h, camera_model):
            R = c2w[:3, :3]
            T = c2w[:3, 3:]
            R = R * [[1.0, -1.0, -1.0]]
            R_inv = R.T
            T_inv = -R_inv @ T
            w2c = np.eye(4)
            w2c[:3, :3] = R_inv
            w2c[:3, 3:4] = T_inv

            with lock:
                if not module_alive:
                    exit(0)
                module.set_uniforms(
                    3, w2c,
                    h, w, fx, fy, cx, cy,
                    camera_model.lower() == "fisheye"
                )
                module.forward()

                rgba = np.round(np.clip(module.pixel_state, 0.0, 1.0)*255.0).astype(np.uint8)

            return {
                "rgb": rgba[:, :, :3],
                "alpha": (~rgba[:, :, 3:]).repeat(3, -1)
            }

        def get_progress(self):
            elapsed = perf_counter() - t0
            avg_latency = elapsed / step
            remaining_steps = config.train_steps - step
            eta = remaining_steps * avg_latency
            return {
                "step": step,
                "total_steps": config.train_steps,
                "elapsed_time": elapsed,
                "eta": eta,
                "latency_ms": avg_latency * 1000 if avg_latency else None,
            }

        async def start_viewer_server():
            server = ViewerServer(
                render_fn=render,
                progress_fn=get_progress,
                http_host="0.0.0.0",
                http_port=config.viewer_port,
                open_browser=False,
            )
            server.start()
            server.wait()

        async def start_viewer():
            await asyncio.create_task(start_viewer_server())

        thread = threading.Thread(target=lambda: asyncio.run(start_viewer()), daemon=True)
        thread.start()

    # train
    t0 = perf_counter()
    shuffle_idx = list(range(module.num_train))
    for step in tqdm(range(start_step, config.train_steps), "Training", initial=start_step, total=config.train_steps):
        if step > 0 and step % len(shuffle_idx) == 0:
            # random.seed(step)
            random.shuffle(shuffle_idx)
        image_idx = shuffle_idx[step % len(shuffle_idx)]
        with lock:
            module.train_step(image_idx, step)
        # 用户请求安全停止：当场保存进度并干净退出
        if os.path.isfile(os.path.join(ckpt_dir, STOP_FILE)):
            save_checkpoint(module, step + 1, ckpt_dir)
            try:
                os.remove(os.path.join(ckpt_dir, STOP_FILE))
            except Exception:
                pass
            PRINT(f"STOPPED: 已安全停止训练，进度保存至 step={step + 1}，下次训练将从此处继续。")
            with lock:
                module.cleanup()
            os._exit(0)
        # 进度标记，GUI 解析用
        if (step + 1) % 100 == 0 or (step + 1) == config.train_steps:
            elapsed = perf_counter() - t0
            eta = elapsed / (step - start_step + 1) * (config.train_steps - step - 1) if step > start_step else 0
            num_splats = len(module.opacities)
            # PROGRESS: 当前步/总步数/已用时秒/预计剩余秒/高斯数
            PRINT(f"PROGRESS: {step + 1}/{config.train_steps} {elapsed:.1f} {eta:.1f} {num_splats}")
        # 定期存 checkpoint
        if (step + 1) % CHECKPOINT_INTERVAL == 0:
            save_checkpoint(module, step + 1, ckpt_dir)
    t1 = perf_counter()
    with lock:
        num_splats = len(module.opacities)
    vram_usage = module.get_vram_usage()
    peak_vram_usage = module.get_peak_vram_usage()
    PRINT(f"Time elapsed: {t1-t0:.1f} seconds")
    PRINT(f"VRAM usage: {vram_usage/1024**3:.2f} GiB")
    PRINT(f"Num splats: {num_splats}")
    with open(os.path.join(config.output_dir, 'train.json'), 'w') as fp:
        train_json = {
            'num_splats': num_splats,
            'time_elapsed': t1-t0,
            'vram': vram_usage,
            'peak_vram': peak_vram_usage,
            'breakdown': module.get_timing_breakdown(),
            'vram_breakdown': module.get_vram_breakdown(),
            "train_images": [module.get_train_image_path(i) for i in range(module.num_train)],
            "val_images": [module.get_val_image_path(i) for i in range(module.num_val)],
        }
        train_json.update(train_meta)
        json.dump(train_json, fp, indent=4)
    if True:
        PRINT("\nTiming breakdown:")
        total_t = 0.0
        for item, dt, n in sorted([
                (item, dt, n) for item, (n, dt) in module.get_timing_breakdown().items() if n != 0
                ], key=lambda x: -x[1]):
            PRINT(item, '-', f"{n}, {dt:.3f} secs")
            if not item.startswith('_'):
                total_t += dt
        PRINT(f"Total - {total_t:.3f} / {t1-t0:.3f} secs")

        PRINT("\nVRAM breakdown:")
        def print_vram(label, nb):
            PRINT(label, '-', f"{nb/1024**2:.1f} MiB" if nb >= 1024**2 else f"{nb/1024:.1f} KiB")
        total_vram = 0
        for item, nb in sorted([
                (item, nb) for item, nb in module.get_vram_breakdown().items() if nb != 0
                ], key=lambda x: -x[1]):
            total_vram += nb
            print_vram(item, nb)
        print_vram('Total', total_vram)
        print_vram('Total (queried)', vram_usage)
        print_vram('Peak (queried)', peak_vram_usage)
    PRINT()

    PRINT("Writing PLY")
    with lock:
        module.write_ply(config.output_ply)
    # 训练正常结束，清理 checkpoint（不再需要恢复）
    remove_checkpoint(ckpt_dir)
    PRINT()

    # save renders

    def save_one_image(pixel_data, path):
        im = pixel_data.copy()
        im[:, :, 3] = 1.0 - im[:, :, 3]
        im = np.round(65535 * np.clip(im, 0, 1)).astype(np.uint16)
        # im = np.round(255 * np.clip(im, 0, 1)).astype(np.uint8)
        im = cv2.cvtColor(im, cv2.COLOR_BGRA2RGB)
        _imwrite_utf8(path, im)

    def save_all_images(rendered_images, split):
        with ThreadPoolExecutor() as executor:
            futures = []
            for i, (path, pixel_data) in enumerate(rendered_images):
                future = executor.submit(save_one_image, pixel_data, path)
                futures.append(future)
            for future in tqdm(futures, f"Saving {split} images"):
                future.result()
        PRINT()

    if config.save_train_renders:
        rendered_images = []
        for i in tqdm(range(module.num_train), "Rendering train images"):
            with lock:
                module.render_train(i)
                path = os.path.join(config.output_dir, f'train_{i:05d}.png')
                rendered_images.append((path, module.pixel_state))
        save_all_images(rendered_images, "train")

    rendered_images = []
    for i in tqdm(range(module.num_val), "Rendering val images"):
        with lock:
            module.render_val(i)
            path = os.path.join(config.output_dir, f'val_{i:05d}.png')
            rendered_images.append((path, module.pixel_state))
    save_all_images(rendered_images, "val")

    # free memory
    with lock:
        module_alive = False
        module.cleanup()


LPIPS_VGG_FILE = "vgg16-397923af.pth"
LPIPS_ALEX_FILE = "alexnet-owt-7be5be79.pth"


def _lpips_weights_ready():
    """LPIPS 依赖 vgg16 / alexnet 的预训练权重。torchvision 会在首次构造 LPIPS 时
    从 download.pytorch.org 拉约 760 MB，国内常长时间无响应，看起来像卡死。
    这里只查本地缓存，不做任何联网。"""
    try:
        import torch.hub
        ckpt = os.path.join(torch.hub.get_dir(), "checkpoints")
        return all(os.path.isfile(os.path.join(ckpt, f))
                   for f in (LPIPS_VGG_FILE, LPIPS_ALEX_FILE))
    except Exception:
        return False


def eval(config: TrainerConfig):
    try:
        import torch
        from torchmetrics.image import PeakSignalNoiseRatio, StructuralSimilarityIndexMeasure
        from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity
        device = "cuda" if torch.cuda.is_available() else 'cpu'
    except:
        PRINT("Evaluation skipped (failed to import torch and/or torchmetrics.image).")
        return

    psnr_fun = PeakSignalNoiseRatio(data_range=1.0).to(device)
    ssim_fun = StructuralSimilarityIndexMeasure(data_range=1.0).to(device)

    # LPIPS 是"学习型"指标，必须用预训练网络。权重不在本地时会联网下载约 760 MB，
    # 网络差就长时间无响应。默认只在权重已缓存时才计算，避免把一次成功的训练
    # 拖成"看起来失败"；需要联网下载时显式设 VKSPLAT_LPIPS_DOWNLOAD=1。
    use_lpips = _lpips_weights_ready()
    allow_download = os.environ.get("VKSPLAT_LPIPS_DOWNLOAD", "").strip().lower() \
        in ("1", "true", "yes", "on")
    if not use_lpips and allow_download:
        use_lpips = True
        PRINT("LPIPS 权重未缓存：按 VKSPLAT_LPIPS_DOWNLOAD 联网下载（约 760 MB，可能很慢）...")
    elif not use_lpips:
        try:
            import torch.hub
            ckpt_dir = os.path.join(torch.hub.get_dir(), "checkpoints")
        except Exception:
            ckpt_dir = "<torch hub checkpoints>"
        PRINT("跳过 LPIPS：预训练权重不在本地缓存，未开启下载。")
        PRINT(f"  权重目录: {ckpt_dir}")
        PRINT(f"  需要文件: {LPIPS_VGG_FILE} (527.8 MB)、{LPIPS_ALEX_FILE} (233.1 MB)")
        PRINT("  想启用 LPIPS，任选一种：")
        PRINT("    1) 把上面两个文件放进该目录（可从已有缓存的机器直接拷贝）")
        PRINT("    2) 设环境变量 VKSPLAT_LPIPS_DOWNLOAD=1 后重跑，联网下载")
        PRINT("  PSNR / SSIM 不受影响，照常输出。")
        PRINT()

    lpips_vgg_fun = lpips_alex_fun = None
    if use_lpips:
        lpips_vgg_fun = LearnedPerceptualImagePatchSimilarity(net_type="vgg", normalize=False).to(device)
        lpips_alex_fun = LearnedPerceptualImagePatchSimilarity(net_type="alex", normalize=True).to(device)

    def load_image(filename):
        im = _imread_utf8(filename, cv2.IMREAD_UNCHANGED)
        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        im = torch.from_numpy(im).float().to(device) / \
            (65535 if im.dtype == np.uint16 else 255)
        return im[None].permute(0, 3, 1, 2)

    def load_mask(filename):
        im = _imread_utf8(filename, cv2.IMREAD_COLOR)
        if len(im.shape) == 3:
            im = im[..., 0]
        im = torch.from_numpy(im).float().to(device) / 255.0
        return im[None, :, :, None].permute(0, 3, 1, 2)

    all_metrics = []
    obj = []

    with open(os.path.join(config.output_dir, 'train.json'), 'r') as fp:
        image_names = json.load(fp)['val_images']
    for i, image_name in tqdm(enumerate(image_names), "Running eval", len(image_names)):

        im_train = image_name["image_path"]
        im_render = os.path.join(config.output_dir, f'val_{i:05d}.png')
        im, ref = load_image(im_render), load_image(im_train)

        # TODO: better way consistent with existing benchmarks
        if 'mask_path' in image_name and image_name['mask_path'] is not None:
            mask = load_mask(image_name['mask_path'])
            im, ref = im * mask, ref * mask

        metrics = [psnr_fun(im, ref).item(), ssim_fun(im, ref).item()]
        entry = {
            'im_train': im_train,
            'im_render': im_render,
            'psnr': metrics[0],
            'ssim': metrics[1],
        }
        if use_lpips:
            metrics += [lpips_vgg_fun(im, ref).item(), lpips_alex_fun(im, ref).item()]
            entry['lpips_vgg'] = metrics[2]
            entry['lpips_alex'] = metrics[3]
        all_metrics.append(metrics)
        obj.append(entry)

    mean = np.mean(all_metrics, axis=0)
    psnr, ssim = float(mean[0]), float(mean[1])
    PRINT(f"PSNR: {psnr:.2f}")
    PRINT(f"SSIM: {ssim:.3f}")
    mean_obj = {'psnr': psnr, 'ssim': ssim}
    if use_lpips:
        lpips_vgg, lpips_alex = float(mean[2]), float(mean[3])
        PRINT(f"LPIPS VGG: {lpips_vgg:.3f}")  # used by inria
        PRINT(f"LPIPS Alex: {lpips_alex:.3f}")  # used by gsplat
        mean_obj['lpips_vgg'] = lpips_vgg
        mean_obj['lpips_alex'] = lpips_alex
    PRINT()

    obj = {
        'mean': mean_obj,
        'images': obj
    }
    with open(os.path.join(config.output_dir, 'eval.json'), 'w') as fp:
        json.dump(obj, fp, indent=4)



def train_main(config: TrainerConfig, resume_output_dir: str = None):

    dataset_name = os.path.basename(os.path.normpath(config.dataset_dir))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config.output_dir = join_dir(config.output_dir, f"{stamp}_{dataset_name}")
    PRINT("Work dir:", config.output_dir)
    PRINT()

    config.image_dir = join_dir(config.dataset_dir, config.image_dir)
    config.mask_dir = join_dir(config.dataset_dir, config.mask_dir) if config.mask_dir is not None else ""
    config.sparse_dir = join_dir(config.dataset_dir, config.sparse_dir)
    config.output_ply = os.path.join(config.output_dir, config.output_ply)

    train(config, resume_output_dir=resume_output_dir)
    eval(config)


def benchmark_mipnerf360():
    # In the paper, we benchmark on PNG images generated by GSplat
    scenes = [
        ("bicycle", "images_4_png"),
        ("garden", "images_4_png"),
        ("stump", "images_4_png"),
        ("bonsai", "images_2_png"),
        ("counter", "images_2_png"),
        ("kitchen", "images_2_png"),
        ("room", "images_2_png"),
    ]

    for scene_name, image_dir in scenes:
        for cap_max in [1000000, 2000000, 3000000, None]:
        # for cap_max in [1000000]:
        # for cap_max in [None]:
        # for cap_max in [1000000, 2000000, 3000000]:
        # for cap_max in [1000000, None]:
            display_cap_max = str(cap_max)
            if cap_max is None:
                config = TrainerConfig()
                display_cap_max = "default"
            else:
                config = MCMCTrainerConfig()
                config.cap_max = cap_max
            # config.dataset_dir = f"D:\\harry\\mipnerf360\\{scene_name}"
            config.dataset_dir = f"/home/harry/gs/360_v2/{scene_name}"
            config.image_dir = image_dir
            # config.output_dir = f"D:\\harry\\outputs\\bench_m360\\{display_cap_max}"
            # config.output_dir = f"D:\\harry\\outputs\\{__import__('sys').argv[1]}\\{display_cap_max}"
            config.output_dir = f"/home/harry/outputs/bench_m360/{display_cap_max}"

            PRINT(f"Running {scene_name} {cap_max}")
            try:
                train_main(config)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(flush=True)

            PRINT(end='\n\n\n')


if __name__ == "__main__":

    # train_main(TrainerConfig())
    train_main(MCMCTrainerConfig())

    # benchmark_mipnerf360()

