# RVC Workflow Studio

这是基于 [RVC](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) 的独立增强版，集成训练向导和歌曲分离、音色转换、效果与合成工作流。上游 RVC 本身已有训练、转换和分离能力；本项目侧重让这些操作更连贯。

常用入口：Windows 整合包双击 `go-webui.bat`；也可使用 `go-training-wizard.bat` 或 `go-separation-wizard.bat`。详见 [项目状态](PROJECT_STATUS.md)、[安装说明](docs/INSTALLATION.md)、[功能清单](docs/FEATURE_INVENTORY.md) 和 [English](README_EN.md)。以下保留原项目介绍及现有说明。

## 增强工作流快速上手

1. 完成 [Windows 安装与资源准备](docs/INSTALLATION.md)。模型、FFmpeg 和可选效果器需分别准备并检查各自许可。
2. 双击 `go-training-wizard.bat` 打开训练向导，导入有权使用的音频，检查参数、启动任务并查看进度及输出。详见 [训练向导](docs/training-wizard.html)。
3. 双击 `go-separation-wizard.bat` 打开分离向导，导入音频或视频，选取处理功能，试听后再处理和导出。详见 [分离向导](docs/separation-wizard.html)。
4. 使用 `go-webui.bat` 进入原 WebUI；单次推理可按需串联分离、音色转换、效果和伴奏合成。详见 [歌曲处理](docs/conversion-pipeline.html) 与 [音乐导入](docs/music-import.html)。

音频处理效果受素材和模型影响，请试听后选择结果。遇到缺少模型、工具、显存不足或任务中断时，参见 [常见问题](docs/TROUBLESHOOTING.md)。默认仅在本机监听，局域网访问需自行处理网络隔离。

增强页面截图将在隐私审查后补充；下方截图来自上游项目，不代表本增强版当前界面。

<div align="center">

<h1>Retrieval-based-Voice-Conversion-WebUI</h1>
简单易用的 语音音色转换/变声器 框架<br><br>

[![madewithlove](https://img.shields.io/badge/made_with-%E2%9D%A4-red?style=for-the-badge&labelColor=orange
)](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)



