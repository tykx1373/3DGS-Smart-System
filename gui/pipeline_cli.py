# -*- coding: utf-8 -*-
"""无界面批量入口：不开 GUI 也能跑 COLMAP + 训练，适合挂机排队。

用法（在仓库根目录执行）：
    env\\vksplat\\python.exe gui\\pipeline_cli.py --images sample\\south-building ^
        --quality fast --colmap-only
    env\\vksplat\\python.exe gui\\pipeline_cli.py --images D:\\photos\\scene ^
        --quality standard --steps 15000

交互点全部改成自动应答（续训保留恢复点、可复用空间定位时直接复用、
重复训练照常重训），因此不需要人盯着；退出码：0 成功 / 1 失败 / 2 未启动 / 130 被 Ctrl+C 中断。
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline_core import (  # noqa: E402
    DEFAULT_COLMAP, DEFAULT_VKSPLAT_PY, QUALITY_PRESETS, RES_AUTO,
    PipelineCore, relativize_path, resolve_path,
)

QUALITY_ARGS = {"fast": "快速", "standard": "标准", "high": "高质量"}


def _force_utf8_output():
    """CI 与英文 Windows 的管道输出默认是 cp1252，中文日志会直接抛
    UnicodeEncodeError；统一切到 UTF-8。没有 reconfigure 的流就跳过。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _emit(text, stream=None):
    """打印兜底：流不支持中文时用 ? 代替，绝不能因为一条日志把程序打崩。"""
    stream = stream or sys.stdout
    try:
        print(text, file=stream, flush=True)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", "") or "utf-8"
        print(text.encode(enc, "replace").decode(enc, "replace"),
              file=stream, flush=True)


_force_utf8_output()


class _Var:
    """Tk Var 风格的 get/set 适配对象，供 PipelineCore 无差别读取。"""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class CliHost(PipelineCore):
    """无界面宿主：实现 PipelineCore 需要的回调，交互点一律自动应答。"""

    def __init__(self, args):
        self.args = args
        PipelineCore.init_core(self)
        self.done = threading.Event()
        self.started = False
        self.trained = False
        self.colmap_ok = False
        self.failure = None
        self._last_pct = -10

        quality = QUALITY_ARGS[args.quality]
        steps = args.steps or QUALITY_PRESETS[quality][0]
        self.img_var = _Var(args.images)
        self.ws_var = _Var(args.workspace or "")
        self.quality_var = _Var(quality)
        self.res_var = _Var(RES_AUTO)
        self.max_img_var = _Var(args.max_image_size)
        self.vs_steps_var = _Var(steps)
        # 只有 GPU 检测失败时才会用到缓存策略；默认与 GUI 一致
        self.vs_cache_var = _Var("cpu")
        self.vs_mcmc_var = _Var(not args.no_mcmc)
        self.run_eval_var = _Var(not args.no_eval)
        self.mask_var = _Var(args.mask or "")
        self.lpips_dl_var = _Var(False)
        self.exposure_fix_var = _Var(args.exposure_fix)
        self.vksplat_py_var = _Var(args.vksplat_python or DEFAULT_VKSPLAT_PY)
        self.colmap_var = _Var(args.colmap or DEFAULT_COLMAP)
        # 无界面模式不启动查看器，留空即可
        self.vkgs_var = _Var("")

    # ------------------------------------------------------------ 输出 ----
    def _log(self, text):
        if "[OK] COLMAP 空间定位完成" in text:
            self.colmap_ok = True
        _emit(text)

    def set_status(self, text):
        _emit(f"== {text}")

    def set_step(self, n):
        pass

    def set_stage(self, n):
        pass

    def set_stage_plan(self, stages):
        pass

    def set_progress(self, frac, detail):
        # 全程同一根进度条：每 10% 打一行，日志不至于被刷屏
        if frac is None or frac < 0:
            return
        pct = int(frac * 100)
        if pct >= self._last_pct + 10:
            self._last_pct = pct
            _emit(f"[{pct:3d}%] {detail}")

    def set_workspace(self, path):
        _emit(f"[INFO] 工作区: {path}")

    def set_running(self, running, indeterminate=False):
        if running:
            self.started = True
        else:
            self.done.set()

    def show_eval(self, mean, stats=None):
        pass

    def show_failure(self, cause, advice):
        self.failure = (cause, advice)

    def _run_viewer(self, output_ply):
        # 走到这里说明训练已经成功收完产物；无界面模式不打开窗口
        self.trained = True
        self._log(f"[INFO] 无界面模式：不启动查看器，模型在 {output_ply}")

    # ------------------------------------------------------------ 询问 ----
    def ask_resume(self):
        # 有恢复点就接着训，删不删由人决定；挂机场景保留恢复点更安全
        return None

    def ask_continue(self, do_colmap):
        return True

    def ask_reuse_colmap(self, n_imgs, ws_dir):
        # 照片与参数一致才问到这里，直接复用，省掉 COLMAP 的三步
        self._log(f"[INFO] 复用工作区里的空间定位结果（{n_imgs} 张）：{ws_dir}")
        return True

    def ask_retrain_existing(self, ws_dir, cfg):
        # 批量重跑时照常训练，不因为已有模型而跳过
        return "retrain"

    def ask_capture_report(self, report):
        # 采集质量只提醒不拦截：挂机时继续训练
        return True


