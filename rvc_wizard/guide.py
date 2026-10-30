"""Generate the offline guide from the same parameter descriptions as the UI."""
from html import escape
from .common import PARAMETERS, ROOT

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f5f7f8;color:#22333b;font:16px/1.85 'Microsoft YaHei UI','Segoe UI',sans-serif}
main{max-width:1000px;margin:auto;padding:48px 24px 80px}h1{font-size:36px;line-height:1.4;margin:12px 0}h2{margin:36px 0 12px;font-size:24px}h3{margin:22px 0 6px}
.eyebrow{color:#0f766e;letter-spacing:3px;font-weight:bold}.lead{font-size:18px;color:#526771}.card{background:white;border:1px solid #dfe7e9;border-radius:18px;padding:28px;margin:20px 0}
.note{border-left:4px solid #0f766e;background:#effaf7;padding:15px 20px}.warn{border-left-color:#d97706;background:#fff8ec}a{color:#087b73}nav{display:flex;flex-wrap:wrap;gap:10px}nav a{background:#eaf2f1;padding:6px 12px;border-radius:8px;text-decoration:none}
table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #e5ecee}th{background:#eff6f5}code{background:#edf1f3;padding:2px 6px;border-radius:4px}svg{width:100%;height:auto}.small{color:#667b85;font-size:14px}li{margin:7px 0}@media(max-width:650px){main{padding:24px 15px}h1{font-size:28px}.card{padding:18px}td,th{padding:8px;font-size:14px}}
"""


def parameter_markdown():
    return "| 设置 | 推荐值 | 为什么这样选 |\n|---|---|---|\n" + "\n".join(
        f"| {name} | {value} | {note} |" for name, value, note in PARAMETERS)


def guide_html():
    rows = "".join(f"<tr><td>{escape(n)}</td><td>{escape(v)}</td><td>{escape(d)}</td></tr>" for n, v, d in PARAMETERS)
    labels = ["导入素材", "素材体检", "选择方案", "开始训练", "试听导出"]
    drawing = '<svg viewBox="0 0 900 110" role="img" aria-label="导入、体检、方案、训练、试听五步流程">'
    for i, label in enumerate(labels):
        x = 15 + 180 * i
        if i < 4:
            drawing += f'<path d="M{x+140} 50h34l-7-6m7 6l-7 6" stroke="#83aaa5" fill="none" stroke-width="2"/>'
        drawing += f'<rect x="{x}" y="12" width="140" height="76" rx="12" fill="#eff8f5" stroke="#c1dfd8"/><text x="{x+70}" y="39" text-anchor="middle" fill="#0f766e" font-size="15">0{i+1}</text><text x="{x+70}" y="67" text-anchor="middle" fill="#22333b" font-size="17">{label}</text>'
    drawing += "</svg>"
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RVC 音色训练向导 · 使用说明</title><style>{CSS}</style><main>
<div class="eyebrow">RVC · 从干声到你的音色</div><h1>音色训练向导使用说明</h1><p class="lead">准备同一位歌手的干声，按五步完成训练。参数不懂时，直接使用推荐方案。</p>
<nav><a href="#start">开始使用</a><a href="#material">准备素材</a><a href="#settings">选择方案</a><a href="#listen">判断效果</a><a href="#recovery">停止与恢复</a><a href="#files">模型与导出</a></nav>
<div class="card">{drawing}<p class="small">这是基于现有底模训练自己的音色。RVC 接收已有的说话或唱歌音频并转换音色；唱词、旋律和演唱方式来自输入音频。</p></div>
<section id="start"><h2>1. 从双击启动到导出</h2><div class="card">
<h3>① 导入素材</h3><p>双击项目根目录的 <code>go-training-wizard.bat</code>，等待浏览器打开。填写音色名称，把 WAV、FLAC、MP3、M4A、OGG 等音频拖入导入框。可以先选一首试听，或从列表移除某个文件。点击“下一步：检查素材”后，向导会复制素材并建立独立项目。</p>
<h3>② 素材体检</h3><p>查看每个文件的时长、声道、采样率、静音比例和疑似削波提示。无法解码、全静音的文件需要移除或换成有效录音。静音按 20 毫秒窗口的均方根音量低于 −55 dBFS 估算，有声时长不是精确的人声识别。静音过多、时长不足、疑似削波会给出提示，允许你判断后继续。</p><p>体检不能可靠识别伴奏、混响或不同歌手。请试听素材，确认整个项目属于同一个目标音色。</p>
<h3>③ 选择方案</h3><p>素材已确认优质时，直接使用默认的“正式训练（推荐）”：200 轮。想先检查流程和初步试听时，选择“快速试跑（20 轮）”，之后可继续到 200 轮。高级设置包含采样率、轮数、每批数量、并行数和保存间隔；点击下一步会显示实际训练摘要。</p>
<h3>④ 开始训练</h3><p>点击“确认并开始训练”。整理切片、音高提取、声音特征提取、音色训练、索引生成会依次自动完成。训练轮次稳定后显示该训练阶段的剩余时间估计，提取和索引阶段以实际文件进度为准。</p><p>关闭网页不会停止后台训练。重新打开或刷新页面，会找回当前任务。关闭程序会中断任务，之后从完整检查点恢复。</p>
<h3>⑤ 试听与导出</h3><p>模型和索引检查通过后，点击“进入试听与导出”。拖入一段<strong>未参与训练的测试干声</strong>，点击转换试听。比较原声和转换结果，尝试低音、中音、高音。导出包包含选定的音色模型、对应索引和使用说明。</p>
</div></section>
<section id="material"><h2>2. 不同素材应该怎样准备</h2><div class="card"><table><tr><th>你的情况</th><th>建议</th></tr>
<tr><td>唱歌 / 翻唱</td><td>同一位歌手、清楚的干声，覆盖常用音域、轻声与强声。保留自然咬字和呼吸，去掉大段伴奏、对白和其他人合唱。</td></tr>
<tr><td>素材少于 5 分钟</td><td>可以先试跑，但更容易覆盖不足。先增加清晰、不同音域的素材，再考虑增加训练轮数。</td></tr>
<tr><td>10～50 分钟优质干声</td><td>常规起始范围。重复片段不能代替新的音域和发声覆盖；优先质量与一致的音色。</td></tr>
<tr><td>混响或伴奏残留明显</td><td>先重新处理素材。可使用原 WebUI 的人声分离、去混响工具；反复处理也可能伤害音色，要对照原声试听。</td></tr>
<tr><td>底噪、失真、削波明显</td><td>重新录音或移除问题片段。增加训练轮数无法修复录音中已经丢失的信息。</td></tr>
<tr><td>说话 / 配音</td><td>收集同一人自然说话的素材，覆盖不同音节和语气。这个版本仍使用带音高的通用模型，试听输入换成独立说话干声。</td></tr></table>
<p>同时用于唱歌和朗读时，可以混合这两类清晰干声，仍需保持同一个人的音色。多种语言可以放在同一项目，不需要填写语言或歌词；效果取决于素材覆盖的音节、音域和发声方式，请分别用唱歌、朗读的独立干声检查。</p>
<p class="note">无需文字标注，无需手工把长音频切成小段。源文件会保留；训练副本自动转声道、重采样、切片和归一化。</p></div></section>
<section id="settings"><h2>3. 推荐方案与高级选项</h2><div class="card"><table><tr><th>设置</th><th>推荐值</th><th>解释</th></tr>{rows}</table>
<h3>什么时候选择 48k？</h3><p>源素材本身优质、细节充分时可以对比 48k。把低采样率或压缩失真的素材升到 48k，不会增加原本不存在的细节。开始处理后，采样率和素材固定；想更换时请新建项目。</p>
<h3>200 轮一定最好吗？</h3><p>不是。它是优质素材的起点。向导每 50 轮保留一个试听音色，停止时也保存当前完成轮次的音色；最终用未参与训练的干声对比。训练损失下降不等同于更像或更好听。</p>
<h3>显存不足怎么办？</h3><p>推荐每批数量为 6；发现显存不足后自动尝试 3、1，每档最多一次。其他自定义数量同样逐步减半到 1。仍然失败时会停止并保留可恢复进度。可以关闭其他占用显存的程序后重试。</p>
</div></section>
<section id="listen"><h2>4. 试听如何判断与调整</h2><div class="card"><table><tr><th>现象</th><th>优先排查 / 调整</th></tr>
<tr><td>音色还像输入歌手</td><td>确认使用了本项目模型和索引；在 0.75 附近比较索引混合比例。提高比例可能更像训练音色，也可能带入素材的缺陷。</td></tr>
<tr><td>齿音、辅音有破碎感</td><td>先确认测试干声干净；试着降低索引比例，或将辅音保护数值从 0.33 往 0.2 调。该参数越小，保护越强；0.5 接近关闭保护。</td></tr>
<tr><td>高音失真、低音不自然</td><td>确认训练素材覆盖该音域；尝试调整输入升降调。差 12 个半音相当于一个八度，不要把升降调当成所有问题的修复方式。</td></tr>
<tr><td>训练更久反而更差</td><td>比较 50、100、150 轮等阶段模型。可以导出较早的音色；不自动按损失最低值宣布“最佳模型”。</td></tr>
<tr><td>回声、伴奏、其他人的声音</td><td>回到素材准备阶段排查。向导的数字体检无法确认这些问题。</td></tr></table>
<p>默认试听使用 RMVPE、原调、索引比例 0.75、辅音保护 0.33，保持输入音量包络。建议用 15～30 秒的独立干声，先听咬字和音色，再比较不同音域。</p></div></section>
<section id="recovery"><h2>5. 停止、失败和继续训练</h2><div class="card"><p>正常训练时点击“保存进度并停止”，程序在当前轮次结束后保存成对检查点和试听音色。等待时间取决于当前轮次；若必须立即停止，可使用“立即停止”，恢复时会回到最近完整保存的轮次。</p><p>停电或关闭程序之后，从顶部选择已有项目并载入，点击“继续 / 重试”。已完成且有效的阶段会复用，损坏的输出会重新生成。检查点不完整时，回退到上一组完整进度并明确提示；不会悄悄把失败续训当成新训练。</p><p>索引失败时，已经训练好的音色仍保留，重试只补索引。试跑完成后，把总目标改为 200 轮，点击继续训练；是<strong>总共训练到 200 轮</strong>，而不是再加 200 轮。</p><p class="note warn">恢复任务需要素材和训练目录仍然存在。不要移动整个项目运行目录，或删除 <code>logs/wizard_...</code>。更换素材、版本或采样率时，应新建项目。</p></div></section>
<section id="files"><h2>6. 模型、索引与导出包</h2><div class="card"><table><tr><th>文件</th><th>作用</th></tr><tr><td>音色模型 .pth</td><td>转换时使用的模型，保存在 <code>assets/weights</code>，原 WebUI 刷新音色列表后也可选择。</td></tr><tr><td>声音索引 .index</td><td>帮助转换结果向训练音色靠近，保存在训练项目并链接到 <code>assets/indices</code>。</td></tr><tr><td>G / D 检查点</td><td>包含完整训练与优化器进度，供继续训练。不要当成转换音色模型使用或分享。</td></tr><tr><td>导出包 .zip</td><td>包含选定的音色模型、有效索引、参数摘要及使用说明。不包含源录音和完整训练检查点。</td></tr></table></div></section>
<p class="small">参数说明与向导共用。参考：<a href="https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/wiki/常见问题解答">RVC 官方常见问题</a>、<a href="https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/main/docs/en/training_tips_en.md">训练说明</a>。实际代码以你这个本地分支为准。</p>
</main></html>"""


def write_guide(root=ROOT):
    path = root / "docs" / "training-wizard.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(guide_html(), encoding="utf-8")
    return path
