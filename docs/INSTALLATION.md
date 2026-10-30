# 安装说明（Windows x64，候选版）

本说明尚未经过全新机器端到端验收。现有本机整合包可继续使用根目录的 `go-webui.bat`、`go-training-wizard.bat` 和 `go-separation-wizard.bat`。以下步骤适用于单独取得的源码候选版；尚未提供正式安装包。

## 1. 环境

准备 64 位 Windows、Python 3.12、可用的网络及足够磁盘空间。现有训练向导要求 NVIDIA CUDA；CPU/AMD 与其他系统对增强功能的兼容性尚未完成验证。NVIDIA 显卡驱动和对应 Torch 后端需要相互兼容。

在源码根目录打开 PowerShell，运行以下命令之一：

```powershell
# NVIDIA，选择与你的显卡相符的后端：cu118 或 cu128
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Backend cu118
# CPU / Windows DirectML 依赖；训练向导仍要求 NVIDIA
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Backend cpu
```

脚本创建 `.venv` 并安装原项目的依赖清单；依赖文件含版本范围及软件源，因此这还不是完全锁定、已复现的安装环境。已有 Python 3.12 可用 `-Python '完整路径\python.exe'` 指定。只需注册已有环境时可加 `-SkipDependencies`。移动项目目录后，请重新运行带 `-SkipDependencies` 的命令，更新隔离子进程的项目路径。

## 2. 额外资源

源码不附带模型、音乐、FFmpeg 或用户训练成果。训练和推理需要单独取得 HuBERT、RMVPE、对应的预训练权重，以及训练用 `logs/mute` 静音数据。路径及上游下载步骤见根目录 README 的“模型与运行目录”。在 PowerShell 中可先用 `.\.venv\Scripts\Activate.ps1` 启用项目环境，再执行下载命令。项目的 Transformers 4.49 要求 `huggingface_hub<1.0`，不要将它无约束升级到 1.x。原上游模型仓库为 <https://huggingface.co/lj1995/VoiceConversionWebUI>；2026-10-30 查得的 main 版本为 `e6d0c1a17da07c33557852f9dfa2bd44cc75737d`。具体文件可用 Hugging Face CLI 的 `--revision` 固定此版本，下载前需核实各文件的许可证及来源。

以下是无需激活虚拟环境的 PowerShell 示例，在项目根目录执行。下载及解压可能覆盖同名文件；如果目录中已有个人模型或静音数据，请先核对并备份。命令仅准备资源，不证明模型权利或性能。

```powershell
$revision = 'e6d0c1a17da07c33557852f9dfa2bd44cc75737d'
.\.venv\Scripts\python.exe -m pip install 'huggingface_hub==0.36.2'
.\.venv\Scripts\python.exe -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI --revision $revision --include 'hubert_base/*' --local-dir assets
.\.venv\Scripts\python.exe -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision $revision --local-dir assets/rmvpe
.\.venv\Scripts\python.exe -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI --revision $revision --include 'pretrained/*' 'pretrained_v2/*' --local-dir assets
.\.venv\Scripts\python.exe -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI mute.zip --revision $revision --local-dir .model-downloads
.\.venv\Scripts\python.exe -m zipfile -e .model-downloads/mute.zip logs
```

需要复用旧分离模型时，可参考 README 的 `pymss_weights/*` 下载命令；新增分离权重由分离向导管理。上面命令尚未在全新环境完整执行，具体测试范围记录在 `PROJECT_STATUS.md`。

Windows 版分离和训练目前直接寻找项目根目录 `ffmpeg.exe` 和 `ffprobe.exe`，需单独取得可信构建并核实其许可证。分离默认还依赖 Leap Xe 与温和去混响权重；下载器跳过标记为已有的温和去混响模型，其配置随源码提供，权重需要单独取得。效果器可通过 `.venv\Scripts\python.exe -I -m rvc_conversion.install_fx` 安装，当前脚本针对 Windows CPython 3.12 x64；Pedalboard 有独立许可。

## 3. 启动

完成环境和资源准备后双击 `go-webui.bat`、`go-training-wizard.bat` 或 `go-separation-wizard.bat`。启动器优先使用现有 `runtime`，否则使用 `.venv`。默认服务端口可能被占用，参照程序提示访问。原 WebUI 默认仅监听本机；如确需局域网访问，可明确设置 `RVC_WEBUI_HOST=0.0.0.0` 后启动，但服务没有因此获得身份验证，应自行隔离网络。Colab 分享模式沿用原项目行为。

## 4. 原有分离权重的来源

上游模型仓库在上述固定版本包含 `pymss_weights/dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt`、`model_bs_roformer_ep_368_sdr_12.9628.ckpt` 和 `model_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`，分别对应温和去混响、ViperX 368 和旧 Karaoke。可参照根目录下载命令将所需文件放入 `assets/pymss_weights`。仓库元数据标注 MIT，但各权重的独立来源及许可仍须核实；本项目不随源码分发它们。新增模型的下载状态和许可提示以分离向导为准。
