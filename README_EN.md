# RVC Workflow Studio

RVC Workflow Studio is an independent enhancement of [Retrieval-based-Voice-Conversion-WebUI (RVC)](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI). It brings guided training, audio separation, voice conversion, optional effects and song mixing into connected workflows. RVC already offers training, conversion and source separation; this project focuses on making those steps easier to use together. It is not an official RVC release.

**Release status:** this is a release candidate, not a finished installer. Windows clean installation and real model inference are still being validated. The [project status](PROJECT_STATUS.md) records what has and has not been tested.

## Features

- **Training wizard:** import and inspect audio, configure training, follow task progress, resume supported jobs and locate exported models.
- **Separation wizard:** process audio or video, preview a segment, select separation and optional cleanup stages, then listen and export results.
- **Song workflow:** in single inference, optionally separate and clean vocals before RVC conversion; keep the converted dry vocal, add optional effects and mix with accompaniment.
- **Music import:** the interface remains, but encrypted-file decoding is unavailable in this public source snapshot because its prebuilt worker is excluded pending third-party review. Ordinary audio import remains available.

Model results vary by source. Harmony removal and dereverberation may also change the intended vocal. Listen before exporting. See the [feature inventory](docs/FEATURE_INVENTORY.md) and [workflow guides](docs/FEATURES.md) for limitations.

## Windows setup

A 64-bit Windows system, Python 3.12, network access and sufficient disk space are needed. The training wizard currently requires an NVIDIA CUDA device. Select a compatible Torch backend; other platforms and devices have not been fully validated for the enhanced workflows.

From PowerShell in the source directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Backend cu118
# Alternatively, choose cu128 for a compatible NVIDIA device.
```

The script creates `.venv` and installs dependencies. Model weights, FFmpeg/FFprobe, training silence data and the optional Pedalboard effects are separate resources. See [installation](docs/INSTALLATION.md) for exact paths, source information, alternatives and the current limitations. Check each resource's license before use. The project does not include private recordings or private voice models.

## Getting started

1. Start `go-webui.bat` for inference and song processing, `go-training-wizard.bat` for guided training, or `go-separation-wizard.bat` for source separation.
2. Prepare the required models and audio tools as described in the installation guide. The interfaces report missing resources; model availability varies by feature.
3. Import authorized audio, choose settings, and review the output before exporting. Training and inference may take considerable GPU time.

The WebUI listens on the local machine by default. LAN access is an explicit opt-in and has not been security audited. The screenshots in the upstream README show the upstream project; screenshots for the enhanced workflows have not yet been prepared for publication.

## Troubleshooting and support

For missing models or tools, failed downloads, GPU memory errors and interrupted jobs, see [troubleshooting](docs/TROUBLESHOOTING.md). Preserve task data when investigating a failure. Do not publish private recordings, model weights, credentials or logs containing personal information. See [contributing](CONTRIBUTING.md) and [security](SECURITY.md).

## Credits and licenses

The RVC source retains its original [MIT license](LICENSE) and copyright notice. Models, FFmpeg, Pedalboard, Unlock Music and other dependencies have their own provenance and terms; the root license does not automatically apply to them. Review [third-party resources](docs/THIRD_PARTY_REVIEW.md) before redistribution. Thanks to RVC and the authors and maintainers of the other upstream components.

[中文说明](README.md) · [Architecture](docs/ARCHITECTURE.md) · [Project audit](docs/PROJECT_AUDIT.md)
