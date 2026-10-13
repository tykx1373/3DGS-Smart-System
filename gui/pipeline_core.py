# -*- coding: utf-8 -*-
"""与界面无关的 3DGS 管线核心：COLMAP 稀疏重建 → VkSplat 训练 → 收取产物。

Tk（quick_gui.QuickSplatApp）与 Qt（quick_gui_qt）两个界面都继承 PipelineCore，
管线逻辑只维护这一份。宿主界面需提供以下“接口”（鸭子类型，不强制继承）：

  变量（get/set 即可，Tk Var 或 Qt 适配对象都行）:
    img_var, ws_var, quality_var, res_var, max_img_var, vs_steps_var,
    vs_cache_var, vs_mcmc_var, run_eval_var, mask_var, lpips_dl_var,
    vksplat_py_var, colmap_var, vkgs_var
  回调（核心可能在工作线程调用，宿主自己负责线程封送）:
    _log(text), set_status(text), set_step(n), set_running(running, indeterminate),
    set_progress(frac, detail), set_workspace(path), show_eval(mean)
  仅 UI 线程调用的询问:
    ask_resume(), ask_continue(do_colmap) -> bool
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
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # 3DGS/gui
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                # 3DGS
CONFIG_PATH = os.path.join(SCRIPT_DIR, "quick_gui_config.json")

# 同目录模块（diagnostics / syscheck）
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import diagnostics  # noqa: E402
import syscheck  # noqa: E402

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

# 训练图像分辨率：质量档位给默认值，用户可在高级选项里单独覆盖
RES_AUTO = "跟随质量档位"
RES_DIR_MAP = {
    "1/4（images_4）": "images_4",
    "1/2（images_2）": "images_2",
    "原分辨率（images）": "images",
}
RES_DEFAULT_BY_QUALITY = {"快速": "images_4", "标准": "images_2", "高质量": "images"}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
# 降采样/归一化副本里标记“已按 EXIF 方向纠正”的文件。COLMAP 会应用 EXIF 方向
# 而 cv2 / stb_image 不会：手机竖拍照片（orientation=6/8）若不预旋转，
# 训练图与位姿差 90°，模型直接训废。marker 用于让旧的无纠偏副本自动失效重建。
EXIF_MARKER = ".orientation_fixed"

# 质量档位 -> (训练步数, 说明)。档位只给默认值，步数/分辨率都能在高级选项里覆盖。
QUALITY_PRESETS = {
    "快速": (5000, "约 2~3 分钟（1/4 分辨率），快速预览轮廓"),
    "标准": (15000, "约 8~10 分钟（半分辨率），推荐日常使用"),
    "高质量": (30000, "约 20 分钟+（全分辨率），细节最丰富"),
}

# tqdm 走 stderr 且用 \r 刷新，会把 stdout 的 PROGRESS 标记挤到行中间，
# 因此这里不要求行首匹配，而是在整行内查找进度标记。
_PROGRESS_RE = re.compile(r"PROGRESS:\s*(\d+)/(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)")

# 通用 tqdm 帧，形如 "Running eval:  44%|███▍ | 7/16 [02:20<03:04, 20.5s/it]"。
# 只匹配 ASCII 阶段名，避免误吃中文或路径文本。
_TQDM_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9 _\-]*?):\s*(?P<pct>\d+)%\|"
    r"[^|]*\|\s*(?P<n>\d+)/(?P<total>\d+)"
    r"(?:\s*\[(?P<elapsed>[0-9:]+)<(?P<eta>[0-9:?]+))?"
)

# ---- COLMAP 匹配器与注册率 ----
# exhaustive 匹配是 O(n²)：超过约 100 张后（尤其 noCUDA 版）会慢到不可用。
SEQUENTIAL_MATCHER_THRESHOLD = 100
# mapper 后注册率（成功定位的照片占比）低于此值时提示补拍——
# 提前诊断比等训练阶段报 "Failed to load image" 好得多。
LOW_REGISTRATION_RATE = 0.7


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


def pick_colmap_matcher(n_imgs):
    """按照片数选匹配器：大图集用 sequential（要求文件名按拍摄顺序命名，
    手机相机默认如此），小图集仍用最稳的 exhaustive。"""
    return "sequential" if n_imgs > SEQUENTIAL_MATCHER_THRESHOLD else "exhaustive"


def parse_registered_images(analyzer_output):
    """从 `colmap model_analyzer` 输出解析 Registered images 数；解析不到返回 None。"""
    m = re.search(r"Registered images:\s*(\d+)", analyzer_output or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------------- PipelineCore ----
class PipelineCore:
    """Tk / Qt 两个界面共用的管线方法集合。宿主接口见模块 docstring。"""

    def init_core(self):
        self.current_proc = None
        self.stop_flag = False
        self._ips_recorded = False
        self._last_failure_hint = None

    # ----------------------------------------------------------- start/stop ----
    def start(self, do_colmap, do_train):
        """UI 线程调用：询问恢复点/耗时后，起工作线程跑管线。"""
        self.ask_resume()
        if not self.ask_continue(do_colmap):
            return
        self._ips_recorded = False
        self.stop_flag = False
        # 纯训练用确定进度条（会被 PROGRESS 标记驱动）；其余阶段不确定
        indeterminate = not (do_train and not do_colmap)
        self.set_running(True, indeterminate)
        if not indeterminate:
            self.set_progress(0, "准备训练...")
        threading.Thread(
            target=self.pipeline_thread,
            kwargs={"do_colmap": do_colmap, "do_train": do_train},
            daemon=True).start()

    def stop_pipeline(self):
        self.stop_flag = True
        self._log("[WARN] 用户请求停止...")
        # 不在此处 terminate：训练进程由 run_cmd 通过 STOP 文件优雅停止，
        # COLMAP 等其他进程由 run_cmd 强制终止。

    # ------------------------------------------------------------- helpers ----
    def _count_images(self, folder):
        if not folder or not os.path.isdir(folder):
            return 0
        return sum(1 for f in os.listdir(folder)
                   if f.lower().endswith(IMAGE_EXTS))

    def _count_selected_images(self):
        folder = resolve_path(self.img_var.get().strip()) if self.img_var.get().strip() else ""
        if not folder or not os.path.isdir(folder):
            return None
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
        try:
            return sum(1 for f in os.listdir(folder) if f.lower().endswith(exts))
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

    def run_cmd(self, cmd_list, env=None, cwd=None, graceful_ws_dir=None, colmap=False):
        display = " ".join(f'"{c}"' if (" " in c or c == "") else c for c in cmd_list)
        self._log(">>> " + display)
        try:
            self.current_proc = subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd,
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

    def _explain_failure(self, rc, output, colmap=False):
        """把退出码翻译成人话。同一原因只讲一次，避免自动续训时重复刷屏。"""
        hint = diagnostics.explain_failure(rc, output, colmap=colmap)
        if not hint:
            return
        if hint == self._last_failure_hint:
            return
        self._last_failure_hint = hint
        cause, advice = hint
        self._log(f"[FAIL] 原因: {cause}")
        self._log(f"[WARN] 建议: {advice}")

    # -------------------------------------------------------- junction ----
    def _make_junction(self, link, target):
        target_abs = os.path.abspath(target)
        if os.path.exists(link):
            try:
                link_real = os.path.realpath(link)
                if os.path.normcase(link_real) == os.path.normcase(target_abs):
                    return True
                if os.path.islink(link):
                    os.unlink(link)
                else:
                    shutil.rmtree(link)
            except Exception:
                pass
        try:
            res = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                                 capture_output=True, text=True)
            if res.returncode == 0:
                return True
            self._log(f"[FAIL] mklink 失败: {res.stderr.strip() or res.stdout.strip()}")
            return False
        except Exception as e:
            self._log(f"[FAIL] 无法创建目录联接: {e}")
            return False

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

        只读元数据不解码像素，几百张图 1 秒内。Pillow 随 customtkinter 自带。
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

    def _make_downscaled(self, dst_dir, src_dir, factor, rotated_names=None):
        """把 src_dir 的图片按 1/factor 缩放后写入 dst_dir，文件名保持不变
        （COLMAP 的 images.bin 按文件名索引，改名就找不到图了）。

        先写 .tmp 再整体替换到位——若旧目录其实是个指向原图的联接，
        直接往里写就会覆盖用户的原图。factor=1 表示只纠偏不缩放
        （高质量档的“方向归一化原图副本”）。
        """
        import cv2
        import numpy as np

        names = [n for n in os.listdir(src_dir) if n.lower().endswith(IMAGE_EXTS)]
        if not names:
            self._log(f"[WARN] 源目录中没有图片: {src_dir}")
            return False

        rotated_names = rotated_names or set()
        has_marker = os.path.isfile(os.path.join(dst_dir, EXIF_MARKER))
        need_exif = bool(rotated_names)

        # 已是普通目录且张数对得上 → 上次生成过，直接用。但若这次检测到
        # 旋转标记而旧副本没有纠偏标记，说明旧副本方向是错的，必须重建。
        if os.path.isdir(dst_dir) and not self._is_reparse(dst_dir):
            stale = need_exif and not has_marker
            have = [n for n in os.listdir(dst_dir) if n.lower().endswith(IMAGE_EXTS)]
            if not stale and len(have) == len(names):
                self._log(f"[INFO] {os.path.basename(dst_dir)} 已存在（{len(names)} 张），跳过生成")
                return True
            if stale:
                self._log(f"[WARN] {os.path.basename(dst_dir)} 是无 EXIF 纠偏的旧副本，"
                          f"将重新生成以纠正方向")

        tmp_dir = dst_dir + ".tmp"
        if os.path.exists(tmp_dir):
            self._remove_dir_or_link(tmp_dir)
        os.makedirs(tmp_dir, exist_ok=True)

        fixed = 0
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
        os.rename(tmp_dir, dst_dir)
        if rotated_names:
            try:
                with open(os.path.join(dst_dir, EXIF_MARKER), "w") as f:
                    f.write("exif orientation fixed\n")
            except Exception:
                pass
        detail = f"，其中 {fixed} 张已按 EXIF 纠正方向" if fixed else ""
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
            )
            return "nvidia" in (result.stdout or "").lower()
        except Exception:
            return False

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
                self._log("[FAIL] COLMAP 路径未找到，请先运行 download_tools.bat。")
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
        images_link = os.path.join(ws_dir, "images")
        if not self._make_junction(images_link, img_dir):
            return None, None, None
        # images_2 / images_4 的降采样副本在训练前按需生成（见 run_vksplat_train）

        db_path = os.path.join(ws_dir, "database.db")
        sparse_dir = os.path.join(ws_dir, "sparse")
        os.makedirs(sparse_dir, exist_ok=True)
        max_img = self.max_img_var.get()

        self._log("===== 步骤 1/3: COLMAP 特征提取 =====")
        if not self.run_cmd([
            colmap_exe, "feature_extractor",
            "--database_path", db_path,
            "--image_path", images_link,
            "--FeatureExtraction.max_image_size", str(max_img),
        ], env=colmap_env, colmap=True):
            return None, None, None

        if self.stop_flag:
            return None, None, None

        n_imgs = self._count_images(img_dir)
        matcher = pick_colmap_matcher(n_imgs)
        if matcher == "sequential":
            self._log(f"[INFO] 共 {n_imgs} 张照片（>{SEQUENTIAL_MATCHER_THRESHOLD}），"
                      f"自动切换 sequential 匹配（要求文件名按拍摄顺序命名，手机默认如此；"
                      f"若重建效果差，可按名称排序后重试）。")

        self._log("===== 步骤 2/3: COLMAP 特征匹配 =====")
        if not self.run_cmd([
            colmap_exe, f"{matcher}_matcher",
            "--database_path", db_path,
        ], env=colmap_env, colmap=True):
            return None, None, None

        if self.stop_flag:
            return None, None, None

        self._log("===== 步骤 3/3: COLMAP 稀疏重建 =====")
        if not self.run_cmd([
            colmap_exe, "mapper",
            "--database_path", db_path,
            "--image_path", images_link,
            "--output_path", sparse_dir,
        ], env=colmap_env, colmap=True):
            return None, None, None

        sparse_zero = self._ensure_sparse_zero(sparse_dir)
        self._check_registration(colmap_exe, colmap_env, sparse_zero, n_imgs)
        return colmap_exe, colmap_env, sparse_zero

    def _check_registration(self, colmap_exe, colmap_env, sparse_zero, n_imgs):
        """mapper 后检查注册率（成功定位的照片占比）。

        过低说明照片重叠不足/缺乏纹理——现在就提示补拍，比等训练阶段报错好。
        检查本身失败不影响后续训练。"""
        if not n_imgs:
            return
        try:
            r = subprocess.run(
                [colmap_exe, "model_analyzer", "--path", sparse_zero],
                capture_output=True, text=True, timeout=120, env=colmap_env)
        except Exception as e:
            self._log(f"[WARN] 注册率检查失败（不影响训练）: {e}")
            return
        registered = parse_registered_images(r.stdout)
        if registered is None:
            return
        pct = registered / n_imgs * 100
        if registered / n_imgs < LOW_REGISTRATION_RATE:
            self._log(f"[WARN] 注册率 {pct:.0f}%（{registered}/{n_imgs} 张）："
                      f"未能定位的照片过多，通常是照片重叠不足或画面缺乏纹理。"
                      f"建议绕物体多拍一圈（每张重叠 60% 以上）后重新生成。")
        else:
            self._log(f"[INFO] 注册率 {pct:.0f}%（{registered}/{n_imgs} 张）。")

    def run_vksplat_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        vksp_py = self.vksplat_py_var.get().strip() or DEFAULT_VKSPLAT_PY
        vksp_py = resolve_path(vksp_py)
        if not os.path.exists(vksp_py):
            self._log(f"[FAIL] VkSplat Python 未找到: {vksp_py}")
            return False

        # checkpoint 询问已在 UI 线程完成（ask_resume），此处只需日志
        if os.path.isfile(os.path.join(ws_dir, "checkpoint.ply")):
            self._log("[INFO] 检测到训练恢复点，将从中断处继续训练。")

        device_id, is_integrated, gpu_name = self._detect_gpu(vksp_py)
        quality = self.quality_var.get()
        cap_map = {"快速": 200000, "标准": 400000, "高质量": 800000}
        # 档位给默认值；高级选项里的「图像分辨率」可单独覆盖
        res_dir = RES_DIR_MAP.get(self.res_var.get()) or \
            RES_DEFAULT_BY_QUALITY.get(quality, "images_2")
        base_cap = cap_map.get(quality, 400000)

        # EXIF 方向检查：COLMAP 会应用 EXIF 旋转，而 cv2 / stb_image 不会。
        rotated = set()
        if os.path.isdir(img_dir):
            img_names = [n for n in os.listdir(img_dir) if n.lower().endswith(IMAGE_EXTS)]
            rotated = self._scan_exif_rotations(img_dir, img_names)
            if rotated:
                self._log(f"[INFO] 检测到 {len(rotated)} 张带旋转标记（EXIF）的照片，"
                          f"副本将自动纠正方向")

        # 降采样副本幂等生成；旧版本 images_2/images_4 联接原图的工作区也会在此修好
        if res_dir != "images":
            src_images = os.path.join(ws_dir, "images")
            src_images = os.path.realpath(src_images) if os.path.isdir(src_images) else img_dir
            if os.path.isdir(src_images):
                self._make_downscaled(os.path.join(ws_dir, res_dir), src_images,
                                      2 if res_dir == "images_2" else 4,
                                      rotated_names=rotated)
        elif rotated:
            # 高质量档：vksplat 用 stb_image 读图不认 EXIF，把 junction 换成
            # 方向归一化的原分辨率副本；COLMAP 读这份也正确。
            images_link = os.path.join(ws_dir, "images")
            if os.path.isdir(images_link):
                self._make_downscaled(images_link, img_dir, 1, rotated_names=rotated)

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
                self._report_eval(os.path.join(os.path.dirname(newest_ply), "eval.json"))
        return True

    def _report_eval(self, eval_json_path):
        """训练收取完成后汇报质量指标：写日志 + 弹窗（宿主负责跨线程封送）。"""
        mean = load_eval_mean(eval_json_path)
        if mean is None:
            return  # 评测被关闭或未完成，不打扰
        verdict, level, rows = judge_eval_metrics(mean)
        summary = "  ".join(f"{n}={v}" for n, v, _ in rows)
        prefix = {"good": "[OK]", "mid": "[INFO]", "bad": "[WARN]"}.get(level, "[INFO]")
        self._log(f"{prefix} 质量评估：{verdict}（{summary}）")
        try:
            self.show_eval(mean)
        except Exception:
            pass

    def _run_train(self, ws_dir, img_dir, sparse_zero, output_ply):
        self._log("===== 步骤 4/5: VkSplat 训练 (Vulkan) =====")
        return self.run_vksplat_train(ws_dir, img_dir, sparse_zero, output_ply)

    def _run_viewer(self, output_ply):
        self._log("===== 步骤 5/5: 启动 VKGS 查看器 =====")
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
    def pipeline_thread(self, do_colmap=True, do_train=True):
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
                name = os.path.basename(img_dir.rstrip("/\\")) or "project"
                ws_dir = os.path.join(PROJECT_ROOT, "workspaces", f"{name}_{n_imgs}imgs_gs")
                self.set_workspace(relativize_path(ws_dir))

            os.makedirs(ws_dir, exist_ok=True)
            output_ply = self._make_output_ply_name(ws_dir)

            if do_colmap:
                self.set_step(1)
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

            if do_train:
                self.set_step(2)
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
                self.set_status("完成！3D 模型已生成，可随时在历史记录里重新打开。")
            else:
                self.set_step(1)
                self.set_status("空间定位完成。可点「开始生成 3D 模型」继续训练，或直接查看已有模型。")
                self._log("[OK] COLMAP 空间定位完成。")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log(f"[FAIL] 未预期的错误: {e}")
            self.set_status(f"发生错误: {e}")
        finally:
            self.set_running(False)
