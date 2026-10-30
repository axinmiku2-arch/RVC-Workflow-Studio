"""Small optional controls in the original Gradio single-conversion page."""
import atexit
from pathlib import Path
import gradio as gr
from gradio.context import Context
from tools.gpu_task_lock import GPUTaskLock
from rvc_separation.models import ROOT, MODELS, sha256
from rvc_separation.engine import signature as digest
from rvc_separation.ui import browse_folder
from .audio import PRESETS, follow_pitch
from .settings import DEFAULTS, normalize, LABELS, check_models
from .backend import Manager, BUSY

SEP = {MODELS[key]["label"]: key for key in ("leap", "deux", "viper")}
KAR = {MODELS[key]["label"]: key for key in ("karaoke", "old_karaoke")}
REV = {"关闭": "off", "温和 · 保留音色与尾音": "gentle", "加强 · 去混响与回声": "fused"}
KEYS = list(DEFAULTS)
PARAMS = ("speaker", "transpose", "f0", "index", "index_rate", "resample_sr", "rms_mix", "protect")


def job_signature(job):
    return digest(dict(source=job["entry"]["sha256"], model=job["conversion"]["model"],
                       params={key:job["conversion"][key] for key in PARAMS}, settings=job["settings"]))


def restored_voice_result(result, job, sid):
    result = list(result)
    if job and Path(job["conversion"]["model"]).name == sid:
        # Loading a voice normally selects its automatic index. During recovery,
        # preserve the saved single-inference index, including an intentional blank.
        result[0] = dict(result[0], value=job["conversion"]["speaker"])
        result[1] = dict(result[1], value=job["conversion"]["protect"])
        result[3] = {"value":job["conversion"]["index"], "__type__":"update"}
    return [*result, None]


def build_controls():
    controls = {}
    with gr.Row():
        with gr.Column(scale=1, min_width=160):
            controls["separate"] = gr.Checkbox(label="分离音频", value=False, elem_id="convert-separate")
            controls["effects"] = gr.Checkbox(label="添加人声效果", value=False)
            controls["song"] = gr.Checkbox(label="合成完整歌曲", value=False, interactive=False)
        with gr.Column(scale=3, min_width=240):
            with gr.Accordion("高级设置", open=False):
                gr.Markdown("分离后只转换人声；转换干声始终保留。")
                controls["separator"] = gr.Dropdown(label="人声分离模型", choices=list(SEP), value=next(iter(SEP)), interactive=False)
                with gr.Row():
                    controls["harmony"] = gr.Checkbox(label="去和声／提取主唱", value=False, interactive=False)
                    controls["denoise"] = gr.Checkbox(label="降噪", value=False, interactive=False)
                controls["karaoke"] = gr.Dropdown(label="去和声模型", choices=list(KAR), value=next(iter(KAR)), interactive=False)
                controls["dereverb"] = gr.Dropdown(label="去混响／回声", choices=list(REV), value=list(REV)[1], interactive=False)
                gr.Markdown("加强去混响可能减少叠唱；去和声不能保证保留所有重叠演唱。")
                controls["preset"] = gr.Dropdown(label="人声效果", choices=list(PRESETS), value="空灵氛围", interactive=False)
                controls["strength"] = gr.Slider(0, 100, value=35, step=1, label="效果强度（0 完全旁路）", interactive=False)
                with gr.Row():
                    controls["vocal_db"] = gr.Slider(-24, 12, value=0, step=.5, label="合成人声音量（dB）", interactive=False)
                    controls["backing_db"] = gr.Slider(-24, 12, value=0, step=.5, label="伴奏音量（dB）", interactive=False)
                controls["backing_pitch"] = gr.Slider(-24, 24, value=0, step=1, label="伴奏独立变调（半音）", interactive=False)
                controls["follow"] = gr.Button("跟随人声调性")
                gr.Markdown("默认保留伴奏原调；跟随时 −14 对应 −2，±12 对应 0。")
                controls["start"] = gr.Number(value=0, label="30秒试听起点（秒）")
                controls["preview"] = gr.Button("试处理30秒")
                controls["post"] = gr.Button("更新效果／合成")
    controls["note"] = gr.Markdown("勾选后，点击转换会自动完成分离预处理。效果与合成可在试听后单独更新。")
    def enable(separate, effects, song, harmony):
        return [gr.update(interactive=separate), gr.update(interactive=separate), gr.update(interactive=separate and harmony),
                gr.update(interactive=separate), gr.update(interactive=separate),
                gr.update(interactive=separate, value=bool(separate and song)),
                gr.update(interactive=effects), gr.update(interactive=effects),
                gr.update(interactive=bool(separate and song)), gr.update(interactive=bool(separate and song)),
                gr.update(interactive=bool(separate and song))]
    enabled = [controls[key] for key in ("separator", "harmony", "karaoke", "dereverb", "denoise", "song", "preset", "strength", "vocal_db", "backing_db", "backing_pitch")]
    for key in ("separate", "effects", "song", "harmony"):
        controls[key].change(enable, [controls[k] for k in ("separate", "effects", "song", "harmony")], enabled, queue=False)
    return controls


