# VideoLingo Batch Mode

[English](./README.md) | [简体中文](./README.zh.md)

Before utilizing the batch mode, ensure you have used the Streamlit mode and properly configured the parameters in `config.yaml`.

## Usage Guide

### 1. Video File Preparation

- Place your video files in the `input` folder
- YouTube links can be specified in the next step

### 2. Task Configuration

Edit the `tasks_setting.xlsx` file:

| Field | Description | Acceptable Values |
|-------|-------------|-------------------|
| Video File | Video filename (without `input/` prefix) or YouTube URL | - |
| Source Language | Source language | 'en', 'zh', ... or leave empty for default |
| Target Language | Translation language | Use natural language description, or leave empty for default |
| Dubbing | Enable dubbing | 0 or empty: no dubbing; 1: enable dubbing |

Example:

| Video File | Source Language | Target Language | Dubbing |
|------------|-----------------|-----------------|---------|
| https://www.youtube.com/xxx | | German | |
| Kungfu Panda.mp4 | |  | 1 |

### 3. Executing Batch Processing

1. Double-click to run `OneKeyBatch.bat`
2. Output files will be saved in the `output` folder
3. Task status can be monitored in the `Status` column of `tasks_setting.xlsx`

> Note: Keep `tasks_setting.xlsx` closed during execution to prevent interruptions due to file access conflicts.

### Japanese to Chinese with Fun-ASR

To use DashScope recorded-file Fun-ASR for Japanese source videos and Chinese subtitles:

1. In `config.yaml`, set `whisper.runtime` to `fun_asr_file`.
2. Set `DASHSCOPE_API_KEY` in your environment, or fill `whisper.fun_asr_file.api_key`.
3. Keep `whisper.fun_asr_file.upload_provider` as `dashscope_tmp` unless you already host segment WAV files through OSS, CDN, or a web server.
4. In `tasks_setting.xlsx`, set `Source Language` to `ja` and `Target Language` to `简体中文` for each Japanese-to-Chinese task.

`fun_asr_file` currently accepts `ja`, `zh`, and `en` source language hints. Other values fail before submitting a DashScope job.

## Important Considerations

### Handling Interruptions

If the command line is closed unexpectedly, language settings in `config.yaml` may be altered. Check settings before retrying.

### Error Management

- Failed files will be moved to the `output/ERROR` folder
- Error messages are recorded in the `Status` column of `tasks_setting.xlsx`
- To retry:
  1. Move the single video folder from `ERROR` to the root directory
  2. Rename it to `output`
  3. Use Streamlit mode to process again
