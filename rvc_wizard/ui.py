"""Five-step Chinese Gradio 3.14 interface."""
import html
import os
from pathlib import Path
import gradio as gr
from .common import DEFAULTS, PRESETS, ROOT, STAGES, duration_text
from .guide import parameter_markdown

CSS = """
body,.gradio-container{background:#f5f7f8!important;color:#243840!important;font-family:'Microsoft YaHei UI','Segoe UI',sans-serif!important}
.gradio-container{max-width:1120px!important;margin:auto!important;padding:28px 24px 50px!important}
footer{display:none!important}h1,h2,h3{letter-spacing:0!important}.wizard-hero{padding:14px 2px 24px}.wizard-hero .eyebrow{font-size:12px;font-weight:700;letter-spacing:3px;color:#0f766e}.wizard-hero h1{font-size:34px;line-height:1.4;margin:9px 0!important}.wizard-hero p{font-size:16px;color:#607681;margin:6px 0}.wizard-hero a{color:#0f766e;font-weight:600}
.wizard-steps{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:12px 0 24px}.wizard-step{padding:15px 12px;border:1px solid #dce5e8;background:white;border-radius:12px;color:#748892}.wizard-step b{display:block;font-size:11px;letter-spacing:2px;margin-bottom:5px}.wizard-step.active{background:#0f766e;color:white;border-color:#0f766e}.wizard-step.passed{color:#0f766e;background:#ecf7f4;border-color:#c7e3dc}
.wizard-card{border:1px solid #dce5e8!important;background:#fff!important;border-radius:16px!important;padding:24px!important;margin-bottom:18px!important;box-shadow:0 5px 16px #294d5610}
.wizard-status{border:1px solid #dce5e8;background:white;padding:18px 22px;border-radius:14px;margin:8px 0 16px}.wizard-status .tag{display:inline-block;border-radius:20px;padding:3px 10px;background:#e5f4ee;color:#0f766e;font-size:12px;font-weight:bold}.wizard-status .tag.warn{background:#fff0d6;color:#a95b09}.wizard-status .tag.bad{background:#fce9e8;color:#af3f36}.wizard-status h3{margin:10px 0 6px;font-size:18px}.wizard-status p{color:#607681;margin:4px 0;overflow-wrap:anywhere}.wizard-status .bar{height:8px;border-radius:10px;background:#e7eef0;overflow:hidden;margin:15px 0 8px}.wizard-status .bar i{display:block;height:100%;background:#17a18f;border-radius:10px;transition:width .4s}.wizard-status .mini{font-size:13px}
.wizard-metrics{display:flex;flex-wrap:wrap;gap:16px}.wizard-metrics span{background:#f0f6f5;padding:10px 14px;border-radius:9px;font-size:14px}.wizard-metrics strong{color:#0f766e}.wizard-note{background:#edf8f4;padding:14px 18px;border-radius:10px;line-height:1.8;color:#3b655b}.wizard-note.warn{background:#fff7e8;color:#986223}
button.primary{background:#0f766e!important;border-color:#0f766e!important;color:white!important}button{border-radius:9px!important;min-height:42px!important;font-weight:600!important}.wizard-card table{font-size:14px!important}.wizard-card label{color:#38515c!important}#training-log textarea{font-family:Consolas,monospace!important;font-size:12px!important;line-height:1.6!important}#environment{font-size:13px;color:#667b85}
@media(max-width:700px){.gradio-container{padding:18px 12px!important}.wizard-card{padding:16px!important}.wizard-hero h1{font-size:27px}.wizard-steps{gap:5px}.wizard-step{font-size:12px;padding:10px 6px}.wizard-step b{font-size:10px}}
"""
LABELS = ["导入素材", "素材体检", "选择方案", "开始训练", "试听导出"]
CSS = CSS.replace(".wizard-card", '[id^="wizard-page-"]')
CSS += "#wizard-heartbeat{display:none!important}"
STATUS = {"draft": "等待整理", "ready": "可以继续", "checking": "素材体检中", "running": "正在训练",
          "stopping": "正在停止", "stopped": "已停止", "interrupted": "可恢复", "failed": "需要处理",
          "completed": "训练完成", "previewing": "试听转换中"}


