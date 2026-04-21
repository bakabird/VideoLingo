# VideoLingo CLI 产出与字幕识别方案探索总结

日期：2026-04-21

## 结论概览

1. VideoLingo 支持通过命令行完成批量产出，但当前形态是“Excel 配置 + Python 批处理脚本”，不是带参数的正式 CLI。
2. 字幕识别主线是 WhisperX 词级时间戳识别，默认本地运行；也支持 302.ai WhisperX API；ElevenLabs ASR 分支处于实验性质，当前代码存在下游兼容风险。
3. 产出链路覆盖字幕视频和可选配音视频：无配音时生成字幕视频；开启配音时继续生成配音音轨并合成最终配音视频。

## 1. 是否支持通过 CLI 完成产出操作

支持，但要准确理解这里的“CLI”边界。

当前批处理入口：

```bash
python batch/utils/batch_processor.py
```

Windows/uv 包装入口：

```bat
batch\OneKeyBatch_uv.bat
```

传统 Conda 包装入口：

```bat
batch\OneKeyBatch.bat
```

### 当前 CLI 形态

它不是这种形态：

```bash
videolingo --input demo.mp4 --source en --target "简体中文" --dubbing 1
```

而是这种形态：

```text
batch/tasks_setting.xlsx
batch/input/
        │
        ▼
python batch/utils/batch_processor.py
        │
        ▼
逐行读取 Excel 任务并产出结果
```

任务配置来自 `batch/tasks_setting.xlsx`，主要字段包括：

| 字段 | 含义 |
| --- | --- |
| `Video File` | 本地视频文件名或 YouTube URL |
| `Source Language` | 源语言，如 `en`、`zh`，留空则使用默认配置 |
| `Target Language` | 目标翻译语言，可用自然语言描述 |
| `Dubbing` | 是否配音，`0` 或空为不配音，`1` 为配音 |
| `Status` | 执行状态，由批处理脚本更新 |

相关代码位置：

- `batch/utils/batch_processor.py`: `process_batch()` 读取 `batch/tasks_setting.xlsx` 并遍历任务。
- `batch/utils/batch_processor.py`: 每个任务调用 `process_video(video_file, dubbing, is_retry)`。
- `batch/utils/video_processor.py`: `process_video()` 定义单视频处理流水线。
- `batch/README.zh.md`: 批处理模式使用说明。

### 批处理产出链路

```text
批处理入口
  │
  ▼
读取 batch/tasks_setting.xlsx
  │
  ▼
校验 batch/input 与任务表
  │
  ▼
按任务临时写入源语言 / 目标语言配置
  │
  ▼
process_video()
  ├─ 处理输入文件：复制本地视频或下载 URL
  ├─ Whisper/ASR 转录
  ├─ NLP + LLM 分句
  ├─ 摘要与多步翻译
  ├─ 切分并对齐字幕
  ├─ 烧录字幕到视频
  └─ 如果 Dubbing=1：继续配音合成
```

字幕阶段：

```text
输入视频
  │
  ▼
ASR 转录
  │
  ▼
分句 / 翻译 / 字幕切分
  │
  ▼
生成 SRT
  │
  ▼
output/output_sub.mp4
```

配音阶段：

```text
字幕阶段完成
  │
  ▼
生成 TTS 任务
  │
  ▼
提取参考音频
  │
  ▼
生成配音片段
  │
  ▼
合并完整配音音轨
  │
  ▼
output/output_dub.mp4
```

### 输出位置说明

批处理代码里有两个关键目录：

| 目录 | 用途 |
| --- | --- |
| `output/` | 当前单个任务的中间产物和临时最终产物 |
| `batch/output/` | 批处理成功后归档位置 |
| `batch/output/ERROR/` | 批处理失败后归档位置 |

代码中 `process_video()` 成功后会调用：

```text
cleanup(SAVE_DIR)
```

其中：

```text
SAVE_DIR = "batch/output"
```

因此，虽然部分文档口径写“输出在 output 文件夹”，但从代码路径看，批处理成功后的稳定结果应以 `batch/output/<视频名>/` 为准。

### 当前 CLI 的限制

1. 没有正式命令参数解析层，例如 `argparse`、`click`、`typer`。
2. 任务输入依赖 Excel，自动化系统需要先生成或修改 `batch/tasks_setting.xlsx`。
3. 部分全局配置仍依赖 `config.yaml`，例如 Whisper runtime、模型、API key、TTS 方法等。
4. 批处理会临时更新 `config.yaml` 中的语言字段，异常中断后可能需要人工检查配置恢复情况。
5. 批处理模式文档标记为 beta，代码和文档对输出目录的描述不完全一致。

## 2. 字幕识别使用的方案

字幕识别由 `core/_2_asr.py` 编排，主线是 WhisperX。

整体流程：

```text
输入视频
  │
  ▼
ffmpeg 抽取音频
  │
  ▼
output/audio/raw.mp3
  │
  ├─ demucs=true
  │     └─ Demucs 分离人声 / 背景音
  │
  ▼
选择用于识别和对齐的音频
  │
  ▼
按静音点切成长片段
  │
  ▼
按 whisper.runtime 选择 ASR 后端
  ├─ local      -> 本地 WhisperX
  ├─ cloud      -> 302.ai WhisperX API
  └─ elevenlabs -> ElevenLabs Speech-to-Text
  │
  ▼
合并分段识别结果
  │
  ▼
整理为词级 DataFrame
  │
  ▼
output/log/cleaned_chunks.xlsx
```

### 默认配置

相关配置位于 `config.yaml`：

