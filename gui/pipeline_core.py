# -*- coding: utf-8 -*-
"""与界面无关的 3DGS 管线核心：COLMAP 稀疏重建 → VkSplat 训练 → 收取产物。

quick_gui.MainWindow（PySide6/Fluent）继承 PipelineCore。

宿主界面需提供以下“接口”（鸭子类型，不强制继承）：

  变量（get/set 即可，Tk Var 或 Qt 适配对象都行）:
    img_var, ws_var, quality_var, res_var, max_img_var, vs_steps_var,
    vs_cache_var, vs_mcmc_var, run_eval_var, mask_var, lpips_dl_var,
    exposure_fix_var, vksplat_py_var, colmap_var, vkgs_var
  回调（核心可能在工作线程调用，宿主自己负责线程封送）:
    _log(text), set_status(text), set_step(n), set_running(running, indeterminate),
    set_progress(frac, detail), set_workspace(path), show_eval(mean, stats),
    show_failure(cause, advice),
    set_stage(n), set_stage_plan(stages)   # 7 段进度时间线（宿主可不实现）
  仅 UI 线程调用的询问:
    ask_resume(), ask_continue(do_colmap) -> bool,
    ask_reuse_colmap(n_imgs, ws_dir) -> bool,      # 有可复用的空间定位时问一句
    ask_retrain_existing(ws_dir, cfg) -> str       # "retrain" / "view" / "cancel"
  工作线程发起、宿主负责弹窗并等待回答的询问:
    ask_capture_report(report) -> bool   # False = 用户选择先去补拍
"""
import os
import re
import sys
import json
import time
import shutil
import tempfile
import subprocess
import threading
from collections import deque

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # 3DGS/gui
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                # 3DGS
CONFIG_PATH = os.path.join(SCRIPT_DIR, "quick_gui_config.json")

# 同目录模块（diagnostics / syscheck）
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import diagnostics  # noqa: E402
import syscheck  # noqa: E402
from progress_tracker import ProgressTracker, _PROGRESS_RE  # noqa: E402

# 拆分后仍然从这里重新导出：界面与测试沿用 pipeline_core.xxx 的旧调用方式
from dataset_tools import (  # noqa: E402
    IMAGE_EXTS, SEQUENTIAL_MATCHER_THRESHOLD, LOW_REGISTRATION_RATE,
    CAPTURE_WARN_RATE, pick_colmap_matcher, parse_registered_images,
    read_registered_names, blur_scores, pick_blurry, build_capture_report,
    photo_precheck_text, capture_report_text,
)
from eval_metrics import load_eval_mean, judge_eval_metrics  # noqa: E402
from model_store import (  # noqa: E402
    scan_history_models, is_path_within, delete_history_model,
)
from workspace_meta import (  # noqa: E402
    COLMAP_META_FILE, COLMAP_META_VERSION,
    write_colmap_meta, colmap_meta_matches,
    TRAIN_CONFIG_FILE, TRAIN_CONFIG_VERSION,
    write_train_config, train_config_matches,
)

# 所有默认路径相对 PROJECT_ROOT 存储
DEFAULT_COLMAP = os.path.join("tools", "colmap-x64-windows-cuda", "COLMAP.bat")


def _find_vkgs_exe():
    """在 tools/ 下自动查找 vk_gaussian_splatting.exe，
    兼容不同版本目录名（如 vkgs-2026.2.9-windows-64bits）。"""
    tools = os.path.join(PROJECT_ROOT, "tools")
    if not os.path.isdir(tools):
        return os.path.join("tools", "vk_gaussian_splatting.exe")
    for root, _dirs, files in os.walk(tools):
        if "vk_gaussian_splatting.exe" in files:
            return os.path.relpath(os.path.join(root, "vk_gaussian_splatting.exe"), PROJECT_ROOT)
    return os.path.join("tools", "vk_gaussian_splatting.exe")


DEFAULT_VKGS = _find_vkgs_exe()


def _find_vksplat_python():
    """优先查找项目目录下的 env/vksplat（自包含），其次常见 conda 安装路径，
    找不到则回退到当前运行 GUI 的 Python（要求其已 pip install vksplat）。"""
    p = os.path.join(PROJECT_ROOT, "env", "vksplat", "python.exe")
    if os.path.exists(p):
        return p
    for cmd in ("mamba", "conda"):
        exe = shutil.which(cmd)
        if exe:
            base = os.path.dirname(os.path.dirname(exe))
            p = os.path.join(base, "envs", "vksplat", "python.exe")
            if os.path.exists(p):
                return p
    for base in [
        os.path.expanduser(r"~\.conda"),
        r"C:\mambaforge", r"C:\miniforge3", r"C:\miniconda3", r"C:\anaconda3",
        r"D:\mambaforge", r"D:\miniforge3", r"D:\miniconda3-pbe", r"D:\miniconda3", r"D:\anaconda3",
        os.path.expanduser(r"~\mambaforge"), os.path.expanduser(r"~\miniforge3"),
        os.path.expanduser(r"~\miniconda3"), os.path.expanduser(r"~\anaconda3"),
        os.path.expanduser(r"~\AppData\Local\mambaforge"),
        os.path.expanduser(r"~\AppData\Local\miniforge3"),
        os.path.expanduser(r"~\AppData\Local\miniconda3"),
        os.path.expanduser(r"~\AppData\Local\anaconda3"),
        r"C:\ProgramData\mambaforge", r"C:\ProgramData\miniforge3",
        r"C:\ProgramData\miniconda3", r"C:\ProgramData\anaconda3",
    ]:
        p = os.path.join(base, "envs", "vksplat", "python.exe")
        if os.path.exists(p):
            return p
    return sys.executable


DEFAULT_VKSPLAT_PY = _find_vksplat_python()

# 训练崩溃自动续训
TRAIN_MAX_RETRIES = 3   # 训练异常退出后，自动从恢复点续训的最大次数
TRAIN_RETRY_DELAY = 10  # 每次续训前的等待秒数（给 GPU/驱动恢复留时间）
# 生成照片副本后把临时目录改名放回原位：Windows 下文件可能被杀毒软件短暂占用
RENAME_RETRIES = 5
RENAME_RETRY_DELAY = 0.4

# 训练图像分辨率：质量档位给默认值，用户可在高级选项里单独覆盖
RES_AUTO = "跟随质量档位"
RES_DIR_MAP = {
    "1/4（images_4）": "images_4",
    "1/2（images_2）": "images_2",
    "原分辨率（images）": "images",
}
RES_DEFAULT_BY_QUALITY = {"快速": "images_4", "标准": "images_2", "高质量": "images"}
# 降采样/归一化副本里标记“已按 EXIF 方向纠正”的文件。COLMAP 会应用 EXIF 方向
# 而 cv2 / stb_image 不会：手机竖拍照片（orientation=6/8）若不预旋转，
# 训练图与位姿差 90°，模型直接训废。marker 用于让旧的无纠偏副本自动失效重建。
EXIF_MARKER = ".orientation_fixed"
# 曝光校正副本的标记：开启校正后旧的未校正副本据此自动失效重建
EXPOSURE_MARKER = ".exposure_matched"
# 标记 images 目录是「联接读不通时程序自己复制出来的照片副本」，下次运行才敢复用，
# 也才敢确认这个普通文件夹不是用户自己放进去的。
IMAGES_COPY_MARKER = ".images_copied_from"

# 质量档位 -> (训练步数, 说明)。档位只给默认值，步数/分辨率都能在高级选项里覆盖。
QUALITY_PRESETS = {
    "快速": (5000, "约 2~3 分钟（1/4 分辨率），快速预览轮廓"),
    "标准": (15000, "约 8~10 分钟（半分辨率），推荐日常使用"),
    "高质量": (30000, "约 20 分钟+（全分辨率），细节最丰富"),
}

# 认不出具体原因时的兜底说法：主面板必须始终有内容可显示，
# 否则新手面对一个不动的进度条完全不知道下一步做什么。
GENERIC_FAILURE = ("这一步没有跑成功（原因没能自动识别）",
                   "展开下方的运行日志看最后几行，或点「导出诊断包」把日志发给开发者。")

# tqdm 走 stderr 且用 \r 刷新，会把 stdout 的 PROGRESS 标记挤到行中间，
# 因此这里不要求行首匹配，而是在整行内查找进度标记。
# 通用 tqdm 帧，形如 "Running eval:  44%|███▍ | 7/16 [02:20<03:04, 20.5s/it]"。
# 只匹配 ASCII 阶段名，避免误吃中文或路径文本。
_TQDM_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9 _\-]*?):\s*(?P<pct>\d+)%\|"
    r"[^|]*\|\s*(?P<n>\d+)/(?P<total>\d+)"
    r"(?:\s*\[(?P<elapsed>[0-9:]+)<(?P<eta>[0-9:?]+))?"
)


# ------------------------------------------------------------ pure helpers ----
def resolve_path(p):
    if not p:
        return p
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(PROJECT_ROOT, p))


def relativize_path(p):
    if not p:
        return p
    if not os.path.isabs(p):
        return p
    try:
        rel = os.path.relpath(p, PROJECT_ROOT)
        if rel.startswith(".."):
            return p
        return rel
    except ValueError:
        return p


def load_config(path=None):
    path = path or CONFIG_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "colmap_path": DEFAULT_COLMAP,
        "vkgs_exe": DEFAULT_VKGS,
        "vksplat_python": DEFAULT_VKSPLAT_PY,
    }


def save_config(cfg, path=None):
    try:
        with open(path or CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=True)
    except Exception:
        pass


def _cfg_int(cfg, key, default, lo, hi):
    """从配置里取整数；缺失、类型不对或越界都退回默认值。"""
    try:
        v = int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default
    return v if lo <= v <= hi else default


def _cfg_choice(cfg, key, valid, default):
    """从配置里取枚举值；不在候选里就退回默认值。"""
    v = cfg.get(key)
    return v if v in valid else default