def parse(values):
    value = dict(zip(KEYS, values))
    value.update(separator=SEP[value["separator"]], karaoke=KAR[value["karaoke"]], dereverb=REV[value["dereverb"]], preset=PRESETS[value["preset"]])
    return normalize(value)


def bind_pipeline(controls, vc, model, source, parameters, convert_button, info, player):
    manager = Manager()
    job_id = gr.State(None)
    dirty = gr.State(None)  # Current UI signature, independent of callback completion order.
    source_digest = gr.State(None)
    restoring_voice = gr.State(None)
    displayed = gr.State(None)
    all_settings = [controls[key] for key in KEYS]
    request_inputs = [source, model, *parameters, *all_settings]
    with gr.Row():
        result_choice = gr.Dropdown(label="试听结果", choices=[], interactive=True, visible=False)
        stop = gr.Button("停止本任务", visible=False)
        retry = gr.Button("重试／继续", visible=False)
        restore_button = gr.Button("恢复最近任务")
    downloads = gr.File(label="本次结果下载（试听片段会标注）", file_count="multiple", interactive=False, visible=False)
    with gr.Accordion("试听满意后导出到文件夹", open=False):
        export_kinds = gr.CheckboxGroup(label="导出结果", choices=["转换干声", "效果人声", "合成歌曲", "原伴奏"], value=["转换干声"])
        with gr.Row():
            folder = gr.Textbox(label="目标文件夹", value=str(ROOT / "exports" / "conversion"), interactive=True)
            browse = gr.Button("浏览文件夹")
            fmt = gr.Radio(["WAV", "FLAC"], value="WAV", label="格式（24位）")
        export_button = gr.Button("导出整首结果", visible=False)
        export_note = gr.Textbox(label="导出信息", interactive=False)

    def unpack(values):
        src, name, speaker, transpose, f0, index, index_rate, rate, rms, protect = values[:10]
        root = Path(__import__('os').environ.get("weight_root", "assets/weights"))
        voice = str((root / str(name)).resolve()) if name else None
        params = dict(speaker=int(speaker or 0), transpose=int(transpose), f0=f0, index=index or "", index_rate=float(index_rate),
                      resample_sr=int(rate), rms_mix=float(rms), protect=float(protect))
        return src, voice, params, parse(values[10:])

    def begin(mode, start, values):
        src, voice, params, settings = unpack(values)
        if mode == "full" and not any(settings[key] for key in ("separate", "effects", "song")):
            if any(job["status"] in BUSY for job in manager.jobs.values()):
                raise gr.Error("当前任务尚未结束，请先等待或停止。")
            check_models(settings, voice)
            with GPUTaskLock("原 WebUI · 单次推理"):
                # Restore can set the model selector without firing its change event.
                # Also prevents another browser's model selection changing this request.
                vc.get_vc(Path(voice).name)
                status, result = vc.vc_single(params["speaker"], src, params["transpose"], params["f0"],
                    params["index"], params["index_rate"], params["resample_sr"], params["rms_mix"], params["protect"])
            if result and (result[0] is None or result[1] is None):
                result = None
            return None, False, None, status, result, gr.update(choices=[], value=None), None, None
        identifier = manager.start(src, voice, params, settings, mode, start)
        job = manager.snapshot(identifier)
        return identifier, job_signature(job), None, "任务已提交，后台会依次执行分离、转换及所选后处理。", None, gr.update(choices=[], value=None), None, job["entry"]["sha256"]

    def full(*values):
        try:
            return begin("full", 0, values)
        except Exception as error:
            raise gr.Error(str(error))

    def preview(start, *values):
        try:
            return begin("preview", float(start), values)
        except Exception as error:
            raise gr.Error(str(error))

    begin_outputs = [job_id, dirty, displayed, info, player, result_choice, downloads, source_digest]
    convert_button.click(full, request_inputs, begin_outputs, api_name="infer_convert_pipeline")
    controls["preview"].click(preview, [controls["start"], *request_inputs], begin_outputs, api_name="infer_convert_preview")
    controls["follow"].click(follow_pitch, parameters[1], controls["backing_pitch"], queue=False)

    def matching(job, values):
        if not job:
            return True
        try:
            src, voice, params, settings = unpack(values)
            expected = job["conversion"]
            return (settings == job["settings"] and voice == expected["model"] and
                    all(params[k] == expected[k] for k in params) and Path(src or "").is_file() and sha256(src) == job["entry"]["sha256"])
        except Exception:
            return False

    def changed(identifier, source_hash, *values):
        try:
            src, voice, params, settings = unpack([None, *values])
            current = digest(dict(source=source_hash, model=voice, params=params, settings=settings))
        except Exception:
            current = "invalid"
        return current, "分离或转换参数变化后点击转换；只修改效果与合成参数，可点击更新效果／合成。"
    source.change(lambda path: sha256(path) if path and Path(path).is_file() else None, source, source_digest, queue=False, show_progress=False)
    for component in request_inputs[1:]:
        component.change(changed, [job_id, source_digest, *request_inputs[1:]], [dirty, controls["note"]], queue=False, show_progress=False)

    refresh_outputs = [info, result_choice, player, downloads, displayed, stop, retry, export_button, convert_button, controls["preview"], controls["post"], dirty]
    def refresh(identifier, stale, shown, source_hash, *values):
        job = manager.snapshot(identifier) if identifier else None
        if not job:
            return [gr.update(), gr.update(visible=False), gr.update(), gr.update(visible=False), gr.update(), gr.update(visible=False), gr.update(visible=False),
                    gr.update(visible=False), gr.update(visible=True), gr.update(visible=True), gr.update(visible=False), gr.update()]
        try:
            _, voice, params, settings = unpack([None, *values])
            current = digest(dict(source=source_hash, model=voice, params=params, settings=settings))
        except Exception:
            current = "invalid"
        stale = current != job_signature(job)
        busy = job["status"] in BUSY
        message = f"【{'30秒试听' if job['mode'] == 'preview' else '整首处理'}】{job['progress']:.0f}%\n音色：{Path(job['conversion']['model']).name}\n{job['message']}"
        if stale:
            message += "\n设置已变化，正式导出已暂停；请转换或更新后处理。"
        signature = (job["id"], job["version"], job["status"], stale)
        choice_update, player_update, download_update = gr.update(), gr.update(), gr.update()
        if signature != shown:
            if job["status"] == "completed" and not stale:
                outputs = job["result"]["outputs"]
                choices = [LABELS[key] for key in LABELS if key in outputs]
                selected = "合成歌曲" if "song" in outputs else "效果人声" if "effect" in outputs else "转换干声"
                choice_update = gr.update(choices=choices, value=selected, visible=True)
                player_update = playback(job, next(key for key in LABELS if LABELS[key] == selected))
                # Integer player/download files are made without changing float processing artifacts.
                download_update = gr.update(value=delivery_files(job), visible=True)
            else:
                choice_update, player_update, download_update = gr.update(choices=[], value=None, visible=False), None, gr.update(value=None, visible=False)
        return [message, choice_update, player_update, download_update, signature, gr.update(visible=busy),
                gr.update(visible=job["status"] in {"failed", "stopped", "interrupted"}),
                gr.update(visible=job["status"] == "completed" and job["mode"] == "full" and not stale),
                gr.update(visible=not busy), gr.update(visible=not busy), gr.update(visible=job["status"] == "completed"), current]

    def delivery_files(job):
        directory = manager.directory / job["id"] / f"downloads_{job['version']}"
        existing = sorted(directory.glob("*.wav")) if directory.exists() else []
        if existing:
            return [str(path) for path in existing]
        from .audio import export
        name = job["name"] + ("_试听30秒" if job["mode"] == "preview" else "")
        return [export(path, directory, name, LABELS[key])["path"] for key, path in job["result"]["outputs"].items() if key in {"converted", "effect", "song"}]

    def playback(job, key):
        # Browser players receive peak-safe PCM24; float processing remains intact.
        directory = manager.directory / job["id"] / f"players_{job['version']}"
        existing = list(directory.glob(f"{key}_*.wav")) if directory.exists() else []
        if existing:
            return str(existing[0])
        from .audio import export
        return export(job["result"]["outputs"][key], directory, key, LABELS[key])["path"]

    # A continuous Gradio load generator captures the initial State arguments.
    # Poll with fresh State values instead, just as the standalone wizard does.
    root = Context.root_block
    heartbeat = gr.Button("任务进度", elem_id="conversion-heartbeat")
    root.css = (root.css or "") + "\n#conversion-heartbeat{display:none!important}"
    heartbeat.click(refresh, [job_id, dirty, displayed, source_digest, *request_inputs[1:]], refresh_outputs, queue=False, show_progress=False)
    root.load(None, [], [], _js="""() => {
        const root=document.querySelector('gradio-app')?.shadowRoot || document;
        clearInterval(window.rvcConversionHeartbeat);
        window.rvcConversionHeartbeat=setInterval(()=>root.querySelector('#conversion-heartbeat')?.click(),1200);
        return [];
    }""")

    def pick(identifier, label, stale):
        job = manager.snapshot(identifier)
        if not job:
            return gr.update()
        if job["status"] != "completed" or (stale and stale != job_signature(job)):
            return None
        key = next((key for key in job["result"]["outputs"] if LABELS[key] == label), None)
        return playback(job, key) if key else None
    result_choice.change(pick, [job_id, result_choice, dirty], player, queue=False)
    stop.click(manager.stop, job_id, [], queue=False)
    def retry_task(identifier):
        try:
            return manager.retry(identifier), gr.update(), None
        except Exception as error:
            raise gr.Error(str(error))
    retry.click(retry_task, job_id, [job_id, dirty, displayed])

    def post(identifier, *values):
        job = manager.snapshot(identifier)
        src, voice, params, settings = unpack(values)
        if not job or voice != job["conversion"]["model"] or not Path(src or "").is_file() or sha256(src) != job["entry"]["sha256"] or any(params[k] != job["conversion"][k] for k in params):
            raise gr.Error("素材或转换参数已变化，请先点击转换。")
        try:
            result = manager.update_post(identifier, settings)
            return result, job_signature(manager.snapshot(result)), None
        except Exception as error:
            raise gr.Error(str(error))
    controls["post"].click(post, [job_id, *request_inputs], [job_id, dirty, displayed], api_name="infer_convert_postprocess")

    def restore():
        job = manager.snapshot()
        if not job:
            return [gr.update() for _ in range(5 + len(request_inputs))]
        params, settings = job["conversion"], dict(job["settings"])
        for key, mapping in (("separator", SEP), ("karaoke", KAR), ("dereverb", REV), ("preset", PRESETS)):
            settings[key] = next(label for label, value in mapping.items() if value == settings[key])
        active = {key: True for key in KEYS}
        for key in ("separator", "harmony", "dereverb", "denoise", "song"):
            active[key] = settings["separate"]
        active["karaoke"] = settings["separate"] and settings["harmony"]
        for key in ("preset", "strength"):
            active[key] = settings["effects"]
        for key in ("backing_pitch", "vocal_db", "backing_db"):
            active[key] = settings["song"] and settings["separate"]
        return [job["id"], job_signature(job), None, job["entry"]["path"], Path(params["model"]).name,
                *[params[key] for key in ("speaker", "transpose", "f0", "index", "index_rate", "resample_sr", "rms_mix", "protect")],
                *[gr.update(value=settings[key], interactive=active[key]) for key in KEYS], job["entry"]["sha256"], job["id"]]
    restore_outputs = [job_id, dirty, displayed, *request_inputs, source_digest, restoring_voice]
    restore_button.click(restore, [], restore_outputs)
    root.load(restore, [], restore_outputs, queue=False)
    browse.click(browse_folder, folder, folder, queue=False)
    def save(identifier, kinds, target, format_, *values):
        job = manager.snapshot(identifier)
        if not matching(job, values):
            raise gr.Error("当前设置与结果不一致，请先转换或更新效果／合成。")
        try:
            selected = [key for key, label in LABELS.items() if label in kinds]
            receipts = manager.export(identifier, selected, target, format_)
            return "\n".join(receipt["path"] for receipt in receipts)
        except Exception as error:
            raise gr.Error(str(error))
    export_button.click(save, [job_id, export_kinds, folder, fmt, *request_inputs], export_note, api_name="infer_convert_export")
    # Avoid leaving task-owned children alive if this UI process terminates.
    atexit.register(lambda: [manager.stop(identifier) for identifier in list(manager.processes)])
    def voice_changed(sid, protect0, protect1, restore_id):
        with GPUTaskLock("原 WebUI · 载入音色"):
            result = vc.get_vc(sid, protect0, protect1)
        return restored_voice_result(result, manager.snapshot(restore_id) if restore_id else None, sid)
    manager.voice_changed = voice_changed
    manager.restoring_voice = restoring_voice
    return manager
