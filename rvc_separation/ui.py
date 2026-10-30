"""Five-step Chinese UI on the existing Gradio 3.14 runtime."""
import html
import os
import subprocess
from pathlib import Path
import gradio as gr
from rvc_wizard.ui import CSS
from .backend import DEFAULTS, BUSY, normalize
from .engine import RESULT_LABELS
from .models import MODELS, ROOT, available, read_json, STATE
from .audio import process_options

LABELS = ["导入素材", "勾选功能", "短段试听", "完整处理", "试听导出"]
CSS = CSS.replace("wizard-page-", "separation-page-") + "#separation-heartbeat{display:none!important}.separation-links a{color:#0f766e;font-weight:600;margin-right:24px}.separation-result-note{font-size:13px;color:#607681}"
CSS += """
button.gr-button-primary{background:#0f766e!important;border-color:#0f766e!important;color:white!important}
button.gr-button-primary:hover{background:#115e59!important}input[type=checkbox],input[type=radio]{accent-color:#0f766e!important}
.gradio-container input,.gradio-container textarea,.gradio-container select{font-family:'Microsoft YaHei UI','Segoe UI',sans-serif!important}
.gradio-container [id^='separation-page-']{scroll-margin-top:24px}
"""
SEP_CHOICES = {MODELS[key]["label"]: key for key in ("leap", "deux", "viper")}
KAR_CHOICES = {MODELS[key]["label"]: key for key in ("karaoke", "old_karaoke")}
REV_CHOICES = {"关闭": "off", "温和 · 保留音色与尾音": "gentle", "加强 · 去混响及延迟回声": "fused"}
KEEP_CHOICES = {"人声 / 干声": "vocals", "伴奏": "instrumental"}
RESULT_CHOICES = {label: key for key, label in RESULT_LABELS.items()}


def steps(current):
    return '<div class="wizard-steps">' + "".join(f'<div class="wizard-step {"active" if i == current else "passed" if i < current else ""}"><b>STEP 0{i}</b>{label}</div>' for i, label in enumerate(LABELS, 1)) + "</div>"


def banner(job):
    if not job:
        return '<div class="wizard-status"><span class="tag">准备开始</span><h3>把歌曲拖进来，先听一小段。</h3><p>勾选需要的功能，试听满意后处理整首，再导出干声。</p></div>'
    percent = max(0, min(100, job["progress"]))
    label = {"ready": "准备试听", "running": "正在处理", "waiting": "显卡排队中", "stopping": "正在停止", "stopped": "可继续", "failed": "需要处理", "interrupted": "可恢复", "completed": "已完成"}.get(job["status"], job["status"])
    return (f'<div class="wizard-status"><span class="tag {"bad" if job["status"] == "failed" else ""}">{label}</span>'
            f'<h3>{html.escape(job.get("current_file") or job["name"])}</h3><p>{html.escape(job["message"])}</p>'
            f'<div class="bar" role="progressbar" aria-valuenow="{percent:.0f}" aria-valuemin="0" aria-valuemax="100"><i style="width:{percent:.1f}%"></i></div>'
            f'<p class="mini">{percent:.1f}% · 关闭网页后后台继续，重新打开可恢复任务。</p></div>')


def model_report(manager):
    state = read_json(STATE, {}) or {}
    lines = ["| 模型 | 用途 | 状态 |", "|---|---|---|"]
    purpose = {"leap": "默认分离", "deux": "分离对比", "karaoke": "去和声", "fused": "加强去混响 / 回声", "denoise": "降噪", "gentle": "温和去混响", "viper": "快速分离", "old_karaoke": "旧主唱提取"}
    for key, spec in MODELS.items():
        status = "✅ 可用" if available(key) else "已下载，待推理验证" if state.get(key, {}).get("downloaded") else "待下载"
        lines.append(f"| {spec['label']} | {purpose[key]} | {status} |")
    return "\n".join(lines) + "\n\n" + manager.model_status + ("\n\n" + manager.model_error if manager.model_error else "")


def browse_folder(current):
    # Native picker is created only in response to this button, never at startup.
    code = "import tkinter as tk; from tkinter import filedialog; import sys; root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True); value=filedialog.askdirectory(title='选择干声导出文件夹', initialdir=sys.argv[1]); print(value,flush=True); root.destroy()"
    import sys
    selected = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code, str(current or ROOT)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", **process_options())
    if selected.returncode:
        raise gr.Error("无法打开文件夹选择器，请手动填写目标路径。")
    return selected.stdout.strip() or current


