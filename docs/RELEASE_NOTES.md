# RVC Workflow Studio v0.1.0-beta

首个公开版本，将 RVC 常用流程整合为更易操作的工作流。

- **一键训练**：导入素材、检查、训练、生成索引，试听并导出模型。
- **一键分离**：分离人声和伴奏，可选择去和声、去混响和降噪，试听后导出。
- **歌曲制作**：在原 WebUI 单次推理中依次完成分离、音色转换、可选人声效果和伴奏合成。
- **方便使用**：可试听短段、查看进度、复用阶段结果，并单独更新效果或混音。

## 使用方法

1. 下载下方的 **Source code (zip)** 并解压。
2. 在 Windows 按 [安装说明](https://github.com/axinmiku2-arch/RVC-Workflow-Studio/blob/main/docs/INSTALLATION.md) 安装 Python 3.12 和项目依赖，准备 FFmpeg、模型以及所需资源。
3. 双击 `go-webui.bat`，或运行 `go-training-wizard.bat`、`go-separation-wizard.bat`。

此发行版为源码包，不包含 Python 运行环境、模型权重或 FFmpeg。音乐解密组件未包含在源码包中，普通音频可正常导入。
