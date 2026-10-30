# 第三方资源审查记录（未完成）

| 资源 | 当前发现 | 发布处理 |
| --- | --- | --- |
| 上游 RVC | 根目录保留 MIT 许可证和版权声明 | 保留完整声明；核对具体上游基线及其他引用代码 |
| 分离权重 | 模型登记中 Deux 标记 CC BY-NC 4.0，Sucial Fused 标记 CC BY-NC-SA 4.0；其余多项要求查看作者说明 | 每个仓库、权重、配置及许可证分别核验；不将权重放入候选包 |
| Pedalboard 0.9.25 | 当前本机安装包元数据包含 GPL-3.0 文本；安装脚本下载校验后隔离安装 | 核对适用条款及分发方案；不要假设受项目 MIT 许可覆盖 |
| Unlock Music worker | `rvc_music/assets/source.json` 记录来源、版本、校验和修改；同目录有 LICENSE 和 NOTICE | 审核来源、依赖和修改分发要求后再决定是否纳入 |
| FFmpeg / FFprobe | 本地存在 Windows 构建；缺少本次已核实的完整构建来源与许可清单 | 暂不捆绑；核实编译选项、源码和相应许可 |
| pymss / 其他依赖 | 代码和依赖分散在多个目录 | 逐一识别来源、许可证、版本、子模块和再分发条件 |

上述是工程审查记录，不是法律结论。许可不清的资源在核实前不纳入公开分发包。

## 2026-10-30：固定版本复核

- [Pedalboard 0.9.25 的 PyPI 元数据](https://pypi.org/pypi/pedalboard/0.9.25/json)列出 GPLv3 分类，已下载安装包的元数据也包含 GPL 第三版全文。代码运行时导入该效果器，项目源码的 MIT 声明不能替代对组合分发和使用条件的判断；正式分发前需明确适用条件。候选不提交该安装包。
- 在固定版本的 Hugging Face 模型卡 API 中，Deux 的 `license` 为 `cc-by-nc-4.0`；Leap Xe 和 BS Karaoke 的模型卡元数据未注明 `license`。未注明不等于允许任意使用，应进一步核对权利人声明。
- 本次查询 Sucial 固定版本时网络请求失败；不能用这次失败独立确认其许可。既有模型登记标为 CC BY-NC-SA 4.0，发布前应再次核对来源。
- 后续重新查询 [Sucial 固定版本模型元数据](https://huggingface.co/api/models/Sucial/Dereverb-Echo_Mel_Band_Roformer/revision/9c83bf27196213e6107cf0de5ff2d06d56a46876)成功，返回的 `cardData.license` 为 `cc-by-nc-sa-4.0`，文件清单包含本项目登记的 fused 权重。该权重不随源码发布；使用者仍应自行阅读完整许可和模型作者的说明。
- `tools/pymss/LICENSE` 和 `tools/pymss_core/LICENSE` 均保留 KitsuneX07 的 MIT 版权声明；目录内其他来源或嵌入组件仍需核对，不能据此断定整个依赖树均为 MIT。

## 2026-10-30：pymss 包对照

将候选内的 `tools/pymss`、`tools/pymss_core` 与安装过程中从 PyPI 下载的 `pymss 2.0.14`、`pymss-core 0.1.4` wheel 中同路径文件逐字节比较。两个 wheel 的元数据均标记 `License-Expression: MIT`，并指向 `pymss-project` 的对应源码仓库；候选保留各自 LICENSE。

候选内这两份 LICENSE 分别与 wheel 的 `dist-info/licenses/LICENSE` 字节一致；除放在包目录内的 LICENSE 外，没有发现候选额外的非缓存文件。

`pymss` wheel 中 66 个包文件：54 个与候选一致，2 个不同（`separator.py`、`utils.py`），10 个 WebUI 静态资源未纳入。`pymss-core` 的 86 个包文件：82 个一致，4 个 Roformer 文件不同（`bands.py`、`common.py`、`mel_band_roformer.py`、`transformer.py`）。差异包括 DirectML 设备、数据类型、频谱计算和缓存处理等兼容代码；不能仅凭对照认定改动作者，也不能因此推断 DirectML 已在本候选通过验收。此比较不证明软件包本身所有嵌入来源及其许可均已完整核实。

## 2026-10-30：Unlock Music 来源复核

从 `adcage/unlock-music` 固定提交 `eb61b9ee1963b0aa731e71d066b31602cec67273` 读取原 worker 和 LICENSE；候选中的原 worker 与许可证分别逐字节一致。原 worker 和修改版 worker 的 SHA-256 均与 `rvc_music/assets/source.json` 的记录一致。此检查证实文件来源及本地完整性，不等于对压缩代码或其依赖完成安全和许可审计；修改版具体差异仍需核实。尝试对压缩代码进行完整字符级比较时计算量过大，已停止本次比较进程。

随后采用针对性重建比较：把原 worker 的换行统一后，仅按记录的三处修改替换（缺失 artist 时使用空数组、空 NCM 元数据提供默认对象及偏移、缺失封面时使用空字符串），可逐字重建修改版；三处原始匹配各出现一次。这验证了修改范围，但不构成对上游压缩代码及依赖的完整安全审计。

## 2026-10-30：worker 内嵌依赖清单

通过 [同一固定提交的源码映射](https://github.com/Adcage/unlock-music/blob/eb61b9ee1963b0aa731e71d066b31602cec67273/e495d03829e7f9f45920.worker.js.map)检查到 347 个源路径及 347 份嵌入源码；映射文件 SHA-256 为 `1153779175f767fb5856f61a118f4cc88462319eb29e0d7214dbc9c0896f3a37`。按 `node_modules` 路径提取出的包名为：

`@babel/runtime`、`assert`、`base64-js`、`browser-id3-writer`、`buffer`、`content-type`、`core-js`、`core-util-is`、`crypto-js`、`debug`、`events`、`file-type`、`ieee754`、`inherits`、`is-typedarray`、`isarray`、`media-typer`、`ms`、`music-metadata`、`music-metadata-browser`、`node-libs-browser`、`object-assign`、`path-browserify`、`peek-readable`、`process-nextick-args`、`readable-stream`、`readable-web-to-node-stream`、`regenerator-runtime`、`safe-buffer`、`stream-browserify`、`string_decoder`、`strtok3`、`token-types`、`typedarray-to-buffer`、`util`、`util-deprecate`。

该清单来源于源码路径，不能证明精确依赖版本或涵盖所有非 npm 来源；嵌套的同名包也可能有不同版本。尚未确定每项具体版本、版权声明和再分发条件，不能把根目录 MIT 声明视为替代这些核查。固定版本仓库根目录呈现的是构建产物和映射，未见包清单；需继续寻找构建对应的源仓库及锁文件。映射只用于本机审查，未加入候选。

该固定提交的 [README](https://github.com/Adcage/unlock-music/blob/eb61b9ee1963b0aa731e71d066b31602cec67273/README.md)称其为预构建版本、具体版本未知，并指向原仓库 `git.unlock-music.dev/um/web`。因此 Adcage 仓库的根许可证本身不足以确认该构建产物及所有嵌入依赖的授权链。

本次直接读取原仓库的 `package.json` 和 `LICENSE` 收到 Cloudflare 403 挑战页面，访问首页超时；未绕过站点限制，也未由此推断其授权内容。