def build_ui(manager):
    def safe(fn):
        def wrapped(*args):
            try:
                return fn(*args)
            except Exception as error:
                raise gr.Error(str(error)) from error
        return wrapped

    def job_label(job):
        return f"{job['name']} · {len(job['files'])} 个文件 · {job['id'][-8:]}"

    def job_choices():
        return [job_label(j) for j in manager.list_jobs()]

    def file_choices(job):
        return [f"{i + 1}. {f['name']}" for i, f in enumerate(job["files"])] if job else []

    def find_file(job_id, label):
        job = manager.snapshot(job_id)
        if not job:
            return None
        return next((f for i, f in enumerate(job["files"]) if label == f"{i + 1}. {f['name']}"), None)

    def settings(sep, sep_model, keep, harmony, kar_model, rev, noise):
        return normalize(dict(separate=bool(sep), separator=SEP_CHOICES[sep_model], keep=[KEEP_CHOICES[c] for c in keep],
                              harmony=bool(harmony), karaoke=KAR_CHOICES[kar_model], dereverb=REV_CHOICES[rev], denoise=bool(noise)))

    def file_report(job):
        if not job:
            return "导入后会显示音轨、时长和声道信息。"
        text = "| 文件 | 时长 | 原始音轨 |\n|---|---|---|\n"
        for entry in job["files"]:
            track = entry["tracks"][entry["track"]]
            name = html.escape(entry["name"]).replace("|", "\\|")
            text += f"| {name} | {entry['duration']:.1f} 秒 | 第 {entry['track'] + 1} / {len(entry['tracks'])} 条 · {track['channels']} 声道 · {track['sample_rate'] / 1000:g}kHz |\n"
        return text

    def result_options(job_id, mode, file_label):
        entry = find_file(job_id, file_label)
        result = next((r for r in manager.results(job_id, mode) if entry and r["file_id"] == entry["id"]), None)
        if not result:
            return {}, None
        options = {RESULT_LABELS[key]: path for key, path in result["outputs"].items()}
        return options, result

    with gr.Blocks(title="RVC 一键分离向导", css=CSS, analytics_enabled=False) as app:
        job_state = gr.State(None)
        page_state = gr.State(1)
        display_state = gr.State(None)
        gr.HTML('<div class="wizard-hero"><div class="eyebrow">RVC · 从歌曲到干净干声</div><h1>把人声留下来。</h1><p>拖入歌曲或视频，勾选需要的功能。先听一小段，满意后处理整首。</p><div class="separation-links"><a href="/separation/open-training" target="_blank">打开训练向导 ↗</a><a href="/separation/help" target="_blank">使用说明 ↗</a></div></div>')
        with gr.Row().style(equal_height=False):
            projects = gr.Dropdown(label="找回已有分离任务", choices=job_choices(), interactive=True)
            refresh = gr.Button("刷新任务")
            restore_button = gr.Button("载入任务")
            new_button = gr.Button("新建分离")
        stepper = gr.HTML(steps(1))
        status = gr.HTML(banner(None))
        notice = gr.Markdown("")
        groups = []
        with gr.Group(visible=True, elem_id="separation-page-1") as group:
            groups.append(group)
            gr.Markdown("## ① 导入歌曲或视频\n可以一次导入多个素材。视频默认读取第一条音轨，可在下面切换。")
            uploads = gr.File(label="把音频或视频拖到这里，也可以点击选择", file_count="multiple", type="file", elem_id="separation-import")
            import_button = gr.Button("导入素材", variant="primary")
            report = gr.Markdown("导入后会显示音轨、时长和声道信息。")
            source_file = gr.Dropdown(label="选择素材试听 / 设置音轨", choices=[], interactive=True)
            audio_track = gr.Dropdown(label="所选素材的音轨", choices=[], interactive=True)
            source_player = gr.Audio(label="所选音轨原声", type="filepath", interactive=False)
            next1 = gr.Button("下一步：勾选功能 →", variant="primary")
        with gr.Group(visible=False, elem_id="separation-page-2") as group:
            groups.append(group)
            gr.Markdown("## ② 勾选需要的功能\n推荐先使用人声分离 + 温和去混响，尽量保留音色、咬字、气声与尾音。")
            separate = gr.Checkbox(label="人声 / 伴奏分离", value=True)
            sep_model = gr.Dropdown(label="分离模型", choices=list(SEP_CHOICES), value=MODELS["leap"]["label"], interactive=True)
            keep = gr.CheckboxGroup(label="希望保留的部分", choices=list(KEEP_CHOICES), value=["人声 / 干声"])
            harmony = gr.Checkbox(label="去和声 / 提取主唱", value=False)
            kar_model = gr.Dropdown(label="主唱提取模型", choices=list(KAR_CHOICES), value=MODELS["karaoke"]["label"], interactive=False)
            dereverb = gr.Radio(label="去混响 / 回声", choices=list(REV_CHOICES), value="温和 · 保留音色与尾音", interactive=True)
            denoise = gr.Checkbox(label="降噪（仅在有明显噪声时开启）", value=False)
            gr.HTML('<div class="wizard-note">加强去混响可能减少和声、叠唱与尾音。主唱提取不能保证保留指定歌手的所有重叠演唱。关闭分离适用于已经提取的人声；只保留伴奏时会关闭人声清理。</div>')
            with gr.Row():
                back2 = gr.Button("← 返回导入")
                next2 = gr.Button("下一步：先听一小段 →", variant="primary")
        with gr.Group(visible=False, elem_id="separation-page-3") as group:
            groups.append(group)
            gr.Markdown("## ③ 先听一小段\n选择有代表性的副歌、伴奏较密或混响明显的片段，对比同一时间段的声音。")
            preview_file = gr.Dropdown(label="选择试段素材", choices=[], interactive=True)
            with gr.Row():
                preview_start = gr.Number(label="试段起点（秒）", value=0, precision=1)
                preview_duration = gr.Number(label="试段时长（秒，1–300）", value=30, precision=1)
            preview_button = gr.Button("试处理并试听", variant="primary")
            with gr.Row():
                preview_original = gr.Audio(label="同一段原声", type="filepath", interactive=False)
                preview_vocals = gr.Audio(label="分离人声", type="filepath", interactive=False)
                preview_final = gr.Audio(label="最终干声", type="filepath", interactive=False)
            preview_extra = gr.Dropdown(label="试听其他试段结果", choices=[], interactive=True)
            preview_extra_player = gr.Audio(label="其他试段结果", type="filepath", interactive=False)
            with gr.Row():
                back3 = gr.Button("← 返回修改功能")
                full_button = gr.Button("满意，处理全部整首 →", variant="primary")
                direct_button = gr.Button("跳过试听，直接处理整首")
        with gr.Group(visible=False, elem_id="separation-page-4") as group:
            groups.append(group)
            gr.Markdown("## ④ 完整处理\n伴奏在第一步保留，后续清理只处理人声。停止仅结束本任务，完成的步骤可以复用。")
            processing = gr.Markdown("等待开始。")
            with gr.Row():
                stop_button = gr.Button("停止本任务")
                resume_button = gr.Button("继续 / 重试", variant="primary")
                to_results = gr.Button("去试听与导出 →")
            with gr.Accordion("查看运行记录", open=False):
                log = gr.Textbox(label="处理记录", lines=10, interactive=False)
        with gr.Group(visible=False, elem_id="separation-page-5") as group:
            groups.append(group)
            gr.Markdown("## ⑤ 试听满意后再导出\n这里只导出整首结果。不同模型适合的歌曲可能不同，请用试听确认残留与音色。")
            result_file = gr.Dropdown(label="选择完整结果的素材", choices=[], interactive=True)
            result_kind = gr.Dropdown(label="选择完整结果试听", choices=[], interactive=True)
            result_player = gr.Audio(label="完整结果试听", type="filepath", interactive=False)
            export_files = gr.CheckboxGroup(label="需要导出的素材", choices=[], value=[])
            export_kinds = gr.CheckboxGroup(label="需要导出的结果", choices=list(RESULT_CHOICES), value=["最终干声"])
            with gr.Row().style(equal_height=False):
                with gr.Column(scale=5, min_width=300):
                    folder = gr.Textbox(label="导出到指定文件夹", value=str(ROOT / "exports" / "separation"), interactive=True)
                with gr.Column(scale=1, min_width=140):
                    browse = gr.Button("浏览文件夹")
            with gr.Row():
                fmt = gr.Radio(label="导出格式 · 44.1kHz / 24 位", choices=["WAV", "FLAC"], value="WAV")
                mono = gr.Checkbox(label="导出单声道（默认双声道）", value=False)
            export_button = gr.Button("导出所选完整结果", variant="primary")
            exported_text = gr.Markdown("试听后选择文件夹，再点击导出。重名文件自动编号，已有文件不会覆盖。")
            exported_files = gr.File(label="本次导出的文件", file_count="multiple", interactive=False)
            gr.HTML('<div class="wizard-note"><a href="/separation/open-training" target="_blank">打开训练向导 ↗</a> · 把导出的干声拖入训练页，即可接着训练。这里不会自动建立训练任务。</div>')
            back5 = gr.Button("← 返回短段试听 / 比较其他方案")
        with gr.Accordion("模型管理 · 下载进度与兼容验证", open=False):
            models_view = gr.Markdown(model_report(manager))
            with gr.Row():
                download_button = gr.Button("继续下载 / 验证模型")
                download_stop = gr.Button("停止模型准备")
            gr.Markdown("新增五个权重约 2.28GB，固定作者版本。完整校验与真实短段推理通过后才可选用。Deux 为 CC BY-NC 4.0，Sucial Fused 为 CC BY-NC-SA 4.0；其他模型以作者说明为准。")
        heartbeat = gr.Button("更新状态", elem_id="separation-heartbeat")
        settings_inputs = [separate, sep_model, keep, harmony, kar_model, dereverb, denoise]
        nav_outputs = [page_state, stepper, *groups]
        def nav(page):
            return [page, steps(page), *[gr.update(visible=i == page) for i in range(1, 6)]]
        def require_nav(job_id, page):
            if not manager.snapshot(job_id):
                raise ValueError("请先导入素材。")
            return nav(page)
        next1.click(safe(lambda j: require_nav(j, 2)), [job_state], nav_outputs)
        next2.click(safe(lambda j: require_nav(j, 3)), [job_state], nav_outputs)
        back2.click(lambda: nav(1), [], nav_outputs, queue=False)
        back3.click(lambda: nav(2), [], nav_outputs, queue=False)
        back5.click(lambda: nav(3), [], nav_outputs, queue=False)
        def go_results(job_id):
            job = manager.snapshot(job_id)
            latest = next((v for v in (job or {}).get("versions", []) if v["id"] == job.get("latest")), None)
            return require_nav(job_id, 3 if latest and latest["mode"] == "preview" else 5)
        to_results.click(safe(go_results), [job_state], nav_outputs, queue=False)
        def restore(job_id):
            job = manager.snapshot(job_id)
            labels = file_choices(job)
            s = job["settings"] if job else DEFAULTS
            page = 4 if job and job["status"] in BUSY else 5 if manager.results(job_id, "full") else 3 if manager.results(job_id, "preview") else 1
            return [job_id, *nav(page), banner(job), file_report(job),
                    *[gr.update(choices=labels, value=labels[0] if labels else None) for _ in range(3)],
                    gr.update(choices=labels, value=labels),
                    s["separate"], MODELS[s["separator"]]["label"], [label for label, key in KEEP_CHOICES.items() if key in s["keep"]],
                    s["harmony"], MODELS[s["karaoke"]]["label"], next(label for label, key in REV_CHOICES.items() if key == s["dereverb"]), s["denoise"], None]
        restore_outputs = [job_state, *nav_outputs, status, report, source_file, preview_file, result_file, export_files, *settings_inputs, display_state]
        def do_import(items):
            job_id = manager.create(items)
            return [*restore(job_id), gr.update(choices=job_choices(), value=job_label(manager.snapshot(job_id))), "素材已导入，可以继续选择功能。"]
        import_button.click(safe(do_import), [uploads], [*restore_outputs, projects, notice])
        def load_job(label):
            job = next((j for j in manager.list_jobs() if job_label(j) == label), None)
            if not job:
                raise ValueError("请选择一个已有任务。")
            return restore(job["id"])
        restore_button.click(safe(load_job), [projects], restore_outputs, queue=False)
        refresh.click(lambda: gr.update(choices=job_choices()), [], [projects], queue=False)
        new_button.click(lambda: restore(None), [], restore_outputs, queue=False)
        def select_source(job_id, label):
            entry = find_file(job_id, label)
            if not entry:
                return [gr.update(choices=[], value=None), None]
            tracks = [f"{i + 1}. {track['codec']} · {track['channels']} 声道 · {track['language']} {track['title']}" for i, track in enumerate(entry["tracks"])]
            return [gr.update(choices=tracks, value=tracks[entry["track"]]), manager.source_preview(job_id, entry["id"])]
        source_file.change(safe(select_source), [job_state, source_file], [audio_track, source_player])
        def select_track(job_id, label, track):
            entry = find_file(job_id, label)
            if not entry or not track:
                return gr.update(), gr.update()
            manager.track(job_id, entry["id"], int(track.split(".", 1)[0]) - 1)
            return manager.source_preview(job_id, entry["id"]), file_report(manager.snapshot(job_id))
        audio_track.change(safe(select_track), [job_state, source_file, audio_track], [source_player, report])
        def changed(job_id, *values):
            s = settings(*values)
            previous = manager.snapshot(job_id)
            modified = bool(previous and previous["settings"] != s)
            if job_id:
                manager.configure(job_id, s)
            clean = "vocals" in s["keep"]
            return [gr.update(interactive=s["separate"]), gr.update(value=[label for label, key in KEEP_CHOICES.items() if key in s["keep"]], interactive=s["separate"]),
                    gr.update(value=s["harmony"], interactive=clean), gr.update(interactive=clean and s["harmony"]),
                    gr.update(value=next(label for label, key in REV_CHOICES.items() if key == s["dereverb"]), interactive=clean),
                    gr.update(value=s["denoise"], interactive=clean), "功能已更新，请重新试听或处理整首。" if modified else "关闭分离时会直接清理导入的人声。" if not s["separate"] else ""]
        for component in settings_inputs:
            component.change(safe(changed), [job_state, *settings_inputs], [sep_model, keep, harmony, kar_model, dereverb, denoise, notice], queue=False)
        def start_preview(job_id, label, start, duration, *values):
            manager.configure(job_id, settings(*values))
            entry = find_file(job_id, label)
            if not entry:
                raise ValueError("请先选择试段素材。")
            manager.start(job_id, "preview", entry["id"], float(start), float(duration))
            return "试段任务已提交，完成后下面的播放器会自动更新。"
        preview_button.click(safe(start_preview), [job_state, preview_file, preview_start, preview_duration, *settings_inputs], [notice], queue=False)
        def start_full(job_id, *values):
            manager.configure(job_id, settings(*values))
            manager.start(job_id, "full")
            return nav(4)
        for button in [full_button, direct_button]:
            button.click(safe(start_full), [job_state, *settings_inputs], nav_outputs, queue=False)
        stop_button.click(manager.stop, [], [], queue=False)
        resume_button.click(safe(manager.resume), [job_state], [], queue=False)
        browse.click(safe(browse_folder), [folder], [folder], queue=False)
        def audition(job_id, label, kind, mode):
            options, _ = result_options(job_id, mode, label)
            return options.get(kind)
        def select_result(job_id, label):
            options, _ = result_options(job_id, "full", label)
            kind = "最终干声" if "最终干声" in options else "伴奏" if "伴奏" in options else next(iter(options), None)
            return gr.update(choices=list(options), value=kind), options.get(kind)
        result_file.change(select_result, [job_state, result_file], [result_kind, result_player], queue=False)
        result_kind.change(lambda j, f, k: audition(j, f, k, "full"), [job_state, result_file, result_kind], [result_player], queue=False)
        preview_extra.change(lambda j, f, k: audition(j, f, k, "preview"), [job_state, preview_file, preview_extra], [preview_extra_player], queue=False)
        def do_export(job_id, files, kinds, destination, output_format, single, *values):
            manager.configure(job_id, settings(*values))
            identifiers = [entry["id"] for label in files if (entry := find_file(job_id, label))]
            if not identifiers:
                raise ValueError("请勾选至少一个需要导出的素材。")
            result = manager.export(job_id, [RESULT_CHOICES[k] for k in kinds], destination, output_format, single, identifiers)
            text = "已导出 **" + str(len(result)) + "** 个文件：\n\n" + "\n".join(f"- {item['path']}" + (f"（为防止削波，音量降低 {20 * __import__('math').log10(item['gain']):.1f}dB）" if item["gain"] < 1 else "") for item in result)
            return text, [item["path"] for item in result]
        export_button.click(safe(do_export), [job_state, export_files, export_kinds, folder, fmt, mono, *settings_inputs], [exported_text, exported_files])
        download_button.click(manager.download, [], [], queue=False)
        download_stop.click(manager.model_stop.set, [], [], queue=False)
        poll_outputs = [status, processing, log, models_view, display_state, preview_original, preview_vocals, preview_final, preview_extra,
                        result_kind, result_player, export_kinds, export_button, preview_button, full_button, direct_button, stop_button, resume_button,
                        *settings_inputs, audio_track]
        def poll(job_id, preview_label, full_label, display_token):
            job = manager.snapshot(job_id)
            busy = job and job["status"] in BUSY
            # Gradio 3.14 Button.update supports visibility, not interactive.
            controls = [gr.update(visible=bool(job) and not busy) for _ in range(3)]
            stop_update = gr.update(visible=bool(busy))
            resume_update = gr.update(visible=bool(job) and job["status"] in {"stopped", "failed", "interrupted"})
            s = job["settings"] if job else DEFAULTS
            clean = "vocals" in s["keep"]
            field_updates = [gr.update(interactive=not busy), gr.update(interactive=not busy and s["separate"]),
                             gr.update(interactive=not busy and s["separate"]), gr.update(interactive=not busy and clean),
                             gr.update(interactive=not busy and clean and s["harmony"]), gr.update(interactive=not busy and clean),
                             gr.update(interactive=not busy and clean), gr.update(interactive=not busy)]
            full = manager.results(job_id, "full")
            token = (job_id, job.get("current_preview"), job.get("current_full"), preview_label, full_label) if job else None
            head = [banner(job), ("**" + job["message"] + "**\n\n" + (job.get("actual_settings") or {}).get("message", "")) if job else "等待开始。", manager.log_tail(job_id), model_report(manager)]
            export_update = gr.update(visible=bool(full) and not busy)
            if token == display_token:
                return [*head, display_token, *[gr.update() for _ in range(7)], export_update, *controls, stop_update, resume_update, *field_updates]
            preview_options, preview = result_options(job_id, "preview", preview_label)
            full_options, complete = result_options(job_id, "full", full_label)
            output = preview["outputs"] if preview else {}
            kind = "最终干声" if "最终干声" in full_options else "伴奏" if "伴奏" in full_options else next(iter(full_options), None)
            extras = list(preview_options)
            export_available = sorted({key for r in full for key in r["outputs"]}, key=lambda k: list(RESULT_LABELS).index(k))
            defaults = [RESULT_LABELS[k] for k in ("final", "instrumental") if k in export_available and (k == "final" or job and "instrumental" in job["settings"]["keep"])]
            export_choices_update = gr.update(choices=[RESULT_LABELS[k] for k in export_available] or list(RESULT_CHOICES), value=defaults or [])
            if display_token and token and display_token[0] == token[0] and display_token[2] == token[2]:
                export_choices_update = gr.update()
            return [*head, token, output.get("original"), output.get("vocals"), output.get("final"), gr.update(choices=extras, value=extras[0] if extras else None),
                    gr.update(choices=list(full_options), value=kind), full_options.get(kind),
                    export_choices_update,
                    export_update, *controls, stop_update, resume_update, *field_updates]
        heartbeat.click(poll, [job_state, preview_file, result_file, display_state], poll_outputs, queue=False, show_progress=False)
        app.load(None, [], [], _js="""() => {
            const root=document.querySelector('gradio-app')?.shadowRoot || document;
            root.querySelectorAll('.dark').forEach(n=>n.classList.remove('dark'));
            clearInterval(window.rvcSeparationHeartbeat);
            window.rvcSeparationHeartbeat=setInterval(()=>{
              root.querySelector('#separation-heartbeat')?.click();
              const nodes=document.createTreeWalker(root.querySelector('#separation-import') || root,NodeFilter.SHOW_TEXT);
              while(nodes.nextNode()){const n=nodes.currentNode;n.textContent=n.textContent.replace('Drop File Here','把音频或视频拖到这里').replace('Click to Upload','点击选择文件').replace(' - or - ',' · 或 · ');}
            },2000);return [];
        }""")
        def initial():
            jobs = manager.list_jobs()
            job_id = manager.active or jobs[0]["id"] if jobs else None
            return [*restore(job_id), gr.update(choices=job_choices(), value=job_label(manager.snapshot(job_id)) if job_id else None)]
        app.load(initial, [], [*restore_outputs, projects])
    return app