[![Licence](https://img.shields.io/badge/LICENSE-MIT-green.svg?style=for-the-badge)](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/main/LICENSE)
[![Huggingface](https://img.shields.io/badge/🤗%20-Models-yellow.svg?style=for-the-badge)](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main/)


[**更新日志**](./docs/cn/Changelog_CN.md) | [**常见问题解答**](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/wiki/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E8%A7%A3%E7%AD%94) | [**AutoDL·5毛钱训练AI歌手**](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/wiki/Autodl%E8%AE%AD%E7%BB%83RVC%C2%B7AI%E6%AD%8C%E6%89%8B%E6%95%99%E7%A8%8B) | [**对照实验记录**](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/wiki/%E5%AF%B9%E7%85%A7%E5%AE%9E%E9%AA%8C%C2%B7%E5%AE%9E%E9%AA%8C%E8%AE%B0%E5%BD%95) | [**在线演示**](https://modelscope.cn/studios/FlowerCry/RVCv2demo)

[**English**](./docs/en/README.en.md) | [**中文简体**](./README.md) | [**日本語**](./docs/jp/README.ja.md) | [**한국어**](./docs/kr/README.ko.md) ([**韓國語**](./docs/kr/README.ko.han.md)) | [**Français**](./docs/fr/README.fr.md) | [**Türkçe**](./docs/tr/README.tr.md) | [**Português**](./docs/pt/README.pt.md)

</div>

> 预训练模型与数据集各有许可；使用前请分别核实来源、授权和适用范围。

> 下方原项目介绍和截图用于说明上游背景，不代表本增强版的实测表现或路线图。

<table>
   <tr>
		<td align="center">训练推理界面</td>
		<td align="center">实时变声界面</td>
	</tr>
  <tr>
		<td align="center"><img src="https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/assets/129054828/092e5c12-0d49-4168-a590-0b0ef6a4f630"></td>
    <td align="center"><img src="https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/assets/129054828/730b4114-8805-44a1-ab1a-04668f3c30a6"></td>
	</tr>
	<tr>
		<td align="center">go-webui.bat</td>
		<td align="center">go-realtime_gui.bat</td>
	</tr>
  <tr>
    <td align="center">可以自由选择想要执行的操作。</td>
		<td align="center">实时延迟受设备与驱动影响；本增强版尚未验证上述运行场景。</td>
	</tr>
</table>

## 简介
本仓库具有以下特点
+ 使用top1检索替换输入源特征为训练集特征来杜绝音色泄漏
+ 即便在相对较差的显卡上也能快速训练
+ 使用少量数据进行训练也能得到较好结果(推荐至少收集10分钟低底噪语音数据)
+ 可以通过模型融合来改变音色(借助ckpt处理选项卡中的ckpt-merge)
+ 简单易用的网页界面
+ 可调用pymss/MSST模型来快速分离人声和伴奏
+ 使用最先进的[人声音高提取算法InterSpeech2023-RMVPE](#参考项目)根绝哑音问题，速度快、资源占用小
+ A卡/I卡使用 CPU 依赖方案；Windows 可使用 DirectML，Linux 使用 CPU

点此查看我们的[演示视频](https://www.bilibili.com/video/BV1pm4y1z7Gm/) !

## 环境配置

本分支面向 **Python 3.12 x64**，请先进入仓库根目录。以下 Ubuntu 说明来自现有项目，增强工作流尚未在 Ubuntu 上验收。

### Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev ffmpeg unzip libsndfile1 libportaudio2

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### Windows

安装 Python 3.12 x64 后创建虚拟环境：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
```

### 按硬件选择依赖

| 硬件 | 安装方式 |
| --- | --- |
| CPU、AMD、Intel | 使用 `requirments_cpu_py312.txt`；Windows 可使用 DirectML，Linux 使用 CPU |
| NVIDIA RTX 50 系 | 先安装 CUDA 12.8 版 Torch，再安装 `requirments_cu128_py312.txt` |
| NVIDIA RTX 50 系以前 | 先安装 CUDA 11.8 版 Torch，再安装 `requirments_cu118_py312.txt` |

#### CPU、AMD、Intel

```bash
python -m pip install -r requirments_cpu_py312.txt
```

#### NVIDIA RTX 50 系：两阶段安装

```bash
python -m pip install torch==2.7.1+cu128 torchaudio==2.7.1+cu128 \
  --index-url https://download.pytorch.org/whl/cu128 \
  --extra-index-url https://pypi.org/simple
python -m pip install -r requirments_cu128_py312.txt
```

#### NVIDIA RTX 50 系以前：两阶段安装

```bash
python -m pip install torch==2.7.1+cu118 torchaudio==2.7.1+cu118 \
  --index-url https://download.pytorch.org/whl/cu118 \
  --extra-index-url https://pypi.org/simple
python -m pip install -r requirments_cu118_py312.txt
```

检查 Torch 与 CUDA 状态：

```bash
python -c "import torch; print('torch:', torch.__version__); print('cuda:', torch.version.cuda); print('cuda available:', torch.cuda.is_available())"
```


### 修改下载源

三个 `requirments_*.txt` 顶部已经包含下载源。中国大陆用户可保留默认镜像；需要使用官方源时，只替换 `--index-url` 和 `--extra-index-url`，保留包版本、CUDA 后缀和两阶段顺序。

| Default mirror | Official source |
| --- | --- |
| `https://mirrors.pku.edu.cn/pypi/simple` | `https://pypi.org/simple` |
| `https://mirrors.nju.edu.cn/pytorch/whl/cpu` | `https://download.pytorch.org/whl/cpu` |
| `https://mirrors.nju.edu.cn/pytorch/whl/cu118` | `https://download.pytorch.org/whl/cu118` |
| `https://mirrors.nju.edu.cn/pytorch/whl/cu128` | `https://download.pytorch.org/whl/cu128` |

## 模型与运行目录

WebUI 会自动创建运行目录。模型请从 [Hugging Face 模型仓库](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main) 下载，并保持以下路径：

```text
assets/
├── hubert_base/
│   ├── config.json
│   ├── preprocessor_config.json
│   └── pytorch_model.bin
├── rmvpe/rmvpe.pt
├── pretrained/
├── pretrained_v2/
├── pymss_weights/
├── weights/        # user RVC .pth models
└── indices/        # user .index files
logs/
└── mute/           # training silence samples

# Exact paths used by the code
assets/hubert_base/config.json
assets/hubert_base/preprocessor_config.json
assets/hubert_base/pytorch_model.bin
assets/rmvpe/rmvpe.pt
assets/pretrained/*.pth
assets/pretrained_v2/*.pth
assets/pymss_weights/*
assets/weights/*.pth
assets/indices/*.index
logs/mute/*
```

### 下载模型

以下命令固定上游模型仓库版本，使用支持反斜杠续行的 shell；Windows PowerShell 请将每条命令合并为一行。在运行命令前启用项目的 `.venv`，使 `python` 指向项目环境。`huggingface_hub` 需保持低于 1.0，以兼容项目使用的 Transformers 4.49；下例指定本机已验证命令入口的 0.36.2。仓库标注 MIT 不代表每个模型的权利均已独立核实，使用前请检查相应模型来源和许可证。已有模型或 `logs/mute` 文件时，先核对并备份；下面的下载和解压命令可能覆盖同名文件。

```bash
python -m pip install "huggingface_hub==0.36.2"

# Required for inference and feature extraction
python -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI --revision e6d0c1a17da07c33557852f9dfa2bd44cc75737d \
  --include "hubert_base/*" --local-dir assets
python -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision e6d0c1a17da07c33557852f9dfa2bd44cc75737d \
  --local-dir assets/rmvpe

# Required for v1/v2 training
python -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI --revision e6d0c1a17da07c33557852f9dfa2bd44cc75737d \
  --include "pretrained/*" "pretrained_v2/*" --local-dir assets
python -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI mute.zip --revision e6d0c1a17da07c33557852f9dfa2bd44cc75737d \
  --local-dir .model-downloads
python -m zipfile -e .model-downloads/mute.zip logs

# Required only for pymss/MSST vocal separation
python -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI --revision e6d0c1a17da07c33557852f9dfa2bd44cc75737d \
  --include "pymss_weights/*" --local-dir assets
```

仅 Windows AMD/Intel DirectML 环境还需要：

```bash
python -m huggingface_hub.cli.hf download lj1995/VoiceConversionWebUI rmvpe.onnx --revision e6d0c1a17da07c33557852f9dfa2bd44cc75737d \
  --local-dir assets/rmvpe
```

### FFmpeg

Ubuntu 已在前面的系统依赖命令中安装 FFmpeg。Windows 用户可把下面两个文件放到项目根目录：

- [ffmpeg.exe](https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/ffmpeg.exe?download=true)
- [ffprobe.exe](https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/ffprobe.exe?download=true)

## 开始使用

### 中文音色训练向导（Windows 整合包）

双击 `go-training-wizard.bat`，在本机浏览器按“导入素材 → 素材体检 → 选择方案 → 开始训练 → 试听导出”训练单个音色。第一次可先选 20 轮快速试跑，再继续到 200 轮；高级选项默认收起。

[完整中文使用说明](./docs/training-wizard.html)包含素材准备、参数取舍、试听调整、停止恢复和导出说明。训练项目保存在 `logs/wizard_*`，音色模型可在原 WebUI 中使用。关闭网页后训练继续；关闭启动窗口前，建议先在向导中保存进度并停止。

### 一键分离向导（歌曲 / 视频提取干声）

双击 `go-separation-wizard.bat`，默认打开本机 `http://127.0.0.1:7899`。流程为“导入素材 → 勾选功能 → 短段试听 → 完整处理 → 试听导出”。支持多文件与视频多音轨，默认使用 Leap Xe 分离人声并温和去混响；去和声、加强去混响 / 回声、降噪按需要开启。

五个新增模型已固定版本下载，复用已有模型和 Python 环境。任务、素材副本及阶段结果位于 `logs/separation`，模型位于 `assets/pymss_weights`。停止后可继续，关闭网页后处理继续。改选项需重新处理受影响步骤；试段不会作为整首导出。默认导出 44.1kHz、双声道、24 位 WAV，也可选 FLAC 或单声道。导出到指定文件夹，重名自动编号。

页面含模型管理与训练向导入口。[完整分离说明](./docs/separation-wizard.html)包含功能选择、模型许可、试听、导出与恢复说明。原 WebUI 和训练向导新增入口及共享显卡任务锁，已在运行的旧实例需下次启动后生效；无需终止其他程序或训练任务。

### 单次推理：自动分离、效果与歌曲合成

在原 WebUI 的单次推理页上传歌曲后，可勾选“分离音频”，再点击“转换”。默认使用 Leap Xe 和温和去混响，高级设置可选去和声、加强去混响、降噪及其他分离模型。试处理30秒与整首处理分别保存。

可独立开启“添加人声效果”和“合成完整歌曲”。效果提供清晰贴近、自然空间、空灵氛围三个预设和强度滑块，转换干声始终保留。伴奏默认保持原调，也可单独变调或跟随人声调性；人声 −14 时跟随伴奏 −2，±12 时伴奏不变。试听后点击“更新效果／合成”，复用已经完成的转换干声。

任务与缓存位于 `logs/conversion_pipeline`，关闭网页后继续执行，刷新恢复最近任务。试听片段不能作为整首正式导出；完成整首后可导出24位 WAV 或 FLAC 到指定文件夹，重名自动编号。效果器使用隔离目录 `tools/audio_fx` 中固定版本 Pedalboard 0.9.25；如需补装，运行 `runtime/python.exe -I -m rvc_conversion.install_fx`，不升级其他依赖。

[完整集成使用说明](./docs/conversion-pipeline.html)。原 `infer_convert` 接口保留，新流程接口为 `infer_convert_pipeline`；批量推理保持原流程。

单次推理保留了音乐导入接口。公开源码暂不包含其解密 worker：该预构建文件的第三方依赖和授权链尚未完成核查，因此此版本的 NCM／QMC 解密功能不可用；普通音频导入及转换不依赖它。本机完整版本的原有功能说明见[自动解密导入说明](./docs/music-import.html)。

启动 WebUI：

```bash
python webui.py
```

无桌面的 Ubuntu 服务器：

```bash
python webui.py --noautoopen
```

默认服务监听端口为 `7865`。用户自己的 `.pth` 模型放入 `assets/weights/`，`.index` 文件放入 `assets/indices/`。

## 参考项目
+ [ContentVec](https://github.com/auspicious3000/contentvec/)
+ [VITS](https://github.com/jaywalnut310/vits)
+ [HIFIGAN](https://github.com/jik876/hifi-gan)
+ [Gradio](https://github.com/gradio-app/gradio)
+ [FFmpeg](https://github.com/FFmpeg/FFmpeg)
+ [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui)
+ [pymss-project/pymss](https://github.com/pymss-project/pymss)
+ [audio-slicer](https://github.com/openvpi/audio-slicer)
+ [Vocal pitch extraction:RMVPE](https://github.com/Dream-High/RMVPE)
  + The pretrained model is trained and tested by [yxlllc](https://github.com/yxlllc/RMVPE) and [RVC-Boss](https://github.com/RVC-Boss).

## 感谢所有贡献者作出的努力
<a href="https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/graphs/contributors" target="_blank">
  <img src="https://contrib.rocks/image?repo=RVC-Project/Retrieval-based-Voice-Conversion-WebUI" />
</a>