```yaml
demucs: true

whisper:
  model: 'large-v3'
  language: 'en'
  detected_language: 'en'
  runtime: 'local'
  whisperX_302_api_key: 'your_302_api_key'
  elevenlabs_api_key: 'your_elevenlabs_api_key'
```

默认识别方式：

| 配置项 | 默认值 | 含义 |
| --- | --- | --- |
| `demucs` | `true` | ASR 前先做人声分离 |
| `whisper.model` | `large-v3` | 默认 Whisper 模型 |
| `whisper.language` | `en` | 指定识别语言 |
| `whisper.runtime` | `local` | 默认本地 WhisperX |

### 本地 WhisperX 后端

入口：

```text
core/asr_backend/whisperX_local.py
```

关键行为：

1. 自动选择设备：有 CUDA 用 GPU，否则用 CPU。
2. 根据显存调整 batch size 和 compute type。
3. 非中文默认使用 `config.yaml` 中的 `whisper.model`，例如 `large-v3`。
4. 中文识别强制使用 `Huan69/Belle-whisper-large-v3-zh-punct-fasterwhisper`。
5. 先执行 Whisper 转录，再使用 WhisperX align model 做词级时间戳对齐。
6. 对每个切片的时间戳加回全局 offset，合并后得到完整视频时间轴。

本地链路可以理解为：

```text
raw_audio_segment
  │
  ▼
Whisper / faster-whisper 转录
  │
  ▼
segments
  │
  ▼
WhisperX align model + vocal_audio_segment
  │
  ▼
word-level timestamps
```

### 302.ai WhisperX 后端

入口：

```text
core/asr_backend/whisperX_302.py
```

配置：

```yaml
whisper:
  runtime: 'cloud'
  whisperX_302_api_key: '...'
```

关键行为：

1. 从人声音频中按片段切出 WAV。
2. 请求 `https://api.302.ai/302/whisperx`。
3. payload 使用 `processing_type: align`，输出 `raw`。
4. 返回结果后同样加回切片 offset。
5. 会把每个片段结果缓存到 `output/log/whisperx302_<start>_<end>.json`。

适用场景：

| 场景 | 适配度 |
| --- | --- |
| 本地没有 GPU | 较适合 |
| 不想下载本地模型 | 较适合 |
| 网络/API 稳定 | 较适合 |
| 需要完全离线 | 不适合 |

### ElevenLabs ASR 后端

入口：

```text
core/asr_backend/elevenlabs_asr.py
```

配置：

```yaml
whisper:
  runtime: 'elevenlabs'
  elevenlabs_api_key: '...'
```

关键行为：

1. 使用 ElevenLabs `scribe_v1`。
2. 请求 `timestamps_granularity: word`。
3. 开启 `diarize: True`。
4. 将 ElevenLabs 结果转换为类似 Whisper 的 `segments` 格式。

风险判断：

当前代码里 `elev2whisper()` 默认 `word_level_timestamp=False`，会移除 `words` 字段；但下游 `process_transcription()` 期待 `segment['words']`。因此这个后端在当前代码状态下存在兼容风险，不应视为主推稳定方案。

### Demucs 人声分离

配置：

```yaml
demucs: true
```

作用：

```text
output/audio/raw.mp3
  │
  ▼
Demucs htdemucs
  ├─ output/audio/vocal.mp3
  └─ output/audio/background.mp3
```

ASR 转录时：

1. 原始音频用于整体切片与部分转录输入。
2. 人声音频用于 WhisperX 对齐，降低背景音乐对词级时间戳的干扰。

这个设计解释了 README 中提到的限制：背景音乐较大的视频会影响 WhisperX 对齐效果，因此建议开启人声分离增强。

## 3. 关键产物

| 产物 | 说明 |
| --- | --- |
| `output/audio/raw.mp3` | ffmpeg 从视频中提取的 16k 单声道音频 |
| `output/audio/vocal.mp3` | Demucs 分离出的人声 |
| `output/audio/background.mp3` | Demucs 分离出的背景音 |
| `output/log/cleaned_chunks.xlsx` | ASR 后的词级结果 |
| `output/log/translation_results.xlsx` | 翻译中间结果 |
| `output/src.srt` | 源语言字幕 |
| `output/trans.srt` | 目标语言字幕 |
| `output/src_trans.srt` | 源语言 + 目标语言字幕 |
| `output/trans_src.srt` | 目标语言 + 源语言字幕 |
| `output/output_sub.mp4` | 烧录字幕后的视频 |
| `output/audio/tts_tasks.xlsx` | 配音任务表 |
| `output/dub.wav` | 合并后的配音音轨 |
| `output/dub.srt` | 配音字幕 |
| `output/output_dub.mp4` | 最终配音视频 |

## 4. 工程判断

如果目标是“自动化产出”，当前代码已经具备可用的批处理能力：

```text
准备 batch/input
  │
  ▼
写入 batch/tasks_setting.xlsx
  │
  ▼
执行 python batch/utils/batch_processor.py
  │
  ▼
读取 batch/output
```

如果目标是“产品化 CLI”，当前还缺一层正式命令接口。比较自然的演进方向是：

```text
videolingo batch --tasks batch/tasks_setting.xlsx
videolingo run --input demo.mp4 --source en --target zh-CN
videolingo asr --input demo.mp4 --runtime local
```

但这属于后续变更设计，不是当前已实现能力。

## 5. 建议保守口径

对外描述时建议这样说：

> VideoLingo 当前支持通过批处理脚本在命令行完成产出，任务通过 `batch/tasks_setting.xlsx` 配置，适合批量自动化处理；但尚未提供完整参数化 CLI。字幕识别默认使用本地 WhisperX 进行词级时间戳转录与对齐，可切换到 302.ai WhisperX API，ElevenLabs ASR 为实验支持。