def build_parser():
    p = argparse.ArgumentParser(
        description="3DGS 快速管线 —— 无界面批量模式（复用同一套 PipelineCore）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python gui/pipeline_cli.py --images D:\\photos\\scene --quality fast --colmap-only\n"
            "  python gui/pipeline_cli.py --images D:\\photos\\scene --quality standard --steps 15000\n"
        ),
    )
    p.add_argument("--images", required=True, help="照片文件夹")
    p.add_argument("--workspace", default="", help="工作区目录（默认 workspaces/<文件夹>_<张数>imgs_gs）")
    p.add_argument("--quality", choices=sorted(QUALITY_ARGS), default="standard",
                   help="质量档位（默认 standard）")
    p.add_argument("--steps", type=int, default=0, help="训练步数（默认取档位预设）")
    p.add_argument("--max-image-size", type=int, default=1600, help="COLMAP 最大图像尺寸（默认 1600）")
    p.add_argument("--mask", default="", help="mask 文件夹（可选）")
    p.add_argument("--exposure-fix", action="store_true", help="开启曝光校正")
    p.add_argument("--no-eval", action="store_true", help="关闭训练后质量评估")
    p.add_argument("--no-mcmc", action="store_true", help="关闭 MCMC（用默认致密化）")
    p.add_argument("--colmap-only", action="store_true", help="只跑空间定位，不训练")
    p.add_argument("--train-only", action="store_true", help="跳过 COLMAP，直接用已有 sparse/0 训练")
    p.add_argument("--force-colmap", action="store_true", help="即使可复用也重新计算空间定位")
    p.add_argument("--vksplat-python", default="", help="VkSplat 的 Python（默认自动查找）")
    p.add_argument("--colmap", default="", help="COLMAP.bat 路径（默认自动选择）")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.colmap_only and args.train_only:
        _emit("--colmap-only 与 --train-only 不能同时使用", sys.stderr)
        return 2
    img_dir = resolve_path(args.images)
    if not os.path.isdir(img_dir):
        _emit(f"照片文件夹不存在: {img_dir}", sys.stderr)
        return 2

    host = CliHost(args)
    do_colmap = not args.train_only
    do_train = not args.colmap_only
    started_at = time.time()

    host._log(f"[INFO] 3DGS 快速管线（无界面）图片: {img_dir}")
    host._log(f"[INFO] 档位={host.quality_var.get()} 步数={host.vs_steps_var.get()} "
              f"COLMAP={'是' if do_colmap else '否'} 训练={'是' if do_train else '否'}")

    host.start(do_colmap, do_train, force_colmap=args.force_colmap)
    if not host.started:
        _emit("管线没有启动（检查照片文件夹与参数）。", sys.stderr)
        return 2

    try:
        while not host.done.wait(0.5):
            pass
    except KeyboardInterrupt:
        _emit("\n[WARN] 收到 Ctrl+C，正在安全停止（保存恢复点）...", sys.stderr)
        host.stop_pipeline()
        host.done.wait(30)
        return 130

    elapsed = time.time() - started_at
    if do_train:
        success = host.trained
    elif do_colmap:
        success = host.colmap_ok
    else:
        success = False
    if not success:
        cause, advice = host.failure or ("运行失败", "查看上面的日志最后几行")
        _emit(f"\n[FAIL] {cause}\n[WARN] 建议: {advice}", sys.stderr)
        return 1

    if do_train:
        _img, _n, ws_dir = host._run_paths()
        if ws_dir:
            out = host._make_output_ply_name(ws_dir)
            _emit(f"[OK] 模型: {out}（工作区 {relativize_path(ws_dir)}）")
    _emit(f"[OK] 完成，用时 {elapsed / 60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
