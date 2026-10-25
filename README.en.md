# 3DGS Smart System — Vulkan-based 3D Gaussian Splatting Reconstruction & Real-time Rendering

English | [简体中文](README.md)

A one-stop 3D Gaussian Splatting (3DGS) pipeline for lightweight hardware: turn a set of photos into a rotatable, zoomable 3D model.

The entire pipeline is **Vulkan-based** and does not depend on CUDA. It works on any Vulkan-capable device, including NVIDIA, AMD, and Intel integrated GPUs.

```
Photo folder → COLMAP sparse reconstruction → VkSplat (Vulkan) training → VKGS real-time viewer
```

---

## Table of Contents

- [Features](#features)
- [End Users: Install from Releases (No Python Required)](#end-users-install-from-releases-no-python-required)
- [Developers: Run from Source](#developers-run-from-source)
- [System Requirements](#system-requirements)
- [Downloading and Installing Dependencies](#downloading-and-installing-dependencies)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Workflow](#workflow)
- [Quality Presets](#quality-presets)
- [FAQ](#faq)
- [Known Issues](#known-issues)
- [License](#license)

---

## Features

- **One-click pipeline** — pick photos → automatic sparse reconstruction → training → viewer, all from the GUI
- **Vulkan training** — powered by [VkSplat](https://github.com/harry7557558/vksplat), GPU acceleration across vendors (NVIDIA / AMD / Intel iGPU)
- **Dual COLMAP builds** — CUDA build (NVIDIA acceleration) and noCUDA build (pure CPU, universal), switchable in Settings
- **Real-time rendering** — based on [VKGS](https://github.com/nvpro-samples/vk_gaussian_splatting); generated PLY files can be previewed directly
- **Smart GPU adaptation** — detects discrete vs. integrated GPUs and adjusts the Gaussian cap and image cache strategy to avoid iGPU TDR timeouts
- **Three quality presets** — Fast (5,000 steps) / Standard (15,000 steps) / High (30,000 steps)
- **Resumable training** — checkpoints every 1,000 steps; after an interruption (manual stop, crash, power loss) training continues from the checkpoint instead of starting over
- **Live progress** — one unified progress bar: COLMAP advances photo by photo ("registering photo 64/128") with an ETA, and training shows step count, percentage, and current Gaussian count; the run log is collapsed by default
- **Safe stop** — clicking "Stop" during training saves the current progress and exits cleanly
- **Consistent output naming** — PLY files carry the parameters, e.g. `vksplat_15000steps_standard.ply`
- **Shareable file** — after training a much smaller `.splat` (about 1/7 of the PLY) is generated automatically; send that single file to others. The bundled VKGS viewer can open it too
- **Instant photo check** — as soon as a folder is selected, the app counts the images and flags blurry ones by name, so you do not wait tens of minutes for COLMAP to tell you the photos are unusable
- **Guided steps** — "Next" stays disabled until usable photos are selected, and the Training Settings / Run pages cannot be opened early; History, Settings, and Logs remain accessible
- **Reusable registration** — if the photos and parameters are unchanged, the app asks "Reuse (fast) / Recompute" before starting; reuse skips all three COLMAP steps
- **Training summary** — whether or not quality evaluation is enabled, a dialog lists the preset, steps, resolution, duration, Gaussian count, and peak VRAM
- **Duplicate-training warning** — if the same photos and settings have already been trained, you get "Retrain / Open existing model / Cancel" instead of waiting again
- **Capture quality feedback before training** — when registration is poor, the app lists the photos that failed and suggests how to reshoot
- **Plain-language errors** — the cause and "what to do now" appear on the Run page, with a one-click diagnostic bundle
- **Logging** — live GUI log plus rotating files in `logs/YYYYMMDD.log`
- **Background tray mode** — while a task is running, minimizing hides the window to the system tray and training continues; closing asks for confirmation first
- **Headless batch mode** — `gui/pipeline_cli.py` runs the same pipeline without the GUI for unattended jobs

---

## End Users: Install from Releases (No Python Required)

If you do not want to set up an environment, download
`3DGS-Studio-windows-x64-Setup-<version>.exe` from the
[Releases page](https://github.com/tykx1373/3DGS-Smart-System/releases) and run it.
COLMAP, VkSplat, VKGS, and a portable Python environment are all bundled.

- **No admin required**: installs to `%AppData%\3DGS-Studio` by default; the directory can be changed. Start-menu and desktop shortcuts are created automatically
- **Two COLMAP builds**: the noCUDA (pure CPU) build is always installed; on NVIDIA GPUs the CUDA build is selected by default for faster feature extraction and can be deselected in a custom install
- **Sample dataset (optional)**: 128 south-building photos (~65 MB, long edge 1600) that let you run the full pipeline once to verify the machine
- **Uninstall keeps your data**: you are asked whether to delete workspaces / outputs / logs; they are kept by default
- **Requirements**: Windows 10/11 x64, a Vulkan 1.3+ capable GPU (NVIDIA / AMD / Intel iGPU), 8 GB RAM or more (16 GB recommended for iGPUs)
- **Verify the download**: the Releases page lists the installer SHA-256; check it in PowerShell with
  `Get-FileHash .\3DGS-Studio-windows-x64-Setup-*.exe -Algorithm SHA256`
- **Uninstall**: from the Start menu or "Settings → Apps"; the uninstaller asks whether to remove `workspaces` (photo projects), `outputs` (generated models), and `logs`
- **Installer language**: the setup wizard is available in English and Simplified Chinese

> **About SmartScreen**: the installer is not code-signed yet, so Windows may show
> "Windows protected your PC" on first run. Click "More info" → "Run anyway";
> this is the standard prompt for unsigned software and does not indicate a risk.

---

## Developers: Run from Source

The following sections are for developers who want to run from source, modify the code,
or rebuild VkSplat. You will need to set up Python and the third-party tools yourself.

---

## System Requirements

| Item | Requirement |
|------|-------------|
| OS | Windows 10 / 11 (x64) |
| GPU | Any Vulkan 1.3+ capable GPU (discrete or integrated) |
| RAM | 8 GB or more (16 GB recommended for iGPUs) |
| Python | 3.9 – 3.12 (using [Miniforge](https://github.com/conda-forge/miniforge) is recommended; it ships mamba) |
| Compiler | Not required (prebuilt VkSplat `.pyd` is included). MSVC v143+ and the Vulkan SDK are only needed to rebuild it |

---

## Downloading and Installing Dependencies

The repository **does not include** third-party binaries (too large). Fetch them into `tools/` as follows.

### Option 1: One-click download script (recommended)

Run `download_tools.bat`; it fetches COLMAP, VKGS, and VkSplat:

```batch
download_tools.bat
```

The script will:

- **COLMAP** — detect the GPU and choose a build:
  - NVIDIA GPU: ask whether to install the CUDA build (recommended), the noCUDA build, or both
  - No NVIDIA GPU: download the noCUDA build directly (works on all GPUs)
- **VKGS** — download the latest Windows release from GitHub and extract it
- **VkSplat** — source and **prebuilt `.pyd`** are already in the repository and installed automatically (no compilation, no Vulkan SDK or MSVC required)
- Skip tools that already exist
- **Print manual download links if any step fails**
- Support **resumable downloads**: rerunning after an interruption continues where it stopped
- Print the follow-up conda environment and VkSplat installation commands when finished

> **Slow downloads?** COLMAP is about 360 MB and GitHub can be slow in some regions. The script:
> 1. Tries several GitHub mirrors and switches when one is too slow
> 2. Resumes downloads after an interruption or mirror switch
> 3. Also accepts manually downloaded zips placed in `tools/` with their original filenames; rerunning the script extracts them automatically
>
> If the script fails (network issues, restricted GitHub access), use Option 2 below.
>
> The GUI also detects the GPU type and selects the matching COLMAP build.

### Option 2: Manual download

#### 1. Vulkan SDK (only needed to rebuild VkSplat)

> **Not required by default.** The repository ships prebuilt `vksplat.cp*-win_amd64.pyd` for Python 3.10 and 3.11, and `download_tools.bat` uses them automatically. Install the Vulkan SDK and MSVC only if you modify VkSplat's C++ sources or use a different Python version.

Download and install the [LunarG Vulkan SDK](https://vulkan.lunarg.com/sdk/home#windows) for Windows.

Make sure `VULKAN_SDK` points to the SDK root (e.g. `C:\VulkanSDK\1.3.x.x.x`); VkSplat's `setup.py` finds it automatically.

#### 2. COLMAP (sparse reconstruction)

Two builds are available; download one or both:

| Build | When to use | Download |
|-------|-------------|----------|
| `colmap-x64-windows-cuda` | NVIDIA GPU; GPU-accelerated feature extraction (**only needs the NVIDIA driver, not the CUDA Toolkit**) | [COLMAP Releases](https://github.com/colmap/colmap/releases) (`COLMAP-x.x.x-windows-cuda.zip`) |
| `colmap-x64-windows-nocuda` | No NVIDIA GPU (AMD / Intel iGPU); pure CPU | Same page (`COLMAP-x.x.x-windows-nocuda.zip`) |

> **Note:** the COLMAP CUDA build is a prebuilt binary with the CUDA runtime statically linked; you do **not** need the CUDA Toolkit. The 3DGS pipeline itself (VkSplat training and rendering) is Vulkan-based and does not depend on CUDA; only COLMAP feature extraction can optionally use CUDA.

Extract into `tools/` so the layout is:

```
tools/
├── colmap-x64-windows-cuda/
│   └── COLMAP.bat
└── colmap-x64-windows-nocuda/
    └── COLMAP.bat
```

#### 3. VKGS (real-time viewer)

Download the latest Windows zip from
[nvpro-samples/vk_gaussian_splatting Releases](https://github.com/nvpro-samples/vk_gaussian_splatting/releases)
and extract it under `tools/`:

```
tools/
└── vkgs-2026.x.x-windows-64bits/
    └── vk_gaussian_splatting.exe
```

#### 4. VkSplat (Vulkan training backend)

VkSplat source is **included in this repository** (`tools/vksplat/`) with local modifications
(rotation-matrix alignment, simple_trainer adjustments, etc.); no submodule or patch is needed.

**Prebuilt binaries are included:** `tools/vksplat/vksplat/` contains
`vksplat.cp310-win_amd64.pyd` and `vksplat.cp311-win_amd64.pyd` for Python 3.10 and 3.11.
`download_tools.bat` detects and uses the matching one; **no Vulkan SDK or MSVC is required**.

Create the environment from `environment.yaml` using [Miniforge](https://github.com/conda-forge/miniforge).
Miniforge ships `mamba` (about 10× faster than `conda`):

```bash
# Create the environment from environment.yaml
mamba env create -f environment.yaml

# Activate it
mamba activate vksplat

# Install CPU-only PyTorch + torchmetrics (VkSplat uses Vulkan, not CUDA)
pip install torch torchmetrics --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple

# Install VkSplat (uses the prebuilt .pyd automatically)
# Rebuilding (only after modifying C++ sources) requires the Vulkan SDK and MSVC
pip install -e tools/vksplat/vksplat --no-build-isolation
```

> If your Python version does not match a prebuilt `.pyd`, `pip install -e .` will try to compile and needs the Vulkan SDK and MSVC.
> Verify the install with `import vksplat` in Python.
>
> No mamba? conda works the same: `conda env create -f environment.yaml`
>
> `download_tools.bat` performs all of these steps automatically; the manual steps are for reference.

Final `tools/` layout:

```
tools/
├── colmap-x64-windows-cuda/        # COLMAP CUDA build
├── colmap-x64-windows-nocuda/      # COLMAP noCUDA build
├── vksplat/                        # VkSplat source (pip install -e)
│   └── vksplat/
│       ├── setup.py
│       ├── src/
│       └── shader/
└── vkgs-2026.x.x-windows-64bits/   # VKGS viewer
    └── vk_gaussian_splatting.exe
```

---

## Quick Start

### Launch the GUI

Double-click `run.bat` in the repository root; it locates the `vksplat` conda environment's Python and starts the GUI.

Or manually:

```bash
conda activate vksplat
python gui/quick_gui.py
```

### Headless batch mode (unattended)

The same pipeline runs without the GUI; interactive prompts are answered automatically, which suits queuing or unattended runs:

```bash
env\vksplat\python.exe gui\pipeline_cli.py --images D:\photos\scene --quality standard
```

- `--colmap-only` runs sparse reconstruction only; `--train-only` trains from an existing `sparse/0`
- Registration is reused when possible; add `--force-colmap` to recompute
- Exit codes: 0 success / 1 failure / 2 not started / 130 interrupted by Ctrl+C (checkpoint is saved safely)

### Typical workflow

1. **Select a photo folder** — click "Browse…" (30–200 photos recommended, shot in a circle around the object with 60%+ overlap)
2. **Choose a quality preset** — Fast / Standard / High (see [Quality Presets](#quality-presets))
3. **Start** — click "Start 3D Reconstruction"; COLMAP performs sparse reconstruction, then VkSplat trains the Gaussian model, with live steps, ETA, and Gaussian count
4. **View the result** — the VKGS viewer opens automatically after training; rotate and zoom to inspect the model

> Click "Stop" to interrupt training safely: progress is saved and the GUI asks whether to resume from the checkpoint next time.

> While training or reconstruction is running, minimizing hides the window to the system tray;
> closing asks for confirmation first — choose "Minimize to tray" to keep running in the background,
> or "Cancel" to stay. Double-click the tray icon (or use "Show main window") to restore.
> When idle, minimize/close behave normally.

> If only training settings changed and the photos did not, the app asks whether to reuse the previous
> reconstruction and skip several minutes of COLMAP. If the same photos and settings were already
> trained, it offers to open the existing model instead of retraining.

> First time, or want to check whether this machine can handle it? Click "No suitable photos? Try the
> built-in sample" below the photo card; it runs the full pipeline on the 128 bundled south-building
> photos (the "Sample dataset" component must be selected during installation).

> On first use, confirm the tool paths on the Settings page and click "Save settings".

---

## Project Structure

```
3DGS/
├── run.bat                     # One-click launcher (finds the vksplat Python environment)
├── gui/
│   ├── quick_gui.py            # Main window: pages, navigation gates, host callbacks
│   ├── pages/                  # Six pages: Photos / Training / Run / History / Settings / Logs
│   ├── dialogs.py              # Training summary and environment self-check dialogs
│   ├── ui_helpers.py           # Label rows, path picker rows, duration formatting
│   ├── dataset_tools.py        # Photo formats, matcher selection, capture pre-check
│   ├── workspace_meta.py       # COLMAP / training fingerprints and reuse decisions
│   ├── model_store.py          # History model scanning and deletion
│   ├── eval_metrics.py         # eval.json metric reading and interpretation
│   ├── progress_tracker.py     # Progress spans, stage timeline, measured training stats
│   ├── qt_theme.py             # Qt style sheet and lightweight widgets (original, no third-party UI library)
│   ├── pipeline_core.py        # UI-independent pipeline core (COLMAP / training / artifacts)
│   ├── pipeline_cli.py         # Headless batch entry point
│   ├── detect_gpu.py           # Vulkan device detection (discrete / integrated adaptation)
│   └── quick_gui_config.json   # Tool path config (generated after saving)
├── tools/             # Third-party tools (download separately, see above)
│   ├── colmap-x64-windows-cuda/
│   ├── colmap-x64-windows-nocuda/
│   ├── vksplat/
│   └── vkgs-2026.2.9-windows-64bits/
├── workspaces/                 # Generated at runtime: COLMAP intermediates
├── outputs/                    # Generated at runtime: VkSplat training output
├── logs/                       # Generated at runtime: rotating log files
├── .gitignore
├── LICENSE                     # Apache-2.0
├── README.md                   # Simplified Chinese
└── README.en.md                # English
```

---

## Workflow

The GUI performs these steps:

1. **COLMAP feature extraction** — `feature_extractor`, extracting SIFT features
2. **COLMAP feature matching** — `exhaustive_matcher`, matching images pairwise
3. **COLMAP sparse reconstruction** — `mapper`, recovering camera poses and a sparse point cloud
4. **VkSplat training** — reads COLMAP's `sparse/0/` and trains the Gaussian model on Vulkan (MCMC strategy)
5. **VKGS viewing** — launches `vk_gaussian_splatting.exe` with the generated PLY

The output PLY is named `vksplat_<steps>steps_<quality>.ply` in the workspace root.

---

## Quality Presets

| Preset | Training steps | Estimated time | Use case |
|--------|----------------|----------------|----------|
| Fast | 5,000 | 2–3 minutes | Quick preview of the shape, pipeline validation |
| Standard | 15,000 | 8–10 minutes | Everyday use, recommended |
| High | 30,000 | 20+ minutes | Most detail |

> MCMC densification is used by default (automatically adds/removes Gaussians; better in most scenes).
> If a small scene (<50 images) is unstable, disable "MCMC optimization" in Advanced options to use the Default strategy.
> Integrated GPUs automatically lower the Gaussian cap (cap_max = 500,000) and use CPU image caching to avoid TDR timeouts; discrete GPUs use 1,000,000.

---

## FAQ

**Q: "Python not found" at launch?**
A: Make sure Miniforge (or Miniconda/Anaconda) is installed and the `vksplat` environment exists. `run.bat` searches common paths automatically; you can also edit `run.bat` to set the Python path.

**Q: VkSplat installation fails?**
A: The repository ships prebuilt `.pyd` files for Python 3.10/3.11 and `download_tools.bat` uses them automatically, so no compilation is needed. If you use another Python version or modified the C++ sources, install the [Vulkan SDK](https://vulkan.lunarg.com/sdk/home) and MSVC (Visual Studio Build Tools with "Desktop development with C++") and set `VULKAN_SDK`.

**Q: GPU timeout (TDR) during training?**
A: Ensure cap_max was automatically set to 500,000 on integrated GPUs; if it still times out, lower the Gaussian cap manually in Advanced options.

**Q: COLMAP reconstruction fails?**
A: Check that photos overlap enough (60%+ recommended) and number at least 30; blurry or textureless images produce too few features.

**Q: How do I open the output PLY?**
A: The GUI opens it in VKGS automatically after training; you can also use `vk_gaussian_splatting.exe` or any 3DGS-capable PLY viewer.

**Q: A "Photo check result" dialog says some photos could not be located. What now?**
A: This is the pre-training check: those photos did not produce a camera pose, usually because of insufficient overlap or blur. Choose "Reshoot" and follow the suggestions, or "Train anyway" to continue with the photos that did register. When all photos register, the dialog does not appear.

**Q: "COLMAP could not finish this step" / "COLMAP crashed"?**
A: Rerun once first. Many COLMAP failures are transient — the same photos may crash during feature extraction on the first run and produce a model with 100% registration on the second. If failures persist, review the photos (overlap, texture) or switch to the noCUDA COLMAP build in Settings.

**Q: How do I send a model to someone else?**
A: Click "Prepare share file" in the training summary, or select a model on the History page and click "Send to someone". The app prepares a much smaller `.splat` next to the PLY (about 1/7 of the size) and reveals it in the file explorer — send that file. The recipient can open it in any `.splat`-capable viewer, and "View 3D model" in this app can open it too. The shared version uses fixed lighting and looks flatter than the local preview; the full model remains the `.ply`.

**Q: Will progress be lost if training is interrupted?**
A: No. Checkpoints are saved every 1,000 steps; "Stop" saves the exact current progress. Next time the GUI detects the checkpoint and asks whether to resume. After an abnormal exit (crash/power loss), progress rolls back to the last automatic thousand-step checkpoint.

**Q: How do I check which version I installed?**
A: The window title bar and sidebar brand area show the version (e.g. `v2.4.1`); the diagnostic bundle also includes it. Compare the installer SHA-256 with the Releases page if you suspect an old build.

**Q: Where are the logs?**
A: The "Run log" expander at the bottom of the GUI shows the live log; daily logs are kept under `logs/`.

---

## Known Issues

Confirmed issues that are not fixed yet, or not yet included in a release, are tracked in [KNOWN_ISSUES.md](KNOWN_ISSUES.md) (Chinese).

---

## License

This project is released under the **Apache License 2.0**; see [LICENSE](LICENSE).

> **Apache-2.0 key points**: any use, modification, and distribution is allowed (including commercial closed-source use) as long as copyright and license notices are retained; it includes a patent grant. Derivative works may use any license; open source is not required.

### Third-party components and licenses

| Component | Integration | Purpose | License |
|-----------|-------------|---------|---------|
| [COLMAP](https://github.com/colmap/colmap) | External process | Sparse reconstruction (SfM/MVS) | BSD-3-Clause |
| [VkSplat](https://github.com/harry7557558/vksplat) | Source included (`tools/vksplat/`) | 3DGS training backend (Vulkan) | Apache-2.0 |
| [VKGS](https://github.com/nvpro-samples/vk_gaussian_splatting) | External process | Real-time viewer | MIT |
| [PySide6](https://www.qt.io/pyside) | Python dependency | GUI framework (official Qt bindings; only native widgets plus original QSS) | LGPLv3 |

> The UI uses only native PySide6 widgets and the project's own `gui/qt_theme.py` styles; no GPLv3 third-party UI library is used. LGPLv3 components are dynamically linked, which permits closed-source distribution as long as the license notices are retained and users can replace the Qt libraries.

See each upstream repository for the source code of the third-party tools.

**VkSplat modification notice (Apache-2.0 §4(b))**: this project modifies the bundled VkSplat sources as follows; each change is noted in the file header:

- `vksplat/simple_trainer.py`: added PLY checkpoint save/restore, GUI progress output (PROGRESS lines), and STOP-file safe stop
- `vksplat/src/gs_trainer.cpp`: added world-coordinate alignment rotation so COLMAP poses follow the OpenSplat convention

The original VkSplat license is at [tools/vksplat/LICENSE](tools/vksplat/LICENSE).