# --------------------------------------------------------------- PipelineCore ----
class PipelineCore:
    """Tk / Qt 两个界面共用的管线方法集合。宿主接口见模块 docstring。"""

    def init_core(self):
        self.current_proc = None
        self.stop_flag = False
        self._ips_recorded = False
        self._last_failure_hint = None
        self._capture_report = None
        self._from_sample = False
        # 进度分段、阶段时间线、训练实测值都交给 tracker；这里只留管线状态
        self.progress = ProgressTracker(self)
        # 训练进度里「显存 X/Y GB」的分母；None 表示这台机器给不出可信总量，
        # 界面就只显示占用值
        self._vram_total_mb = None

    # ---------------------------------------------------------- 进度分段 ----
    def _set_span(self, lo, hi):
        self.progress.set_span(lo, hi)

    def _set_train_span(self, a, b):
        self.progress.set_train_span(a, b)

    def map_progress(self, frac):
        return self.progress.map_progress(frac)

    def _progress(self, frac, detail):
        self.progress.progress(frac, detail)

    # ---------------------------------------------------------- 阶段时间线 ----
    def _stage_plan(self, stages):
        self.progress.stage_plan(stages)

    def _stage(self, n):
        self.progress.stage(n)

    def _record_train_stats(self, line):
        self.progress.record_train_stats(line)

    def _train_summary(self):
        return self.progress.train_summary()

    def _stage_from_output(self, line):
        self.progress.stage_from_output(line)

    def _done_message(self):
        """跑完时给用户的那句话：示例首跑要说得像个里程碑。"""
        if getattr(self, "_from_sample", False):
            self._from_sample = False
            return "这是你做出的第一个模型！在刚打开的窗口里按住鼠标拖动，就能围着它转。"
        return "完成！3D 模型已生成，可随时在历史记录里重新打开。"

    def _confirm_capture_quality(self):
        """采集质量不达标时先问一句要不要去补拍；False 表示本轮就此停下。

        只提醒不拦截：报告没有、照片没问题、宿主没实现弹窗，三种情况都照常训练。
        """
        report = getattr(self, "_capture_report", None)
        self._capture_report = None
        if not report:
            return True
        ask = getattr(self, "ask_capture_report", None)
        if not callable(ask):
            return True
        try:
            return bool(ask(report))
        except Exception as e:
            self._log(f"[WARN] 采集质量提示失败（按继续训练处理）: {e}")
            return True

    # ----------------------------------------------------------- start/stop ----
    def start(self, do_colmap, do_train, force_colmap=False):
        """UI 线程调用：询问复用/重复训练/恢复点/耗时后，起工作线程跑管线。

        force_colmap=True 表示用户明确要求重算（「只用 COLMAP」入口），
        此时连问都不问，直接从头跑。
        """
        self.ask_resume()
        self.progress.reset_run()
        # 有未完成的恢复点 = 在续训，不该再提示「这套设置已经训练过」
        if do_train and not self._has_checkpoint():
            if self._ask_retrain_existing() != "retrain":
                return
        reuse = False
        if do_colmap and do_train and not force_colmap:
            reuse = self._ask_reuse_colmap()
        run_colmap = do_colmap and not reuse
        if not self.ask_continue(run_colmap):
            return
        self._ips_recorded = False
        self.stop_flag = False
        self.progress.reuse = reuse
        if reuse:
            self._log("[INFO] 复用上次的空间定位结果，跳过 COLMAP（照片与参数未变）。")
        # COLMAP 也能逐张报进度了，所以全程用同一根确定进度条：
        # 两个都做时 COLMAP 占前 30%，训练占后 70%；只做其一就占满。
        # 复用空间定位时进度条只有训练部分，也占满。
        self.progress.configure(run_colmap, do_train)
        # 时间线只显示本次真的会走的段：复用/只做空间定位/关掉评估时，
        # 把用不上的段藏起来，免得用户盯着一个永远不会亮的节点。
        plan = ([1, 2, 3] if run_colmap else [])
        if do_train:
            plan += [4, 5]
            try:
                if self.run_eval_var.get():
                    plan.append(6)
            except Exception:
                plan.append(6)
            plan.append(7)
        self._stage_plan(plan)
        self.set_running(True, False)
        self._progress(0, "正在准备..." if run_colmap else "正在准备训练...")
        threading.Thread(
            target=self.pipeline_thread,
            kwargs={"do_colmap": do_colmap, "do_train": do_train,
                    "reuse_colmap": reuse},
            daemon=True).start()

    def _default_workspace(self, img_dir, n_imgs):
        """没填工作区时的默认目录（工作线程与复用检查必须用同一规则）。"""
        name = os.path.basename(img_dir.rstrip("/\\")) or "project"
        return os.path.join(PROJECT_ROOT, "workspaces", f"{name}_{n_imgs}imgs_gs")

    def _run_paths(self):
        """本次运行的照片目录/张数/工作区；照片没选好时返回 (None, 0, None)。"""
        img_dir = resolve_path(self.img_var.get().strip())
        n_imgs = self._count_images(img_dir)
        if not n_imgs:
            return None, 0, None
        ws_dir = resolve_path(self.ws_var.get().strip()) \
            or self._default_workspace(img_dir, n_imgs)
        return img_dir, n_imgs, ws_dir

    def _has_checkpoint(self):
        """工作区里是否有未完成的训练恢复点（下次会续训，而不是从头训）。"""
        _img, _n, ws_dir = self._run_paths()
        if not ws_dir:
            return False
        return (os.path.isfile(os.path.join(ws_dir, "checkpoint.ply"))
                and os.path.isfile(os.path.join(ws_dir, "checkpoint.ply.step")))

    def _train_settings(self):
        """当前训练设置的快照：写进 train_config.json，也用于识别「已经这样训过」。"""
        mask = self.mask_var.get().strip()
        if mask:
            mask = relativize_path(resolve_path(mask))
        return {
            "quality": str(self.quality_var.get()),
            "steps": int(self.vs_steps_var.get()),
            "res_choice": str(self.res_var.get()),
            "mcmc": bool(self.vs_mcmc_var.get()),
            "run_eval": bool(self.run_eval_var.get()),
            "exposure_fix": bool(self.exposure_fix_var.get()),
            "mask_dir": mask,
            "max_image_size": int(self.max_img_var.get()),
        }

    def _ask_retrain_existing(self):
        """这组照片 + 这套设置已经成功训过时问一句。

        返回 "retrain"（继续跑）、"view"/"cancel"（宿主已处理，调用方直接返回）。
        没记录、模型被删、宿主不支持，都按 "retrain" 处理。
        """
        img_dir, _n, ws_dir = self._run_paths()
        if not img_dir or not ws_dir:
            return "retrain"
        matched, cfg = train_config_matches(ws_dir, img_dir, self._train_settings())
        if not matched:
            return "retrain"
        ask = getattr(self, "ask_retrain_existing", None)
        if not callable(ask):
            return "retrain"
        try:
            decision = str(ask(ws_dir, cfg)).strip().lower()
        except Exception as e:
            self._log(f"[WARN] 重复训练提示失败（按重新训练处理）: {e}")
            return "retrain"
        return decision if decision in ("retrain", "view", "cancel") else "retrain"

    def _ask_reuse_colmap(self):
        """有完整且与当前照片/参数一致的空间定位结果时，问一句要不要复用。

        不能复用、宿主没实现询问，都按「重新计算」处理——宁可多等几分钟，
        也不拿旧位姿去训一批新照片。
        """
        img_dir, n_imgs, ws_dir = self._run_paths()
        if not img_dir or not ws_dir:
            return False
        ok, reason = colmap_meta_matches(ws_dir, img_dir, self.max_img_var.get())
        if not ok:
            # 有旧记录却不能复用：把原因写进日志，免得用户以为「怎么又重算了」
            if os.path.isfile(os.path.join(ws_dir, COLMAP_META_FILE)):
                self._log(f"[INFO] 重新计算空间定位：{reason}")
            return False
        ask = getattr(self, "ask_reuse_colmap", None)
        if not callable(ask):
            return False
        try:
            return bool(ask(n_imgs, ws_dir))
        except Exception as e:
            self._log(f"[WARN] 复用询问失败（按重新计算处理）: {e}")
            return False

    def stop_pipeline(self):
        self.stop_flag = True
        self._log("[WARN] 用户请求停止...")
        # 不在此处 terminate：训练进程由 run_cmd 通过 STOP 文件优雅停止，
        # COLMAP 等其他进程由 run_cmd 强制终止。

    # ------------------------------------------------------------- helpers ----
    def _count_images(self, folder):
        """数文件夹里的可训练照片；读不动就当 0，绝不把异常抛给选照片那一步。

        这个数只用于估算耗时和判断「工作区跟数据集对不对得上」，读失败时给出
        0 比让整条流程崩掉更符合它的分量。
        """
        if not folder or not os.path.isdir(folder):
            return 0
        try:
            return sum(1 for f in os.listdir(folder)
                       if f.lower().endswith(IMAGE_EXTS))
        except OSError:
            return 0

    def _count_selected_images(self):
        """当前选择文件夹里的可训练照片数；与 _count_images 同口径（复用 IMAGE_EXTS）。

        只用于耗时估算，所以必须算成「真的会被处理的那几张」——早先这里多列了
        .webp，混着 webp 的文件夹会把 COLMAP 耗时估算撑高。
        """
        folder = resolve_path(self.img_var.get().strip()) if self.img_var.get().strip() else ""
        if not folder or not os.path.isdir(folder):
            return None
        try:
            return sum(1 for f in os.listdir(folder)
                       if f.lower().endswith(IMAGE_EXTS))
        except Exception:
            return None

    def _make_output_ply_name(self, ws_dir):
        steps = self.vs_steps_var.get()
        quality = self.quality_var.get()
        quality_map = {"快速": "fast", "标准": "standard", "高质量": "high"}
        q = quality_map.get(quality, "standard")
        return os.path.join(ws_dir, f"vksplat_{steps}steps_{q}.ply")

    def _find_new_output_ply(self, output_dir, existing_dirs):
        """本次新生成的输出目录里是否有 splat.ply。
        用来判断“训练其实已经完成”，只是之后评测阶段失败了。"""
        try:
            for d in os.listdir(output_dir):
                full = os.path.join(output_dir, d)
                if os.path.isdir(full) and d not in existing_dirs:
                    if os.path.isfile(os.path.join(full, "splat.ply")):
                        return True
        except Exception:
            pass
        return False

    def _find_latest_ply(self, ws_dir):
        # 新数据集的工作区可能还不存在，listdir 不能崩
        if not os.path.isdir(ws_dir):
            return None
        plys = [os.path.join(ws_dir, f) for f in os.listdir(ws_dir)
                if f.lower().endswith(".ply")]
        if not plys:
            return None
        return max(plys, key=os.path.getmtime)

    # ----------------------------------------------------------- run cmd ----
    def _resolve_colmap(self, colmap_path):
        p = colmap_path.strip()
        low = p.lower()
        if low.endswith(".bat"):
            base = os.path.dirname(p)
            exe = os.path.join(base, "bin", "colmap.exe")
        else:
            exe = p
            base = os.path.dirname(os.path.dirname(p))
        env = os.environ.copy()
        bin_dir = os.path.join(base, "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        plugins = os.path.join(base, "plugins")
        if os.path.isdir(plugins):
            env["QT_PLUGIN_PATH"] = plugins + os.pathsep + env.get("QT_PLUGIN_PATH", "")
        return exe, env

    def run_cmd(self, cmd_list, env=None, cwd=None, graceful_ws_dir=None, colmap=False,
                colmap_total=0):
        display = " ".join(f'"{c}"' if (" " in c or c == "") else c for c in cmd_list)
        self._log(">>> " + display)
        try:
            self.current_proc = subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd,
                creationflags=syscheck.NO_WINDOW,
            )
        except Exception as e:
            self._log(f"[FAIL] 启动失败: {e}")
            return False

        graceful_requested = False
        graceful_deadline = None
        tail = deque(maxlen=200)   # 保留输出尾部，失败时用来认原因
        for line in self.current_proc.stdout:
            if self.stop_flag and not graceful_requested:
                if graceful_ws_dir:
                    # 训练进程：写 STOP 文件，等它自己保存进度后退出
                    try:
                        with open(os.path.join(graceful_ws_dir, "STOP"), "w") as f:
                            f.write("stop")
                        graceful_requested = True
                        graceful_deadline = time.time() + 60
                        self._log("[WARN] 已请求安全停止，等待训练保存进度...")
                        self.set_status("正在保存训练进度，请稍候...")
                        continue  # 继续读输出，等进程自己退出
                    except Exception:
                        pass
                try:
                    self.current_proc.terminate()
                except Exception:
                    pass
                self._log("[WARN] 已被用户停止。")
                return False
            # 安全网：优雅停止后超过 60 秒进程仍未退出，强制终止
            if graceful_requested and graceful_deadline and time.time() > graceful_deadline:
                try:
                    self.current_proc.terminate()
                except Exception:
                    pass
                self._log("[WARN] 等待超时，已强制终止训练进程（进度回退到上一个恢复点）。")
                return False
            line = line.rstrip()
            if line:
                tail.append(line)
                self._log(line)
                if colmap_total:
                    self._colmap_line_progress(line, colmap_total)
                self._stage_from_output(line)
                self._record_train_stats(line)
        self.current_proc.wait()
        rc = self.current_proc.returncode
        self.current_proc = None
        if graceful_requested:
            self._log("[WARN] 训练已安全停止，进度已保存。")
            return False
        if rc != 0:
            self._log(f"[FAIL] 退出码: {rc}")
            self._explain_failure(rc, "\n".join(tail), colmap)
            return False
        return True

    def _colmap_line_progress(self, line, total):
        self.progress.colmap_line_progress(line, total)

    def _step_progress(self, n, total, verb):
        self.progress.step_progress(n, total, verb)

    def _explain_failure(self, rc, output, colmap=False):
        """把退出码翻译成人话：日志一份，主面板一份。

        同一原因只讲一次，避免自动续训时重复刷屏。日志默认折叠，新手出错时
        第一反应不是翻日志，所以原因和建议必须同时送到界面上（show_failure）。
        """
        hint = diagnostics.explain_failure(rc, output, colmap=colmap) or GENERIC_FAILURE
        if hint == self._last_failure_hint:
            return
        self._last_failure_hint = hint
        cause, advice = hint
        self._log(f"[FAIL] 原因: {cause}")
        self._log(f"[WARN] 建议: {advice}")
        self._notify_failure(cause, advice)

    def _notify_failure(self, cause, advice):
        """把「原因 + 怎么办」送到主面板；宿主没实现该回调时静默跳过。"""
        show = getattr(self, "show_failure", None)
        if callable(show):
            try:
                show(cause, advice)
            except Exception:
                pass   # 面板显示失败不能反过来影响管线

    # ---------------------------------------------------- 工作区照片接入 ----
    def _ensure_images_dir(self, images_dir, src_dir):
        """保证 images_dir 是一个「程序能读」的照片目录；联接读不通就退回复制。

        旧做法只建目录联接（零拷贝），把联接直接当数据通路。但联接能不能被**遍历**
        取决于这台机器的策略：实测有机器上 `mklink /J` 返回成功、联接也确实在那里，
        一列目录就抛 WinError 448（不受信任的装入点），COLMAP 与训练都读不到照片。
        所以联接只当快路径试一次，建完必须实测能不能列出文件；读不通就复制副本，
        宁可多占磁盘，也不要让用户在那台机器上跑不起来。

        另外三个坑（都踩过）：
        - 联接不是符号链接，os.path.islink 恒为 False，判定要看 lstat 的 reparse tag；
          旧代码因此走 rmtree 去删联接，删不掉，随后 mklink 必然报「文件已存在」。
        - rmtree 若真生效，删掉的可能是用户自己的照片文件夹。
        - cmd 的输出是 OEM 代码页，让 subprocess 按 UTF-8 解码会在读取线程里抛
          UnicodeDecodeError，最后拿到 None 再 .strip()，把真实原因盖成一句看不懂
          的报错。
        """
        src_abs = os.path.normcase(os.path.abspath(src_dir))
        marker = os.path.join(images_dir, IMAGES_COPY_MARKER)

        if self._is_reparse(images_dir):
            link_to = self._link_target(images_dir)
            if link_to == src_abs and self._dir_readable(images_dir):
                return True                       # 指向对、也读得动，重跑不该重来
            if link_to != src_abs:
                self._log("[INFO] 照片文件夹换了，重建工作区里的照片链接。")
            else:
                self._log("[WARN] 这台机器不允许程序创建的链接被读取，"
                          "改为把照片复制到工作区。")
            try:
                self._remove_dir_or_link(images_dir)   # 只移除链接本身
            except OSError as e:
                self._log(f"[FAIL] 无法移除旧的照片链接: {e}")
                return False
        elif os.path.isdir(images_dir):
            if self._dir_readable(images_dir) and self._copied_from(marker, src_abs):
                return True                       # 上次复制的副本，继续用
            if not self._dir_readable(images_dir):
                self._log(f"[FAIL] 工作区里的 images 读不出来: {images_dir}")
                self._notify_failure(
                    "工作区里已有的照片目录读不出来",
                    "在「高级选项」里换一个新的工作区名最省事；确认那个文件夹里没有你"
                    "自己的照片的话，也可以手动删掉它再重试。")
                return False
            # 真实目录且没有复制标记：里面可能是用户自己放的照片，删不得
            self._log("[FAIL] 工作区里的 images 是一个普通文件夹，不是程序创建的链接，"
                      "我不能直接删掉它。")
            self._notify_failure(
                "工作区里已经有一个同名的 images 文件夹（不是程序建的链接）",
                "在「高级选项」里换一个新的工作区名最省事；确认那个文件夹里没有你自己的"
                "照片的话，也可以手动删掉它再重试。")
            return False

        res = self._run_text(["cmd", "/c", "mklink", "/J", images_dir, src_dir])
        if res is not None and res.returncode == 0:
            if self._dir_readable(images_dir):
                return True
            # 建成功却读不了：这台机器禁止遍历程序新建的装入点，退回复制
            self._log("[WARN] 照片链接建成了但系统不允许读取它（不受信任的装入点），"
                      "改为把照片复制到工作区。")
            try:
                self._remove_dir_or_link(images_dir)
            except OSError as e:
                self._log(f"[FAIL] 无法移除读不通的照片链接: {e}")
                return False
        else:
            self._log("[WARN] 建立照片链接失败"
                      + (f"：{(res.stdout or '').strip()[:120]}" if res is not None else "")
                      + "，改为把照片复制到工作区。")
        return self._copy_images(images_dir, src_dir)

    def _copy_images(self, images_dir, src_dir):
        """把照片原样复制一份进工作区（联接被这台机器禁用时的退路）。"""
        names = sorted(n for n in os.listdir(src_dir) if n.lower().endswith(IMAGE_EXTS))
        if not names:
            self._log(f"[FAIL] 照片文件夹里没有支持的图片: {src_dir}")
            return False

        tmp_dir = images_dir + ".tmp"
        if os.path.exists(tmp_dir):
            self._remove_dir_or_link(tmp_dir)
        os.makedirs(tmp_dir, exist_ok=True)

        done = 0
        total = 0
        for name in names:
            dst = os.path.join(tmp_dir, name)
            for attempt in range(RENAME_RETRIES):
                try:
                    shutil.copy2(os.path.join(src_dir, name), dst)
                    break
                except OSError as e:
                    if attempt == RENAME_RETRIES - 1:
                        self._log(f"[WARN] 复制失败 {name}: {e}")
                        dst = None
            if dst is None:
                continue
            total += os.path.getsize(dst)
            done += 1

        if done == 0:
            self._remove_dir_or_link(tmp_dir)
            self._log("[FAIL] 照片一张都没复制成功")
            self._notify_failure(
                "照片没能复制进工作区（这台机器不允许程序读取自己建的链接，"
                "只能靠复制）",
                "多半是磁盘满了或工作区没有写权限：清出空间后重试，或在「高级选项」里"
                "换个工作区名；仍不行就导出诊断包发出来")
            return False
        if done < len(names):
            self._log(f"[WARN] 有 {len(names) - done} 张照片没能复制，训练只会用到"
                      f"复制成功的 {done} 张。")

        with open(os.path.join(tmp_dir, IMAGES_COPY_MARKER), "w", encoding="utf-8") as f:
            f.write(os.path.abspath(src_dir))
        # 刚写出的文件常被杀毒软件/索引服务短暂占用，改名会偶发 WinError 5
        for attempt in range(RENAME_RETRIES):
            try:
                os.rename(tmp_dir, images_dir)
                break
            except OSError as e:
                if attempt == RENAME_RETRIES - 1:
                    self._log(f"[FAIL] 无法把照片副本放到位: {e}")
                    return False
        self._log(f"[OK] 已把 {done} 张照片复制到工作区（约 {total / 2 ** 20:.0f} MB）。"
                  "这台机器不允许程序创建的图片链接，复制不影响模型效果。")
        return True

    @staticmethod
    def _copied_from(marker, src_abs):
        """images 目录里是否有「我就是从 src 复制来的」标记（决定能不能复用）。"""
        try:
            with open(marker, encoding="utf-8") as f:
                return os.path.normcase(os.path.abspath(f.read().strip())) == src_abs
        except OSError:
            return False

    @staticmethod
    def _link_target(link):
        """读联接里存的目标路径，**不跟随联接**。

        不能用 os.path.realpath：它真的会去遍历，被系统拦下时（WinError 448 不在
        CPython 容忍的错误码名单里）直接抛异常。
        """
        try:
            t = os.readlink(link)
        except OSError:
            return None
        for prefix in ("\\\\?\\", "\\??\\"):
            if t.startswith(prefix):
                t = t[len(prefix):]
        return os.path.normcase(os.path.abspath(t))

    @staticmethod
    def _dir_readable(path):
        """能不能真的列出这个目录——联接建得成不代表读得动。"""
        try:
            with os.scandir(path) as it:
                next(it, None)
        except OSError:
            return False
        return True

    @staticmethod
    def _run_text(cmd):
        """跑一条命令并拿到**一定能解码**的输出；cmd 的内部输出不该影响主流程。"""
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30,
                               creationflags=syscheck.NO_WINDOW)
        except Exception:
            return None

        def dec(b):
            for enc in ("utf-8", "gbk", "cp437", "latin-1"):
                try:
                    return b.decode(enc)
                except (UnicodeDecodeError, ValueError):
                    continue
            return b.decode("utf-8", "replace")

        r.stdout, r.stderr = dec(r.stdout or b""), dec(r.stderr or b"")
        return r

    @staticmethod
    def _is_reparse(path):
        """目录联接/符号链接判定。Windows 的目录联接用 os.path.islink 不可靠，
        这里以 lstat 的 st_reparse_tag 为主。"""
        try:
            if getattr(os.lstat(path), "st_reparse_tag", 0):
                return True
        except Exception:
            pass
        return os.path.islink(path)

    @staticmethod
    def _remove_dir_or_link(path):
        """删除目录；若是联接/符号链接，只移除链接本身，不动它指向的目录。"""
        if PipelineCore._is_reparse(path):
            os.rmdir(path)
        else:
            shutil.rmtree(path)

    @staticmethod
    def _scan_exif_rotations(src_dir, names):
        """返回带 EXIF 旋转标记（orientation != 1）的文件名集合。

        只读元数据不解码像素，几百张图 1 秒内。Pillow 在 environment.yaml 中显式声明。
        读不出 EXIF 的文件（或 Pillow 缺失）按无旋转处理——维持原行为。
        """
        try:
            from PIL import Image
        except ImportError:
            return set()
        rotated = set()
        for name in names:
            try:
                with Image.open(os.path.join(src_dir, name)) as im:
                    exif = im.getexif()
                    if exif and int(exif.get(274, 1)) != 1:  # 274 = Orientation
                        rotated.add(name)
            except Exception:
                continue
        return rotated

    @staticmethod
    def _decode_exif_fixed(buf):
        """解码字节数组并按 EXIF 方向旋转到位，返回 BGR ndarray。

        cv2.imdecode 会忽略 EXIF 方向，因此带旋转标记的图走 PIL：
        exif_transpose 把像素转到正确方向，再交回 cv2 缩放编码。
        """
        import cv2
        from io import BytesIO
        from PIL import Image, ImageOps
        with Image.open(BytesIO(buf)) as src_im:
            im = ImageOps.exif_transpose(src_im)
            if im.mode != "RGB":
                im = im.convert("RGB")
            import numpy as np
            return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    def _make_downscaled(self, dst_dir, src_dir, factor, rotated_names=None,
                         exposure_fix=False):
        """把 src_dir 的图片按 1/factor 缩放后写入 dst_dir，文件名保持不变
        （COLMAP 的 images.bin 按文件名索引，改名就找不到图了）。

        先写 .tmp 再整体替换到位——若旧目录其实是个指向原图的联接，
        直接往里写就会覆盖用户的原图。factor=1 表示只纠偏不缩放
        （高质量档的“方向归一化原图副本”）。exposure_fix=True 时额外做
        曝光校正：以“中间曝光”那张照片为参照，其余逐通道直方图匹配，
        统一明暗（VkSplat 不支持曝光补偿，照片明暗不一会训出色差）。
        """
        import cv2
        import numpy as np

        names = [n for n in os.listdir(src_dir) if n.lower().endswith(IMAGE_EXTS)]
        if not names:
            self._log(f"[WARN] 源目录中没有图片: {src_dir}")
            return False

        rotated_names = rotated_names or set()
        has_marker = os.path.isfile(os.path.join(dst_dir, EXIF_MARKER))
        has_exp_marker = os.path.isfile(os.path.join(dst_dir, EXPOSURE_MARKER))
        need_exif = bool(rotated_names)

        # 已是普通目录且张数对得上 → 上次生成过，直接用。但：
        # ① 这次检测到旋转标记而旧副本没有纠偏标记，方向是错的，重建；
        # ② 开了曝光校正而旧副本没有校正标记，重建。
        if os.path.isdir(dst_dir) and not self._is_reparse(dst_dir):
            stale = ((need_exif and not has_marker)
                     or (exposure_fix and not has_exp_marker))
            have = [n for n in os.listdir(dst_dir) if n.lower().endswith(IMAGE_EXTS)]
            if not stale and len(have) == len(names):
                self._log(f"[INFO] {os.path.basename(dst_dir)} 已存在（{len(names)} 张），跳过生成")
                return True
            if stale:
                self._log(f"[WARN] {os.path.basename(dst_dir)} 是旧副本（缺少纠偏/曝光标记），"
                          f"将重新生成")

        # 曝光校正参照：用 1/8 缩略图统计每张的亮度，取“中间曝光”那张
        # 作为参照并记录其三通道直方图（缩略图的直方图足以代表全图分布）
        ref_name, ref_hists = None, None
        if exposure_fix and len(names) > 1:
            lums, hists = {}, {}
            for name in names:
                try:
                    with open(os.path.join(src_dir, name), "rb") as f:
                        buf = np.frombuffer(f.read(), dtype=np.uint8)
                    small = cv2.imdecode(buf, cv2.IMREAD_REDUCED_COLOR_8)
                    if small is None:
                        continue
                    lums[name] = float(small.mean())
                    hists[name] = [cv2.calcHist([small], [c], None, [256],
                                                 [0, 256]).ravel() for c in range(3)]
                except Exception:
                    continue
            if lums:
                ref_name = sorted(lums, key=lums.get)[len(lums) // 2]
                ref_hists = hists[ref_name]
                self._log(f"[INFO] 曝光校正：以 {ref_name}（中间曝光）为参照，"
                          f"{len(lums)} 张照片将统一明暗")
            else:
                self._log("[WARN] 曝光校正：读不出任何照片统计，跳过校正")

        tmp_dir = dst_dir + ".tmp"
        if os.path.exists(tmp_dir):
            self._remove_dir_or_link(tmp_dir)
        os.makedirs(tmp_dir, exist_ok=True)

        fixed = 0
        matched = 0
        done = 0
        for name in names:
            try:
                with open(os.path.join(src_dir, name), "rb") as f:
                    buf = np.frombuffer(f.read(), dtype=np.uint8)
                if name in rotated_names:
                    im = self._decode_exif_fixed(buf.tobytes())
                    fixed += 1
                else:
                    im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if im is None:
                    continue
                # 曝光校正：当前图逐通道 CDF 对齐到参照图 CDF（查表实现）
                if ref_hists is not None and name != ref_name:
                    for c in range(3):
                        s = cv2.calcHist([im], [c], None, [256], [0, 256]).ravel()
                        s = np.cumsum(s)
                        s = s / max(s[-1], 1.0)
                        r = np.cumsum(ref_hists[c])
                        r = r / max(r[-1], 1.0)
                        lut = np.clip(np.searchsorted(r, s), 0, 255).astype(np.uint8)
                        im[:, :, c] = lut[im[:, :, c]]
                    matched += 1
                h, w = im.shape[:2]
                if factor > 1:
                    im = cv2.resize(im, (max(1, w // factor), max(1, h // factor)),
                                    interpolation=cv2.INTER_AREA)
                ext = os.path.splitext(name)[1].lower() or ".jpg"
                params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in (".jpg", ".jpeg") else []
                enc_ok, enc = cv2.imencode(ext, im, params)
                if not enc_ok:
                    continue
                with open(os.path.join(tmp_dir, name), "wb") as f:
                    f.write(enc.tobytes())
                done += 1
                # 副本生成通常几秒到几十秒；逐张报进度，条才不是假的。
                # 宿主没实现 set_progress（纯逻辑测试）就跳过。
                if factor > 1 and hasattr(self, "set_progress") \
                        and done % max(1, len(names) // 100) == 0:
                    self._progress(done / float(len(names)),
                                   f"第 4/7 步 · 正在准备训练图像 {done}/{len(names)}")
            except Exception as e:
                self._log(f"[WARN] {os.path.basename(dst_dir)} 生成失败 {name}: {e}")

        if done == 0:
            self._remove_dir_or_link(tmp_dir)
            self._log(f"[FAIL] {os.path.basename(dst_dir)} 一张都没生成成功")
            return False

        if os.path.exists(dst_dir):
            try:
                self._remove_dir_or_link(dst_dir)
            except Exception as e:
                self._remove_dir_or_link(tmp_dir)
                self._log(f"[FAIL] 无法替换 {dst_dir}: {e}")
                return False
        # Windows 上刚写出的 jpg 常被杀毒软件/索引服务短暂占用，目录重命名会偶发
        # WinError 5。重试几次；仍失败就给出可执行的建议，而不是把异常抛给上层
        # 变成一句"未预期的错误"。
        for attempt in range(RENAME_RETRIES):
            try:
                os.rename(tmp_dir, dst_dir)
                break
            except OSError as e:
                if attempt == RENAME_RETRIES - 1:
                    self._log(f"[FAIL] 重命名到 {dst_dir} 失败: {e}")
                    self._notify_failure(
                        f"照片副本已生成，但放回原位时失败：{e}",
                        "通常是杀毒软件或资源管理器正占用这些文件：稍等几秒再点一次"
                        "「开始生成」，或把项目目录加入杀毒软件的排除列表")
                    return False
                time.sleep(RENAME_RETRY_DELAY)
        if rotated_names:
            try:
                with open(os.path.join(dst_dir, EXIF_MARKER), "w") as f:
                    f.write("exif orientation fixed\n")
            except Exception:
                pass
        if ref_hists is not None:
            try:
                with open(os.path.join(dst_dir, EXPOSURE_MARKER), "w") as f:
                    f.write("exposure matched\n")
            except Exception:
                pass
        detail = f"，其中 {fixed} 张已按 EXIF 纠正方向" if fixed else ""
        detail += f"，{matched} 张已统一曝光" if matched else ""
        self._log(f"[OK] 已生成 {os.path.basename(dst_dir)}"
                  f"{'（原分辨率，仅纠偏）' if factor == 1 else f'（1/{factor} 分辨率）'}，"
                  f"共 {done} 张{detail}")
        return True

    # --------------------------------------------------- ensure sparse/0 ----
    def _ensure_sparse_zero(self, sparse_dir):
        sparse_zero = os.path.join(sparse_dir, "0")
        os.makedirs(sparse_zero, exist_ok=True)
        moved_something = False
        for fname in ("cameras.bin", "images.bin", "points3D.bin"):
            src = os.path.join(sparse_dir, fname)
            dst = os.path.join(sparse_zero, fname)
            if os.path.isfile(src) and not os.path.isfile(dst):
                shutil.move(src, dst)
                moved_something = True
        if moved_something:
            self._log("[INFO] 已将 COLMAP bin 文件移到 sparse/0/ 下。")
        return sparse_zero

    # -------------------------------------------------------- VkSplat py ----
    def _build_vksplat_script(self, dataset_dir, image_dir, sparse_dir,
                              output_dir, train_steps, cache_device,
                              device_id=-1, cap_max=1000000, resume_output_dir=None,
                              allow_lpips_download=False,
                              use_mcmc=True, run_eval=True, mask_dir=None):
        resume_line = f", resume_output_dir=r\"{resume_output_dir}\"" if resume_output_dir else ""
        # mask_dir 为 None 时传 None（simple_trainer 据此留空）；否则用正斜杠路径，
        # 绝对路径经 join_dir 会原样保留，避免与 dataset_dir 错误拼接。
        mask_repr = "None" if mask_dir is None else \
            'r"' + str(mask_dir).replace("\\", "/") + '"'
        # 评测的 LPIPS 需要约 760 MB 预训练权重。默认只在已缓存时才计算（见
        # simple_trainer.eval）；勾选「允许联网下载」后把开关注入训练脚本的环境变量
        # —— 训练是独立子进程，必须写进脚本才带得过去。
        lpips_line = 'os.environ["VKSPLAT_LPIPS_DOWNLOAD"] = "1"\n' if allow_lpips_download else ""
        return f"""# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.abspath(r"{os.path.join(PROJECT_ROOT, 'tools', 'vksplat', 'vksplat')}"))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
{lpips_line}
# 强制 UTF-8 输出，避免中文日志在 GUI 中乱码
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import simple_trainer
simple_trainer.TRAIN_DEVICE = {device_id}

from simple_trainer import MCMCTrainerConfig, TrainerConfig, train_main

if __name__ == "__main__":
    config = (MCMCTrainerConfig if {use_mcmc} else TrainerConfig)(
        output_dir=r"{output_dir}",
        output_ply="splat.ply",
        train_steps={train_steps},
        max_steps={train_steps},
        refine_stop_iter={train_steps},
        dataset_dir=r"{dataset_dir}",
        image_dir=r"{image_dir}",
        sparse_dir=r"{sparse_dir}",
        image_cache_device="{cache_device}",
        cap_max={cap_max},
        mask_dir={mask_repr},
        run_eval={run_eval},
    )
    train_main(config{resume_line})
"""

    def _detect_gpu(self, vksp_py):
        detect_script = os.path.join(PROJECT_ROOT, "gui", "detect_gpu.py")
        spv_dir = os.path.join("tools", "vksplat", "vksplat", "shader", "generated")
        try:
            result = subprocess.run(
                [vksp_py, "-u", detect_script, spv_dir],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.join(PROJECT_ROOT, "tools", "vksplat", "vksplat"),
                creationflags=syscheck.NO_WINDOW,
            )
            info = json.loads(result.stdout.strip().splitlines()[-1])
            return info["device_id"], info["is_integrated"], info["name"]
        except Exception as e:
            self._log(f"[WARN] GPU 检测失败，使用默认设备: {e}")
            return -1, False, "unknown"

    def _is_nvidia_gpu(self):
        """是否装有 NVIDIA 显卡（决定 COLMAP 用 CUDA 还是 noCUDA 版本）。
        用 PowerShell CIM 替代已弃用的 wmic（Win11 24H2 起移除）。"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=15,
                creationflags=syscheck.NO_WINDOW,
            )
            return "nvidia" in (result.stdout or "").lower()
        except Exception:
            return False

    def _detect_vram_mb(self):
        """读取独显专用显存（MB），读不到返回 None。

        NVIDIA 用 nvidia-smi 精确读取；其他显卡退回 CIM AdapterRAM——
        它是 uint32，8GB 以上会回绕成 4GB 左右，因此非 N 卡最多只能
        判到“约 4GB”，宁可保守降分辨率也不冒显存不足的风险。
        """
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
                creationflags=syscheck.NO_WINDOW)
            if out.returncode == 0:
                vals = [int(t) for t in (out.stdout or "").replace(",", " ").split()
                        if t.strip().isdigit()]
                if vals:
                    return max(vals)
        except Exception:
            pass
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_VideoController | "
                 "Measure-Object -Property AdapterRAM -Maximum).Maximum"],
                capture_output=True, text=True, timeout=15,
                creationflags=syscheck.NO_WINDOW)
            s = (out.stdout or "").strip()
            if s.isdigit() and int(s) > 0:
                return int(s) // (1024 * 1024)
        except Exception:
            pass
        return None

    def _run_colmap(self, img_dir, ws_dir):
        colmap_path = resolve_path(self.colmap_var.get().strip())

        cuda_path = resolve_path(os.path.join("tools", "colmap-x64-windows-cuda", "COLMAP.bat"))
        nocuda_path = resolve_path(os.path.join("tools", "colmap-x64-windows-nocuda", "COLMAP.bat"))
        is_nvidia = self._is_nvidia_gpu()

        if not colmap_path or not os.path.exists(colmap_path):
            if is_nvidia and os.path.exists(cuda_path):
                colmap_path = cuda_path
                self._log("[INFO] 自动选择 COLMAP CUDA 版本。")
            elif os.path.exists(nocuda_path):
                colmap_path = nocuda_path
                self._log("[INFO] 自动选择 COLMAP noCUDA 版本（兼容所有显卡）。")
            else:
                repair = ("请重新运行安装程序并选择修复。"
                          if os.path.isfile(os.path.join(PROJECT_ROOT, "3DGS-Studio.exe"))
                          else "请先运行 download_tools.bat。")
                self._log(f"[FAIL] COLMAP 路径未找到，{repair}")
                return None, None, None
        else:
            if "cuda" in colmap_path.lower() and not is_nvidia and os.path.exists(nocuda_path):
                colmap_path = nocuda_path
                self._log("[INFO] 检测到非 NVIDIA GPU，自动切换到 COLMAP noCUDA 版本。")

        colmap_exe, colmap_env = self._resolve_colmap(colmap_path)
        if not os.path.exists(colmap_exe):
            self._log(f"[FAIL] colmap.exe 未找到: {colmap_exe}")
            return None, None, None

        os.makedirs(ws_dir, exist_ok=True)
        # COLMAP 直接读用户的真实照片夹：工作区里的 images 只是给训练用的，
        # 而建在工作区里的联接在某些机器上不允许被遍历（WinError 448），
        # 没必要让最耗时的重建阶段去赌这台机器的策略。
        # images_2 / images_4 的降采样副本在训练前按需生成（见 run_vksplat_train）

        db_path = os.path.join(ws_dir, "database.db")
        sparse_dir = os.path.join(ws_dir, "sparse")
        os.makedirs(sparse_dir, exist_ok=True)
        max_img = self.max_img_var.get()

        # COLMAP 三段在本阶段里的大致占比：提取 35% / 匹配 15% / 重建 50%
        cm_lo, cm_hi = self.progress.p_lo, self.progress.p_hi
        cm_span = cm_hi - cm_lo

        def sub(a, b):
            self._set_span(cm_lo + cm_span * a, cm_lo + cm_span * b)

        # 张数在特征提取前就要用：日志里能显示「共 N 张」，逐张进度也靠它
        n_imgs = self._count_images(img_dir)

        self._stage(1)
        sub(0.0, 0.35)
        self.progress.reset_colmap_timing()
        self._progress(0, f"第 1/7 步 · 正在提取照片特征（共 {n_imgs} 张）...")
        self._log("===== 步骤 1/7: COLMAP 特征提取 =====")
        if not self.run_cmd([
            colmap_exe, "feature_extractor",
            "--database_path", db_path,
            "--image_path", img_dir,
            "--FeatureExtraction.max_image_size", str(max_img),
        ], env=colmap_env, colmap=True, colmap_total=n_imgs):
            return None, None, None

        if self.stop_flag:
            return None, None, None

        matcher = pick_colmap_matcher(n_imgs)
        if matcher == "sequential":
            self._log(f"[INFO] 共 {n_imgs} 张照片（>{SEQUENTIAL_MATCHER_THRESHOLD}），"
                      f"自动切换 sequential 匹配（要求文件名按拍摄顺序命名，手机默认如此；"
                      f"若重建效果差，可按名称排序后重试）。")

        self._stage(2)
        sub(0.35, 0.50)
        self._progress(0.0, f"第 2/7 步 · 正在比对 {n_imgs} 张照片之间的重叠"
                            f"（COLMAP 这一步不报逐张进度，通常 1~2 分钟）...")
        self._log("===== 步骤 2/7: COLMAP 特征匹配 =====")
        if not self.run_cmd([
            colmap_exe, f"{matcher}_matcher",
            "--database_path", db_path,
        ], env=colmap_env, colmap=True):
            return None, None, None

        if self.stop_flag:
            return None, None, None

        self._stage(3)
        sub(0.50, 1.00)
        self.progress.reset_colmap_timing()
        self._progress(0.0, f"第 3/7 步 · 正在计算相机位置（0/{n_imgs}）...")
        self._log("===== 步骤 3/7: COLMAP 稀疏重建 =====")
        if not self.run_cmd([
            colmap_exe, "mapper",
            "--database_path", db_path,
            "--image_path", img_dir,
            "--output_path", sparse_dir,
        ], env=colmap_env, colmap=True, colmap_total=n_imgs):
            return None, None, None
        self._progress(1.0, f"照片定位完成（{n_imgs} 张）")

        sparse_zero = self._ensure_sparse_zero(sparse_dir)
        self._check_registration(colmap_exe, colmap_env, sparse_zero, n_imgs, img_dir)
        # 记下这批照片与参数：下次照片没变时可以直接复用，不必再跑一遍 COLMAP
        write_colmap_meta(ws_dir, img_dir, max_img)
        return colmap_exe, colmap_env, sparse_zero

    def _check_registration(self, colmap_exe, colmap_env, sparse_zero, n_imgs, img_dir=None):
        """mapper 后检查定位情况，必要时准备一份训练前的采集质量报告。

        过低说明照片重叠不足/缺乏纹理——现在就提示补拍，比等训练阶段报错好。
        检查本身失败不影响后续训练：报告留空，管线照跑。"""
        if not n_imgs:
            return
        try:
            r = subprocess.run(
                [colmap_exe, "model_analyzer", "--path", sparse_zero],
                capture_output=True, text=True, timeout=120, env=colmap_env,
                creationflags=syscheck.NO_WINDOW)
        except Exception as e:
            self._log(f"[WARN] 注册率检查失败（不影响训练）: {e}")
            return
        registered = parse_registered_images((r.stdout or "") + "\n" + (r.stderr or ""))
        if registered is None:
            # 静默返回过一次：统计写在 stderr，早期只读 stdout 时这道检查空转了很久没人发现。
            self._log("[WARN] 没能读到定位统计（不影响训练）。")
            return
        pct = registered / n_imgs * 100
        if registered / n_imgs < LOW_REGISTRATION_RATE:
            self._log(f"[WARN] 注册率 {pct:.0f}%（{registered}/{n_imgs} 张）："
                      f"未能定位的照片过多，通常是照片重叠不足或画面缺乏纹理。"
                      f"建议绕物体多拍一圈（每张重叠 60% 以上）后重新生成。")
        else:
            self._log(f"[INFO] 注册率 {pct:.0f}%（{registered}/{n_imgs} 张）。")

        if registered / n_imgs >= CAPTURE_WARN_RATE:
            return      # 定位得不错就别打扰用户，日志里那行百分比已经够了
        try:
            names = sorted(f for f in os.listdir(img_dir)
                           if f.lower().endswith(IMAGE_EXTS)) if img_dir else []
            reg_names = read_registered_names(sparse_zero)
            if not names or reg_names is None:
                return
            # 只有定位已经不达标时才顺手看清晰度：一批照片多花一两秒，
            # 换掉「训练两小时才发现白拍」的情况。
            blurry = pick_blurry(blur_scores(img_dir, names))
            report = build_capture_report(names, reg_names, blurry)
            if report:
                self._capture_report = report
                self._log("[WARN] 采集质量报告已生成，训练开始前会提醒一次。")
        except Exception as e:
            self._log(f"[WARN] 采集质量检查失败（不影响训练）: {e}")

    def run_vksplat_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        vksp_py = self.vksplat_py_var.get().strip() or DEFAULT_VKSPLAT_PY
        vksp_py = resolve_path(vksp_py)
        if not os.path.exists(vksp_py):
            self._log(f"[FAIL] VkSplat Python 未找到: {vksp_py}")
            return False

        # checkpoint 询问已在 UI 线程完成（ask_resume），此处只需日志
        if os.path.isfile(os.path.join(ws_dir, "checkpoint.ply")):
            self._log("[INFO] 检测到训练恢复点，将从中断处继续训练。")

        self._stage(4)
        self._set_train_span(0.0, 0.04)     # 准备阶段只占训练大段的一小截
        self._progress(0, "第 4/7 步 · 正在检查显卡并准备训练环境...")
        device_id, is_integrated, gpu_name = self._detect_gpu(vksp_py)
        quality = self.quality_var.get()
        cap_map = {"快速": 200000, "标准": 400000, "高质量": 800000}
        # 显存总量：既用于分辨率自适应，也用作进度条里「显存 X/Y GB」的分母。
        # 只在可信时给分母——核显是共享内存（与程序自身占用不是一个口径），
        # 非 N 卡的 CIM AdapterRAM 在 8GB 以上会回绕，宁可不显示也不报错数。
        vram_total_mb = None
        if not is_integrated and gpu_name != "unknown":
            vram_total_mb = self._detect_vram_mb()
            if vram_total_mb is not None and vram_total_mb < 2048:
                vram_total_mb = None
        self._vram_total_mb = vram_total_mb

        # 档位给默认值；高级选项里的「图像分辨率」可单独覆盖。
        # 用户手动选了分辨率 → 完全尊重；跟随档位 → 按显存自适应：
        # 核显共享内存、独显 <8GB 时强制降半档，避免显存不足训练崩溃。
        res_dir = RES_DIR_MAP.get(self.res_var.get())
        auto_res = res_dir is None
        if auto_res:
            res_dir = RES_DEFAULT_BY_QUALITY.get(quality, "images_2")
            if res_dir == "images":
                if is_integrated:
                    res_dir = "images_2"
                    self._log("[INFO] 核显共享内存：自动使用 1/2 分辨率"
                              "（可在高级选项手动改回）。")
                elif vram_total_mb is not None:
                    if vram_total_mb < 7500:
                        res_dir = "images_2"
                        self._log(f"[INFO] 检测到显存约 {vram_total_mb // 1024} GB（不足 8GB）："
                                  f"自动使用 1/2 分辨率（可在高级选项手动改回）。")
                    else:
                        self._log(f"[INFO] 显存 {vram_total_mb // 1024} GB：使用原分辨率训练。")
        base_cap = cap_map.get(quality, 400000)

        # 第 4 段：生成降采样/纠偏副本。它比训练快得多，但用户能看到
        # 「正在准备 128 张里的第 N 张」，不必对着不动的条猜。
        n_imgs = self._count_images(img_dir)
        res_label = {"images_4": "1/4 分辨率", "images_2": "1/2 分辨率",
                     "images": "原分辨率"}.get(res_dir, res_dir)
        self._progress(0, f"第 4/7 步 · 正在准备训练图像（{res_label}，共 {n_imgs} 张）...")

        # EXIF 方向检查：COLMAP 会应用 EXIF 旋转，而 cv2 / stb_image 不会。
        rotated = set()
        if os.path.isdir(img_dir):
            img_names = [n for n in os.listdir(img_dir) if n.lower().endswith(IMAGE_EXTS)]
            rotated = self._scan_exif_rotations(img_dir, img_names)
            if rotated:
                self._log(f"[INFO] 检测到 {len(rotated)} 张带旋转标记（EXIF）的照片，"
                          f"副本将自动纠正方向")

        # 训练读的是工作区里的 <res_dir>，副本一律**从真实照片夹**生成：工作区里那个
        # images 联接在某些机器上根本不允许被遍历（WinError 448），拿它当源等于把整条
        # 链路押在联接可用上。降采样副本幂等生成；旧版本把 images_2/images_4 联接回原图
        # 的工作区也会在此修好。曝光校正一并完成，绝不动用户原图。
        exp_fix = bool(self.exposure_fix_var.get())
        if exp_fix:
            self._log("[INFO] 曝光校正已开启：训练图将统一明暗后再训练。")
        images_dir = os.path.join(ws_dir, "images")
        if res_dir != "images":
            if not self._make_downscaled(os.path.join(ws_dir, res_dir), img_dir,
                                         2 if res_dir == "images_2" else 4,
                                         rotated_names=rotated, exposure_fix=exp_fix):
                return False
        elif rotated or exp_fix:
            # 高质量档（或开了曝光校正）：vksplat 用 stb_image 读图不认 EXIF，
            # 用方向归一化的原分辨率副本代替直通的照片目录。
            if not self._make_downscaled(images_dir, img_dir, 1,
                                         rotated_names=rotated, exposure_fix=exp_fix):
                return False
        elif not self._ensure_images_dir(images_dir, img_dir):
            return False

        if gpu_name == "unknown":
            cap_max = base_cap
            cache = self.vs_cache_var.get()
            self._log(f"[WARN] GPU 检测失败，使用: cap_max={cap_max}，图片缓存={cache}")
        elif is_integrated:
            cap_max = min(base_cap, 200000 if quality == "快速" else 300000)
            cache = "cpu"
            self._log(f"[INFO] 检测到核显: {gpu_name}，cap_max={cap_max}，图片缓存=cpu")
        else:
            cap_max = base_cap
            cache = "gpu"
            self._log(f"[INFO] 检测到独显: {gpu_name}，cap_max={cap_max}，图片缓存=gpu，分辨率={res_dir}")

        steps = self.vs_steps_var.get()
        try:
            laptop = syscheck.detect_laptop()
            measured = (syscheck.load_cache().get("measured_ips") or {}).get(quality)
            est = syscheck.estimate_train_seconds(
                {"name": gpu_name}, quality, steps, measured_ips=measured, laptop=laptop)
            note = "基于上次实测速度" if measured else "首次估算"
            tail = "（笔记本已按保守系数放大）" if (laptop and not measured) else ""
            self._log(f"[INFO] 预计训练耗时（{note}）：{syscheck.format_duration(est)}{tail}")
        except Exception:
            pass
        dataset_dir = ws_dir.replace("\\", "/")
        image_dir = res_dir
        sparse_dir = os.path.relpath(sparse_zero, ws_dir).replace("\\", "/")
        output_dir = os.path.join(PROJECT_ROOT, "outputs").replace("\\", "/")
        os.makedirs(output_dir, exist_ok=True)

        existing_dirs = set()
        if os.path.isdir(output_dir):
            for d in os.listdir(output_dir):
                if os.path.isdir(os.path.join(output_dir, d)):
                    existing_dirs.add(d)

        use_mcmc = bool(self.vs_mcmc_var.get())
        run_eval = bool(self.run_eval_var.get())
        mask_picked = self.mask_var.get().strip()
        mask_picked = resolve_path(mask_picked) if mask_picked else None
        self._log(f"[INFO] 优化策略: {'MCMC' if use_mcmc else '默认致密化（小场景兜底）'}")
        if mask_picked:
            self._log(f"[INFO] Mask 文件夹: {mask_picked}")
        if not run_eval:
            self._log("[INFO] 已关闭训练后质量评估，本次不会生成 eval.json。")

        script = self._build_vksplat_script(
            dataset_dir=dataset_dir, image_dir=image_dir,
            sparse_dir=sparse_dir, output_dir=output_dir,
            train_steps=steps, cache_device=cache,
            device_id=device_id, cap_max=cap_max,
            resume_output_dir=ws_dir.replace("\\", "/"),
            allow_lpips_download=self.lpips_dl_var.get(),
            use_mcmc=use_mcmc, run_eval=run_eval, mask_dir=mask_picked,
        )

        tmp_path = os.path.join(tempfile.gettempdir(), "vksplat_train_generated.py")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(script)
        except Exception as e:
            self._log(f"[FAIL] 无法写出训练脚本: {e}")
            return False

        self._log(f"[INFO] 生成的训练脚本: {tmp_path}")
        cwd = ws_dir
        # 记下这次「怎么跑的」，训练完成后和实测结果一起展示，也用于识别重复训练
        self.progress.set_train_params({
            "quality": quality,
            "steps": steps,
            "res_label": res_label,
            "n_imgs": n_imgs,
            "mcmc": use_mcmc,
            "run_eval": run_eval,
            "exposure_fix": exp_fix,
        })
        self._stage(5)
        self._set_train_span(0.04, 0.92)
        self._progress(0, f"第 5/7 步 · 正在训练 3D 模型（{steps} 步，这是最花时间的一段）...")
        # 崩溃自动续训：训练进程异常退出且存在恢复点时自动重跑
        ok = False
        retries = 0
        while True:
            ok = self.run_cmd([vksp_py, "-u", tmp_path], cwd=cwd, graceful_ws_dir=ws_dir)
            if ok or self.stop_flag:
                break  # 成功，或用户主动停止：不重试
            ckpt_ply = os.path.join(ws_dir, "checkpoint.ply")
            ckpt_step = os.path.join(ws_dir, "checkpoint.ply.step")
            if not (os.path.isfile(ckpt_ply) and os.path.isfile(ckpt_step)):
                self._log("[WARN] 训练异常退出，工作区没有可用恢复点，无法自动续训。")
                break
            if retries >= TRAIN_MAX_RETRIES:
                self._log(f"[FAIL] 已自动续训 {TRAIN_MAX_RETRIES} 次仍未成功，停止。")
                break
            retries += 1
            self._log(f"[WARN] 训练异常退出，{TRAIN_RETRY_DELAY} 秒后自动从恢复点续训"
                      f"（第 {retries}/{TRAIN_MAX_RETRIES} 次）…")
            self.set_status(f"训练异常，正在自动续训（第 {retries}/{TRAIN_MAX_RETRIES} 次）…")
            for _ in range(TRAIN_RETRY_DELAY):
                if self.stop_flag:
                    break
                time.sleep(1)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        if not ok:
            # 退出码非 0 不代表模型没训出来：评测阶段失败（LPIPS 权重下不下来等）
            # 也会让退出码变成 1。只要新目录里有 splat.ply 就照常收取。
            if not self._find_new_output_ply(output_dir, existing_dirs):
                return False
            self._log("[WARN] 训练进程非正常退出，但已找到 PLY 产物 —— 继续收取模型"
                      "（评测可能未完成，指标不全）。")

        quality_en = {"快速": "fast", "标准": "standard", "高质量": "high"}.get(quality, "standard")
        target_name = f"vksplat_{steps}steps_{quality_en}"
        newest = None
        if os.path.isdir(output_dir):
            for d in os.listdir(output_dir):
                full = os.path.join(output_dir, d)
                if os.path.isdir(full) and d not in existing_dirs:
                    if newest is None or os.path.getmtime(full) > os.path.getmtime(newest):
                        newest = full

        self._stage(7)
        self._set_train_span(0.99, 1.0)
        self._progress(0.0, "第 7/7 步 · 正在整理输出并导出分享版 .splat...")
        if newest:
            target = os.path.join(output_dir, target_name)
            if os.path.exists(target):
                shutil.rmtree(target)
            try:
                os.rename(newest, target)
                self._log(f"[INFO] 输出目录已重命名: {target_name}")
            except Exception as e:
                self._log(f"[WARN] 重命名输出目录失败: {e}")
                target = newest

            cleaned = 0
            for f in os.listdir(target):
                if f.startswith("val_") and f.endswith(".png"):
                    try:
                        os.remove(os.path.join(target, f))
                        cleaned += 1
                    except Exception:
                        pass
            if cleaned:
                self._log(f"[INFO] 已清理 {cleaned} 张验证图（节省空间）")

            ply_path = os.path.join(target, "splat.ply")
            if os.path.exists(ply_path):
                shutil.copy2(ply_path, output_ply)
                self._log(f"[OK] 已将 PLY 复制到: {output_ply}")
                self._export_splat(output_ply)
                self._record_training_result(ws_dir, img_dir, target, output_ply)
                self._report_eval(os.path.join(target, "eval.json"))
                return True

        if os.path.isdir(output_dir):
            newest_ply = None
            newest_mtime = 0
            for root, _dirs, files in os.walk(output_dir):
                for f in files:
                    if f.lower().endswith(".ply"):
                        full = os.path.join(root, f)
                        mt = os.path.getmtime(full)
                        if mt > newest_mtime:
                            newest_mtime = mt
                            newest_ply = full
            if newest_ply:
                shutil.copy2(newest_ply, output_ply)
                self._log(f"[OK] 已将最新 PLY 复制到: {output_ply}")
                self._export_splat(output_ply)
                self._record_training_result(ws_dir, img_dir,
                                             os.path.dirname(newest_ply), output_ply)
                self._report_eval(os.path.join(os.path.dirname(newest_ply), "eval.json"))
        return True

    def _export_splat(self, ply_path, dest=None):
        """PLY → .splat（通用 splat 查看器格式），体积约为 PLY 的 1/7。

        每个高斯 32 字节：位置 3×float32 + 尺度 3×float32（保持 log 值，
        查看器自己 exp）+ RGBA 4×uint8（颜色由 SH 直流项算出、不透明度
        sigmoid 后量化）+ 旋转四元数 4×uint8（归一化后 ×128+128）。
        只保留 DC 颜色、丢弃高阶 SH，因此只适合预览分享，训练产物仍是 PLY。

        dest 省略时写到 PLY 的同名 .splat；分享历史模型时由调用方按目录名命名，
        否则 outputs 里的 splat.ply 会转成 "splat.splat"。
        """
        splat_path = dest or os.path.splitext(ply_path)[0] + ".splat"
        try:
            import numpy as np
            with open(ply_path, "rb") as f:
                header_lines = []
                while True:
                    line = f.readline()
                    if not line:
                        raise ValueError("PLY 头部不完整")
                    header_lines.append(line)
                    if line.strip() == b"end_header":
                        break
                n_vert, props, little_endian = None, [], True
                for line in header_lines:
                    parts = line.decode("ascii", "replace").split()
                    if not parts:
                        continue
                    if parts[0] == "format":
                        little_endian = "binary_little_endian" in parts
                    elif parts[0] == "element" and len(parts) >= 3 and parts[1] == "vertex":
                        n_vert = int(parts[2])
                    elif parts[0] == "property" and len(parts) >= 3 and parts[1] == "float":
                        props.append(parts[2])
                if n_vert is None or not props:
                    raise ValueError("PLY 头部缺少 vertex/property")
                if not little_endian:
                    raise ValueError("仅支持 binary_little_endian PLY")
                idx = {p: i for i, p in enumerate(props)}
                need = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                        "scale_0", "scale_1", "scale_2",
                        "rot_0", "rot_1", "rot_2", "rot_3")
                if any(k not in idx for k in need):
                    raise ValueError("PLY 缺少必要字段（非 3DGS 布局？）")
                # 循环结束后文件位置恰好在 end_header 之后，直接读顶点数据
                data = np.frombuffer(f.read(), dtype="<f4",
                                     count=n_vert * len(props)).reshape(n_vert, len(props))

            # 中断/半成品模型可能带 NaN 高斯（训练坏点），剔除以免渲染成噪点
            need_cols = [idx[k] for k in need]
            finite = np.isfinite(data[:, need_cols]).all(axis=1)
            if not finite.all():
                skipped = int((~finite).sum())
                data = data[finite]
                n_vert = len(data)
                self._log(f"[INFO] .splat 导出已剔除 {skipped} 个异常（NaN）高斯")

            sh_c0 = 0.28209479177387814  # 1/(2*sqrt(pi))，SH 直流项系数
            rgb = np.clip(0.5 + sh_c0 * data[:, [idx["f_dc_0"], idx["f_dc_1"],
                                                  idx["f_dc_2"]]], 0.0, 1.0)
            alpha = np.clip(1.0 / (1.0 + np.exp(-data[:, idx["opacity"]])), 0.0, 1.0)
            color = np.empty((n_vert, 4), dtype=np.uint8)
            color[:, :3] = (rgb * 255.0 + 0.5).astype(np.uint8)
            color[:, 3] = (alpha * 255.0 + 0.5).astype(np.uint8)
            rot = data[:, [idx["rot_0"], idx["rot_1"], idx["rot_2"], idx["rot_3"]]]
            rot = rot / np.maximum(np.linalg.norm(rot, axis=1, keepdims=True), 1e-8)
            rotq = np.clip(rot * 128.0 + 128.0, 0, 255).astype(np.uint8)

            rec = np.zeros(n_vert, dtype=np.dtype([
                ("pos", "<f4", (3,)), ("scale", "<f4", (3,)),
                ("color", "u1", (4,)), ("rot", "u1", (4,))]))
            rec["pos"] = data[:, [idx["x"], idx["y"], idx["z"]]]
            rec["scale"] = data[:, [idx["scale_0"], idx["scale_1"], idx["scale_2"]]]
            rec["color"] = color
            rec["rot"] = rotq
            with open(splat_path, "wb") as f:
                f.write(rec.tobytes())

            ply_mb = os.path.getsize(ply_path) / 2**20
            splat_mb = os.path.getsize(splat_path) / 2**20
            pct = splat_mb / ply_mb * 100 if ply_mb else 100.0
            self._log(f"[OK] 已导出 .splat: {splat_path}"
                      f"（{splat_mb:.1f} MB，为 PLY 的 {pct:.0f}%，"
                      f"体积小、适合直接发给别人）")
            return splat_path
        except Exception as e:
            self._log(f"[WARN] .splat 导出失败（不影响 PLY）: {e}")
            return None

    def _record_training_result(self, ws_dir, img_dir, model_dir, output_ply):
        """记录「这组照片 + 这套设置」已经产出模型，供下次开始时提醒。"""
        try:
            write_train_config(ws_dir, img_dir, self._train_settings(), output_ply,
                               model_dir=model_dir,
                               actual=dict(self.progress.train_stats))
        except Exception as e:
            self._log(f"[WARN] 训练配置记录失败（不影响模型）: {e}")

    def _report_eval(self, eval_json_path):
        """训练收取完成后汇报参数与质量指标：写日志 + 弹窗（宿主负责跨线程封送）。

        评测关掉时也要弹：步数、分辨率、耗时、高斯数这些同样是用户想看的。
        """
        mean = load_eval_mean(eval_json_path)
        if mean is not None:
            verdict, level, rows = judge_eval_metrics(mean)
            summary = "  ".join(f"{n}={v}" for n, v, _ in rows)
            prefix = {"good": "[OK]", "mid": "[INFO]", "bad": "[WARN]"}.get(level, "[INFO]")
            self._log(f"{prefix} 质量评估：{verdict}（{summary}）")
        else:
            self._log("[INFO] 训练完成（未开启质量评估或评估未完成，没有 PSNR/SSIM）。")
        try:
            self.show_eval(mean, self._train_summary())
        except Exception:
            pass

    def _run_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        self._log("===== 步骤 5/7: VkSplat 训练 (Vulkan) =====")
        return self.run_vksplat_train(ws_dir, img_dir, sparse_zero, output_ply)

    def _run_viewer(self, output_ply):
        self._log("===== 步骤 7/7: 启动 VKGS 查看器 =====")
        vkgs = resolve_path(self.vkgs_var.get().strip())
        if vkgs and os.path.exists(vkgs):
            try:
                subprocess.Popen([vkgs, output_ply])
                self._log("[OK] 查看器已启动。")
            except Exception as e:
                self._log(f"[FAIL] 无法启动查看器: {e}")
        else:
            self._log(f"[WARN] VKGS 查看器未配置。输出 PLY: {output_ply}")

    # ------------------------------------------------------------- thread ----
    def pipeline_thread(self, do_colmap=True, do_train=True, reuse_colmap=False):
        self._last_failure_hint = None   # 新的运行：允许重新给出失败原因
        try:
            img_dir = resolve_path(self.img_var.get().strip())
            ws_dir = resolve_path(self.ws_var.get().strip())

            if not img_dir or not os.path.isdir(img_dir):
                self.set_status("图片文件夹无效，请重新选择。")
                self._log("[FAIL] 图片文件夹无效。")
                return

            n_imgs = self._count_images(img_dir)
            if n_imgs == 0:
                self.set_status("该文件夹里没有找到图片，请重新选择。")
                self._log(f"[FAIL] 图片文件夹里没有支持的图片: {img_dir}")
                return

            if not ws_dir:
                ws_dir = self._default_workspace(img_dir, n_imgs)
                self.set_workspace(relativize_path(ws_dir))

            os.makedirs(ws_dir, exist_ok=True)
            output_ply = self._make_output_ply_name(ws_dir)

            if do_colmap:
                if reuse_colmap:
                    # start() 已确认过；这里再验一次，防止询问期间工作区被改动
                    ok, reason = colmap_meta_matches(ws_dir, img_dir, self.max_img_var.get())
                    if ok:
                        sparse_zero = os.path.join(ws_dir, "sparse", "0")
                        self._log(f"[OK] 复用上次的空间定位结果（{n_imgs} 张），跳过 COLMAP。")
                        self.set_status("已复用上次的空间定位结果，直接开始训练。")
                        self._progress(0.0, "复用上次的空间定位结果，直接开始准备训练...")
                    else:
                        reuse_colmap = False
                        self._log(f"[WARN] 复用条件已变化（{reason}），改为重新计算空间定位。")
                if not reuse_colmap:
                    self.set_step(1)
                    self.progress.set_span(*self.progress.colmap_span)
                    self.set_status("正在识别照片中的特征点并计算相机位置...（这一步最耗时）")
                    _, _, sparse_zero = self._run_colmap(img_dir, ws_dir)
                    if sparse_zero is None:
                        self.set_status("空间定位失败，请看日志里的「原因 / 建议」，或点「导出诊断」。")
                        return
            else:
                sparse_zero = os.path.join(ws_dir, "sparse", "0")
                if not os.path.isdir(sparse_zero):
                    self.set_status("未找到已有的空间定位结果。")
                    self._log(f"[FAIL] 未找到已有 sparse/0 目录: {sparse_zero}")
                    return
                self._log(f"[INFO] 跳过 COLMAP，复用已有稀疏重建: {sparse_zero}")

            if self.stop_flag:
                return

            if do_train and not self._confirm_capture_quality():
                self.set_status("已按你的选择停在训练前：补拍后重新点「开始生成 3D 模型」。")
                return

            if do_train:
                self.set_step(2)
                self.progress.set_span(*self.progress.train_span)
                self.set_status("正在训练 3D 模型...（请耐心等待）")
                if not self._run_train(ws_dir, img_dir, sparse_zero, output_ply):
                    if self.stop_flag:
                        self.set_status("训练已安全停止，进度已保存，下次可继续。")
                    else:
                        self.set_status("模型训练失败，请看日志里的「原因 / 建议」，或点「导出诊断」。")
                    return

                if self.stop_flag:
                    return

                self.set_step(3)
                self.set_status("训练完成，正在打开 3D 查看器...")
                self._run_viewer(output_ply)
                self._log(f"[OK] 全部完成! 输出: {output_ply}")
                self._progress(1.0, "全部完成")
                self.set_status(self._done_message())
            else:
                self.set_step(1)
                self.set_status("空间定位完成。可点「开始生成 3D 模型」继续训练，或直接查看已有模型。")
                self._log("[OK] COLMAP 空间定位完成。")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log(f"[FAIL] 未预期的错误: {e}")
            self.set_status(f"发生错误: {e}")
            self._notify_failure(f"程序遇到未预期的错误：{e}", GENERIC_FAILURE[1])
        finally:
            self.set_running(False)