def steps(current):
    return '<div class="wizard-steps">' + "".join(
        f'<div class="wizard-step {"active" if i == current else "passed" if i < current else ""}"><b>STEP 0{i}</b>{name}</div>'
        for i, name in enumerate(LABELS, 1)) + "</div>"


def health_report(job):
    if not job:
        return "导入后会逐个检查音频。"
    reports = [f["report"] for f in job["files"] if f["report"]]
    total = sum(r["duration"] for r in reports)
    voiced = sum(r["voiced_seconds"] for r in reports)
    text = f"### {html.escape(job['name'])} · 素材报告\n\n**{len(job['files'])} 个文件 · 总时长 {duration_text(total)} · 估算有声 {duration_text(voiced)}**\n\n"
    text += "| 文件 | 时长 | 格式信息 | 检查结果 |\n|---|---|---|---|\n"
    for f in job["files"]:
        r = f["report"]
        name = html.escape(f["original_name"]).replace("|", "\\|")
        if not r:
            text += f"| {name} | — | — | 等待检查 |\n"
        elif not r["ok"]:
            text += f"| {name} | {duration_text(r['duration'])} | — | ❌ {r['error']} |\n"
        else:
            notes = "；".join(r["warnings"]) or "数字检查通过，请仍然试听确认干净。"
            text += f"| {name} | {duration_text(r['duration'])} | {r['sample_rate']/1000:g}kHz / {r['channels']} 声道 | 静音约 {r['silence_ratio']:.0%}；{notes} |\n"
    if reports and voiced < 300:
        text += "\n> 有声素材不足 5 分钟：可以试跑，但建议增加清晰、不同音域的干声。\n"
    text += "\n数字体检不能判断伴奏残留、混响和是否混入其他人的声音。请试听并确认素材属于同一位歌手。"
    return text


def summary(job):
    if not job:
        return "选择方案后，这里显示实际训练配置。"
    s = job["settings"]
    seconds = sum((f["report"] or {}).get("duration", 0) for f in job["files"])
    return (f"### 开始前确认\n\n**音色：{html.escape(job['name'])}** · {len(job['files'])} 个文件 · {duration_text(seconds)}\n\n"
            f"方案：**{s['preset']}** · v2 / {s['sr']} / 带音高 / RMVPE\n\n"
            f"总目标 **{s['epochs']} 轮** · 每批 **{s['batch_size']}** · 预处理 **{s['workers']}** 路 · 每 **{s['save_every']}** 轮保存\n\n"
            "保存最近两组完整续训进度，每 50 轮保留试听音色。关闭网页后后台继续运行。")


def status_html(job):
    if not job:
        return '<div class="wizard-status"><span class="tag">准备开始</span><h3>把同一位歌手的干声拖进来</h3><p>无需标注或手工切片。下一步会先检查素材。</p></div>'
    state = job["status"]
    color = "bad" if state == "failed" else "warn" if state in ("stopped", "stopping", "interrupted") else ""
    p = job["progress"]
    progress = None
    detail = ""
    if p.get("epoch"):
        progress = 100 * p["epoch"] / max(1, p["total"])
        detail = f"第 {p['epoch']} / {p['total']} 轮"
        if p.get("eta") is not None:
            detail += f" · 训练阶段预计还需 {duration_text(p['eta'])}"
    elif p.get("total"):
        progress = 100 * p.get("done", 0) / max(1, p["total"])
        detail = f"已处理 {p.get('done', 0)} / {p['total']} 个文件"
    stages = dict(STAGES)
    stages.update(check="素材体检", done="试听与导出", import_="导入素材", preview="转换试听")
    name = stages.get(job["stage"], "素材准备")
    bar = f'<div class="bar" role="progressbar" aria-valuenow="{progress:.0f}" aria-valuemin="0" aria-valuemax="100"><i style="width:{min(100,progress):.1f}%"></i></div>' if progress is not None else ""
    saved = f"最近保存：第 {job['saved_epoch']} 轮" if job["saved_epoch"] else "首次训练前会自动检查所需底模与磁盘空间"
    return (f'<div class="wizard-status"><span class="tag {color}">{STATUS.get(state,state)}</span>'
            f'<h3>{html.escape(job["name"])} · {name}</h3><p>{html.escape(job["message"])}</p>{bar}'
            f'<p class="mini">{html.escape(detail)}</p><p class="mini">{saved}</p></div>')


