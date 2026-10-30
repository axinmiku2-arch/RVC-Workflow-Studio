# 架构概览

训练入口 `training_wizard.py` → `rvc_wizard/` → RVC 预处理、训练、索引、导出子进程。分离入口 `separation_wizard.py` → `rvc_separation/` → 解码、模型处理、阶段缓存、导出。主页面 `webui.py` → `rvc_music/` 导入 → `rvc_conversion/` → 分离、RVC、可选效果、合成。GPU 任务通过 `tools/gpu_task_lock.py` 协调。

各任务目录保存状态和缓存；不要手动删除未完成任务的数据。多 WebUI 实例对同一转换任务目录的恢复存在状态冲突风险，审计见 [PROJECT_AUDIT.md](PROJECT_AUDIT.md)。