def environment_text(root=ROOT):
    try:
        import torch
        if not torch.cuda.is_available():
            return "⚠ 没有检测到可用 NVIDIA 显卡；开始训练时会给出检查提示。"
        device = torch.cuda.get_device_properties(0)
        count = len(list((root / "assets" / "weights").glob("*.pth")))
        return f"本机运行 · {device.name} · {device.total_memory / 1024**3:.0f}GB 显存 · 已有 {count} 个音色模型"
    except Exception:
        return "⚠ 无法读取显卡环境，请查看启动窗口的提示。"


def build_ui(manager):
    def project_label(job):
        return f"{job['name']} · {job['created_at'][:19].replace('T',' ')} · {job['id'][-4:]}"

    def choices():
        return [project_label(j) for j in manager.list_jobs()]

    def file_label(i, entry):
        return f"{i+1}. {entry['original_name']}"

    def find_file(job_id, label):
        return next((f for i, f in enumerate((manager.snapshot(job_id) or {}).get("files", [])) if file_label(i, f) == label), None)

    def model_label(model):
        return f"{'最终音色' if model['final'] else '阶段音色'} · 第 {model['epoch']} 轮"

    def find_model(job_id, label):
        return next((m["path"] for m in (manager.snapshot(job_id) or {}).get("models", []) if model_label(m) == label), None)

    def nav(page):
        return [page, steps(page), *[gr.update(visible=i == page) for i in range(1, 6)]]

    def safe(fn):
        def wrapped(*args):
            try:
                return fn(*args)
            except Exception as error:
                raise gr.Error(str(error)) from error
        return wrapped

    with gr.Blocks(title="RVC 音色训练向导", css=CSS, analytics_enabled=False) as app:
        job_state = gr.State(None)
        page_state = gr.State(1)
        preview_state = gr.State(None)
        gr.HTML('<div class="wizard-hero"><div class="eyebrow">RVC · 从干声到你的音色</div><h1>音色训练，一步一步来。</h1><p>准备好干声，剩下的交给向导。第一次训练直接使用推荐方案。</p><a href="/wizard/help" target="_blank" rel="noopener">打开完整使用说明 ↗</a></div>')
        gr.Markdown(environment_text(manager.root), elem_id="environment")
        gr.HTML('<div class="wizard-note">素材有伴奏、混响或和声？<a href="/wizard/open-separation" target="_blank" rel="noopener">打开一键分离向导 ↗</a>，试听并导出干声后再拖入这里。</div>')
        with gr.Row().style(equal_height=False):
            projects = gr.Dropdown(label="找回已有项目", choices=choices(), interactive=True)
            refresh = gr.Button("刷新列表")
            load = gr.Button("载入项目")
            new = gr.Button("新建音色")
        stepper = gr.HTML(steps(1))
        banner = gr.HTML(status_html(None))
        groups = []
        with gr.Group(visible=True, elem_id="wizard-page-1") as group:
            groups.append(group)
            gr.Markdown("## ① 导入你的干声\n一次训练一个音色。可以拖入同一位歌手的多首歌曲或多段录音。")
            name = gr.Textbox(label="给这个音色起个名字", placeholder="例如：我的唱歌音色", value="我的音色")
            uploads = gr.File(label="把干声音频拖到这里，也可以点击选择", file_count="multiple", type="file", file_types=["audio"], elem_id="audio-import")
            with gr.Row():
                imported_preview = gr.Dropdown(label="选择一个导入文件试听", choices=[], interactive=True)
                source_player = gr.Audio(label="素材试听", type="filepath", interactive=False)
            gr.HTML('<div class="wizard-note">同一位歌手 · 清晰干声 · 尽量覆盖不同音域。无需文字标注，无需提前切成小段。</div>')
            next1 = gr.Button("下一步：检查素材 →", variant="primary")
        with gr.Group(visible=False, elem_id="wizard-page-2") as group:
            groups.append(group)
            gr.Markdown("## ② 看看素材是否准备好了\n音频会逐个检查。发现无效文件时，可以直接从这个项目移除。")
            report = gr.Markdown("等待素材检查。")
            with gr.Row():
                remove_choice = gr.Dropdown(label="项目内的素材（也可选择试听）", choices=[], interactive=True)
                remove_button = gr.Button("移除选中的素材")
                recheck = gr.Button("重新检查")
            checked_player = gr.Audio(label="检查后仍建议试听确认", type="filepath", interactive=False)
            with gr.Row():
                back2 = gr.Button("← 上一步")
                next2 = gr.Button("下一步：选择训练方案 →", variant="primary", visible=False)
        with gr.Group(visible=False, elem_id="wizard-page-3") as group:
            groups.append(group)
            gr.Markdown("## ③ 不懂参数，就选推荐方案\n素材优质时可直接正式训练；第一次也可以先试跑，再继续训练到 200 轮。")
            preset = gr.Radio(label="这次怎样训练？", choices=PRESETS, value=DEFAULTS["preset"], interactive=True)
            preset_note = gr.Markdown("**正式训练：200 轮。** 优质干声的起点，最终效果需要用独立干声试听判断。")
            with gr.Accordion("高级设置 · 需要时再调整", open=False):
                sr = gr.Radio(label="模型采样率", choices=["40k", "48k"], value="40k", interactive=True)
                epochs = gr.Slider(1, 1200, value=200, step=1, label="总训练目标（轮）", interactive=True)
                batch = gr.Slider(1, 40, value=6, step=1, label="每批训练数量（显存不足会自动降低）", interactive=True)
                workers = gr.Slider(1, min(16, os.cpu_count() or 1), value=min(4, os.cpu_count() or 1), step=1, label="预处理并行数", interactive=True)
                interval = gr.Slider(1, 50, value=5, step=1, label="每多少轮保存续训进度", interactive=True)
            with gr.Accordion("这些选项是什么意思？", open=False):
                gr.Markdown(parameter_markdown())
            with gr.Row():
                back3 = gr.Button("← 上一步")
                next3 = gr.Button("下一步：确认训练 →", variant="primary")
        with gr.Group(visible=False, elem_id="wizard-page-4") as group:
            groups.append(group)
            configuration = gr.Markdown("选择方案后显示训练摘要。")
            stages_view = gr.Markdown("整理与切片 → 提取音高 → 声音特征 → 训练音色 → 生成索引")
            with gr.Row():
                start = gr.Button("确认并开始训练", variant="primary")
                retry = gr.Button("继续 / 重试")
                stop = gr.Button("保存进度并停止")
                force = gr.Button("立即停止（回到最近保存）")
            gr.Markdown("正常停止会等待当前轮次完成后保存。关闭网页后训练继续；需要关闭程序时，建议先停止并等待保存完成。")
            with gr.Accordion("查看详细日志", open=False):
                console = gr.Textbox(label="运行记录（最近 50 行）", lines=14, interactive=False, elem_id="training-log")
                error_file = gr.File(label="完整错误记录", interactive=False, visible=False)
            with gr.Row():
                back4 = gr.Button("← 上一步")
                next4 = gr.Button("进入试听与导出 →", variant="primary", visible=False)
        with gr.Group(visible=False, elem_id="wizard-page-5") as group:
            groups.append(group)
            gr.Markdown("## ⑤ 听一听，再保存你的音色\n用**没有参加训练的干声**做测试，比较低音、中音、高音与咬字。")
            model = gr.Dropdown(label="选择要试听或导出的音色", choices=[], interactive=True)
            test_audio = gr.Audio(label="拖入独立的测试干声（建议 15～30 秒）", source="upload", type="filepath", interactive=True)
            semitones = gr.Slider(-24, 24, value=0, step=1, label="升降调（半音，0 为原调）", interactive=True)
            with gr.Accordion("试听微调 · 声音不像或辅音异常时再试", open=False):
                index_rate = gr.Slider(0, 1, value=0.75, step=0.05, label="索引混合比例（较高时更靠近训练音色）", interactive=True)
                protect = gr.Slider(0, 0.5, value=0.33, step=0.01, label="辅音保护（数值越小保护越强，0.5 接近关闭）", interactive=True)
            convert = gr.Button("转换并试听", variant="primary")
            converted = gr.Audio(label="转换结果 · 和上方原声对比", type="filepath", interactive=False)
            with gr.Row():
                export = gr.Button("打包导出选中的音色")
                package = gr.File(label="模型 + 索引 + 使用说明", interactive=False)
            with gr.Accordion("继续训练到更多轮次", open=False):
                target = gr.Number(value=200, label="新的总训练目标（不是追加轮数）", precision=0)
                continue_button = gr.Button("保存设置并继续训练")
            back5 = gr.Button("← 返回训练记录")

        navigation = [page_state, stepper, *groups]
        heartbeat = gr.Button("更新训练状态", elem_id="wizard-heartbeat")

        def do_import(job_id, display_name, files):
            if job_id:
                if files:
                    manager.add_files(job_id, files)
                manager.update(job_id, name=(display_name or "我的音色").strip()[:80])
            else:
                job_id = manager.create(display_name, files)
            manager.check(job_id)
            return [job_id, *nav(2), gr.update(choices=choices(), value=project_label(manager.snapshot(job_id)))]

        next1.click(safe(do_import), [job_state, name, uploads], [job_state, *navigation, projects], queue=False)

        def uploaded(files):
            selected = [f"{i+1}. {Path(getattr(f,'orig_name',f.name)).name}" for i, f in enumerate(files or [])]
            return gr.update(choices=selected, value=selected[0] if selected else None)

        uploads.change(uploaded, [uploads], [imported_preview], queue=False)
        imported_preview.change(lambda label, files: files[int(label.split('. ',1)[0])-1].name if label and files else None, [imported_preview, uploads], [source_player], queue=False)
        remove_choice.change(lambda job_id, label: (find_file(job_id, label) or {}).get("path"), [job_state, remove_choice], [checked_player], queue=False)
        remove_button.click(safe(lambda jid, label: manager.remove_file(jid, (find_file(jid, label) or {})["id"])), [job_state, remove_choice], [], queue=False)
        recheck.click(safe(manager.check), [job_state], [], queue=False)

        def next_check(job_id):
            if "check" not in manager.snapshot(job_id)["completed_stages"]:
                raise ValueError("先完成体检，并移除或替换无效文件。")
            return nav(3)

        next2.click(safe(next_check), [job_state], navigation, queue=False)

        def choose_preset(value):
            if value == "自定义":
                return ["按你的需求调整高级设置。采样率只能在开始处理之前更换。", *[gr.update() for _ in range(5)]]
            count = 20 if value == PRESETS[1] else 200
            note = "**快速试跑：20 轮。** 检查流程与初步试听，完成后可继续到 200 轮。" if count == 20 else "**正式训练：200 轮。** 优质干声的起点，最终效果需要用独立干声试听判断。"
            return [note, "40k", count, 6, min(4, os.cpu_count() or 1), 5]

        preset.change(choose_preset, [preset], [preset_note, sr, epochs, batch, workers, interval], queue=False)

        def configure(job_id, p, sample_rate, count, size, parallel, save):
            manager.configure(job_id, p, sample_rate, count, size, parallel, save)
            return [*nav(4), summary(manager.snapshot(job_id))]

        next3.click(safe(configure), [job_state, preset, sr, epochs, batch, workers, interval], [*navigation, configuration], queue=False)
        start.click(safe(manager.start), [job_state], [], queue=False)
        retry.click(safe(manager.start), [job_state], [], queue=False)
        stop.click(lambda: manager.stop(), [], [], queue=False)
        force.click(lambda: manager.stop(immediate=True), [], [], queue=False)

        def to_results(job_id):
            job = manager.snapshot(job_id)
            if not job["models"] or not job["index"]:
                raise ValueError("模型与索引尚未完成，请先继续 / 重试。")
            models = sorted(job["models"], key=lambda m: (m["epoch"], m["final"]), reverse=True)
            return [*nav(5), gr.update(choices=[model_label(m) for m in models], value=model_label(models[0]))]

        next4.click(safe(to_results), [job_state], [*navigation, model], queue=False)
        convert.click(safe(lambda jid, label, audio, shift, rate, p: manager.preview(jid, find_model(jid, label), audio, shift, rate, p)), [job_state, model, test_audio, semitones, index_rate, protect], [], queue=False)
        export.click(safe(lambda jid, label: manager.export(jid, find_model(jid, label))), [job_state, model], [package], queue=False)

        def continue_training(job_id, goal):
            job = manager.snapshot(job_id)
            if int(goal) <= job["saved_epoch"]:
                raise ValueError(f"新目标应高于已保存的 {job['saved_epoch']} 轮。")
            s = job["settings"]
            manager.configure(job_id, "自定义", s["sr"], goal, s["batch_size"], s["workers"], s["save_every"])
            manager.start(job_id)
            return [*nav(4), "自定义", s["sr"], int(goal), s["batch_size"], s["workers"], s["save_every"]]

        continue_button.click(safe(continue_training), [job_state, target], [*navigation, preset, sr, epochs, batch, workers, interval], queue=False)
        for button, number in [(back2, 1), (back3, 2), (back4, 3), (back5, 4)]:
            button.click(lambda n=number: nav(n), [], navigation, queue=False)
        refresh.click(lambda: gr.update(choices=choices()), [], [projects], queue=False)

        def restore(job_id):
            job = manager.snapshot(job_id)
            if not job:
                raise ValueError("请先在列表中选择已有项目。")
            s = job["settings"]
            page = 5 if job["models"] and job["index"] and job["status"] not in ("running", "stopping") else 4 if "prepare" in job["completed_stages"] or job["status"] in ("running", "stopping", "failed", "interrupted", "stopped") else 3 if "check" in job["completed_stages"] else 2
            goal = max(200, job["saved_epoch"] + 50)
            candidates = list(manager.directory(job_id).glob("test-input.*"))
            source = job.get("test_source") or (str(max(candidates, key=lambda p: p.stat().st_mtime)) if candidates else None)
            source = source if source and Path(source).is_file() else None
            models = sorted(job["models"], key=lambda m: (m["epoch"], m["final"]), reverse=True)
            selected = gr.update(choices=[model_label(m) for m in models], value=model_label(models[0]) if models else None)
            exported = job.get("export_path")
            exported = exported if exported and Path(exported).is_file() else None
            return [job_id, *nav(page), job["name"], None, s["preset"], s["sr"], s["epochs"], s["batch_size"], s["workers"], s["save_every"], None, exported, goal, source, None, selected]

        restore_outputs = [job_state, *navigation, name, uploads, preset, sr, epochs, batch, workers, interval, preview_state, package, target, test_audio, converted, model]
        load.click(safe(lambda label: restore(next((j['id'] for j in manager.list_jobs() if project_label(j) == label), None))), [projects], restore_outputs, queue=False)

        def new_project():
            return [None, *nav(1), "我的音色", None, DEFAULTS["preset"], "40k", 200, 6, min(4, os.cpu_count() or 1), 5, None, None, 200, None, None, gr.update(choices=[], value=None)]

        new.click(new_project, [], restore_outputs, queue=False)

        def poll(job_id, file_id, selected_model, last_preview):
            job = manager.snapshot(job_id)
            if not job:
                return [status_html(None), health_report(None), summary(None), gr.update(choices=[], value=None),
                        gr.update(choices=[], value=None), gr.update(), last_preview, gr.update(visible=False),
                        gr.update(visible=False), "等待开始。", "", gr.update(value=None, visible=False),
                        *[gr.update(visible=False) for _ in range(4)]]
            file_choices = [file_label(i, f) for i, f in enumerate(job["files"])]
            if file_id not in file_choices:
                file_id = file_choices[0] if file_choices else None
            models = sorted(job["models"], key=lambda m: (m["epoch"], m["final"]), reverse=True)
            model_choices = [model_label(m) for m in models]
            if selected_model not in model_choices:
                selected_model = model_choices[0] if model_choices else None
            busy = job["status"] in ("checking", "running", "stopping", "previewing")
            if busy and job["stage"] in ("pitch", "features"):
                directory = manager.directory(job_id)
                total = len(list((directory / "1_16k_wavs").glob("*.wav")))
                folder = "2b-f0nsf" if job["stage"] == "pitch" else "3_feature768"
                done = len(list((directory / folder).glob("*.npy")))
                job["progress"] = {"done": min(done,total), "total": total}
            stage_text = "\n\n".join(f"{'✅' if stage in job['completed_stages'] else '⏳' if stage == job['stage'] and busy else '○'} **{label}**" for stage, label in STAGES)
            preview = job["preview"]
            audio_update = gr.update(value=preview) if preview != last_preview else gr.update()
            error = manager.directory(job_id) / "wizard-error.log"
            can_start = not busy and "check" in job["completed_stages"] and job["status"] != "completed"
            return [status_html(job), health_report(job), summary(job), gr.update(choices=file_choices, value=file_id),
                    gr.update(choices=model_choices, value=selected_model), audio_update, preview,
                    gr.update(visible="check" in job["completed_stages"] and not busy),
                    gr.update(visible=bool(models and job["index"]) and not busy), stage_text, manager.log_tail(job_id),
                    gr.update(value=str(error) if error.exists() else None, visible=error.exists()),
                    gr.update(visible=can_start and "prepare" not in job["completed_stages"]), gr.update(visible=can_start and "prepare" in job["completed_stages"]), gr.update(visible=busy), gr.update(visible=busy)]

        # Gradio 3.14's `every` freezes inputs at page load. Re-dispatch a small
        # ordinary event instead, so job selection and component state stay current.
        heartbeat.click(poll, [job_state, remove_choice, model, preview_state],
                 [banner, report, configuration, remove_choice, model, converted, preview_state, next2, next4, stages_view, console, error_file, start, retry, stop, force], queue=False, show_progress=False)
        app.load(None, [], [], _js="""() => {
            const root=document.querySelector('gradio-app')?.shadowRoot || document;
            root.querySelectorAll('.dark').forEach(node => node.classList.remove('dark'));
            clearInterval(window.rvcWizardHeartbeat);
            window.rvcWizardHeartbeat = setInterval(() => {
                const nodes = document.createTreeWalker(root.querySelector('#audio-import') || root, NodeFilter.SHOW_TEXT);
                while(nodes.nextNode()) {
                    const n=nodes.currentNode;
                    n.textContent=n.textContent.replace('Drop File Here','把干声音频拖到这里').replace('Click to Upload','点击选择文件').replace(' - or - ',' · 或 · ');
                }
                root.querySelector('#wizard-heartbeat')?.click();
            }, 2000);
            return [];
        }""")

        # A refresh restores the active job, otherwise the latest saved project.
        def initial():
            jobs = manager.list_jobs()
            if not jobs:
                return [*new_project(), gr.update(choices=choices(), value=None)]
            job_id = manager.active_id or jobs[0]["id"]
            return [*restore(job_id), gr.update(choices=choices(), value=project_label(manager.snapshot(job_id)))]

        app.load(initial, [], [*restore_outputs, projects])
    return app
