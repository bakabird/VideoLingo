import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import requests
from rich import print as rprint

from core.utils.config_utils import load_key, update_key
from core.utils.models import _AUDIO_TMP_DIR


OUTPUT_LOG_DIR = Path("output/log")
RUNTIME_NAME = "fun_asr_file"
SUPPORTED_LANGUAGE_HINTS = {"ja", "zh", "en"}
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com"

REQUEST_PARAMETER_VERSION = "dashscope-fun-asr-file-rest-v1"
LANGUAGE_MAPPING_VERSION = "videolingo-fun-asr-language-v1"
CONVERTER_VERSION = "dashscope-fun-asr-to-whisper-v1"

TRANSIENT_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
PENDING_TASK_STATUS = {"PENDING", "RUNNING"}
FAILED_TASK_STATUS = {"FAILED", "CANCELED", "CANCELLED", "UNKNOWN"}
PLACEHOLDER_VALUES = {
    "",
    "your_dashscope_api_key",
    "your-dashscope-api-key",
    "your-api-key",
    "sk-xxx",
    "sk-xxxx",
}

PUNCTUATION_RE = re.compile(r"^[\s,.;:!?，。；：！？、\-—…\"'“”‘’（）()【】\[\]{}<>《》]+$")


def _load_optional(key: str, default: Any = None) -> Any:
    try:
        return load_key(key)
    except KeyError:
        return default


def _is_placeholder(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in PLACEHOLDER_VALUES


def _get_dashscope_api_key() -> str:
    source = _load_optional("whisper.fun_asr_file.api_key_source", "env_or_config")
    env_name = _load_optional("whisper.fun_asr_file.api_key_env", "DASHSCOPE_API_KEY")
    env_key = os.getenv(env_name, "")
    config_key = _load_optional("whisper.fun_asr_file.api_key", "")

    if source == "env":
        api_key = env_key
    elif source == "config":
        api_key = config_key
    else:
        api_key = env_key or config_key

    if _is_placeholder(api_key):
        return ""
    return str(api_key).strip()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalise_base_url(base_url: str) -> str:
    return (base_url or DEFAULT_DASHSCOPE_BASE_URL).rstrip("/")


def normalise_fun_asr_language(language: str) -> str:
    language_hint = (language or "").strip().lower()
    if language_hint not in SUPPORTED_LANGUAGE_HINTS:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGE_HINTS))
        raise ValueError(
            "fun_asr_file supports source language hints "
            f"{supported}. Set whisper.language to one of those values before transcription."
        )
    return language_hint


def load_fun_asr_file_config() -> Dict[str, Any]:
    language_hint = normalise_fun_asr_language(_load_optional("whisper.language", ""))
    return {
        "runtime": RUNTIME_NAME,
        "model": _load_optional("whisper.fun_asr_file.model", "fun-asr") or "fun-asr",
        "api_key": _get_dashscope_api_key(),
        "api_key_source": _load_optional("whisper.fun_asr_file.api_key_source", "env_or_config"),
        "api_key_env": _load_optional("whisper.fun_asr_file.api_key_env", "DASHSCOPE_API_KEY"),
        "language_hint": language_hint,
        "enable_itn": bool(_load_optional("whisper.fun_asr_file.enable_itn", True)),
        "cache_enabled": bool(_load_optional("whisper.fun_asr_file.cache", True)),
        "upload_provider": _load_optional("whisper.fun_asr_file.upload_provider", "dashscope_tmp"),
        "base_url": _normalise_base_url(
            _load_optional("whisper.fun_asr_file.dashscope.base_url", DEFAULT_DASHSCOPE_BASE_URL)
        ),
        "poll_interval_seconds": _as_float(
            _load_optional("whisper.fun_asr_file.dashscope.poll_interval_seconds", 2), 2
        ),
        "poll_timeout_seconds": _as_float(
            _load_optional("whisper.fun_asr_file.dashscope.poll_timeout_seconds", 1800), 1800
        ),
        "max_retries": _as_int(_load_optional("whisper.fun_asr_file.dashscope.max_retries", 3), 3),
        "retry_backoff_seconds": _as_float(
            _load_optional("whisper.fun_asr_file.dashscope.retry_backoff_seconds", 1), 1
        ),
        "public_url_base": _load_optional("whisper.fun_asr_file.public_url.base_url", ""),
        "public_url_template": _load_optional("whisper.fun_asr_file.public_url.url_template", ""),
        "public_local_output_dir": _load_optional(
            "whisper.fun_asr_file.public_url.local_output_dir",
            os.path.join(_AUDIO_TMP_DIR, "fun_asr_public"),
        ),
    }


def validate_fun_asr_file_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = dict(config or load_fun_asr_file_config())

    if not str(config.get("model", "")).strip():
        raise ValueError("fun_asr_file requires whisper.fun_asr_file.model, defaulting to fun-asr.")
    if not config.get("api_key"):
        env_name = config.get("api_key_env", "DASHSCOPE_API_KEY")
        raise ValueError(
            "fun_asr_file requires a DashScope API key. "
            f"Set environment variable {env_name} or whisper.fun_asr_file.api_key."
        )

    provider = str(config.get("upload_provider", "")).strip()
    if provider == "dashscope_tmp":
        if not config.get("base_url"):
            raise ValueError("fun_asr_file requires whisper.fun_asr_file.dashscope.base_url.")
    elif provider == "public_url":
        base = str(config.get("public_url_base") or "").strip()
        template = str(config.get("public_url_template") or "").strip()
        if not base and not template:
            raise ValueError(
                "fun_asr_file public_url upload provider requires "
                "whisper.fun_asr_file.public_url.base_url or url_template."
            )
    else:
        raise ValueError(
            "fun_asr_file upload_provider must be dashscope_tmp or public_url."
        )

    normalise_fun_asr_language(str(config.get("language_hint", "")))
    return config


def _safe_number(value: Optional[float]) -> str:
    if value is None:
        return "full"
    return f"{float(value):.3f}".replace(".", "_")


def slice_audio_to_pcm_wav(
    audio_path: str,
    start: Optional[float],
    end: Optional[float],
    output_dir: Optional[str] = None,
    filename_prefix: Optional[str] = None,
) -> str:
    output_root = Path(output_dir or os.path.join(_AUDIO_TMP_DIR, RUNTIME_NAME))
    output_root.mkdir(parents=True, exist_ok=True)

    if start is None:
        start = 0.0
    if end is not None and end <= start:
        raise ValueError(f"Invalid Fun-ASR segment range: start={start}, end={end}")

    prefix = filename_prefix or f"fun_asr_{_safe_number(start)}_{_safe_number(end)}"
    output_path = output_root / f"{prefix}.wav"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start:
        cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", audio_path])
    if end is not None:
        cmd.extend(["-t", f"{end - start:.3f}"])
    cmd.extend(["-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output_path)])

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to prepare Fun-ASR audio segments.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"Failed to prepare Fun-ASR PCM WAV segment: {stderr}") from exc

    return str(output_path)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_metadata(
    segment_path: str,
    runtime: str,
    model: str,
    language_hint: str,
    enable_itn: bool,
    request_parameter_version: str = REQUEST_PARAMETER_VERSION,
    language_mapping_version: str = LANGUAGE_MAPPING_VERSION,
    converter_version: str = CONVERTER_VERSION,
) -> Dict[str, Any]:
    return {
        "audio_sha256": _sha256_file(segment_path),
        "runtime": runtime,
        "model": model,
        "language_hint": language_hint,
        "enable_itn": bool(enable_itn),
        "request_parameter_version": request_parameter_version,
        "language_mapping_version": language_mapping_version,
        "converter_version": converter_version,
    }


def build_fun_asr_cache_key(
    segment_path: str,
    runtime: str = RUNTIME_NAME,
    model: str = "fun-asr",
    language_hint: str = "ja",
    enable_itn: bool = True,
    request_parameter_version: str = REQUEST_PARAMETER_VERSION,
    language_mapping_version: str = LANGUAGE_MAPPING_VERSION,
    converter_version: str = CONVERTER_VERSION,
) -> str:
    metadata = _cache_metadata(
        segment_path,
        runtime,
        model,
        language_hint,
        enable_itn,
        request_parameter_version,
        language_mapping_version,
        converter_version,
    )
    payload = json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _operation_retry_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "max_attempts": max(1, int(config.get("max_retries", 3))),
        "backoff_seconds": max(0.1, float(config.get("retry_backoff_seconds", 1))),
    }


def _retry_call(
    operation: str,
    func: Callable[[], Any],
    max_attempts: int,
    backoff_seconds: float,
) -> Any:
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    raise RuntimeError(f"{operation} failed after {max_attempts} attempts: {last_error}") from last_error


def _response_json(response: requests.Response, operation: str) -> Dict[str, Any]:
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{operation} returned non-JSON response: {response.text[:500]}") from exc


def _request_with_retries(
    method: str,
    url: str,
    operation: str,
    config: Dict[str, Any],
    **kwargs: Any,
) -> requests.Response:
    retry_config = _operation_retry_config(config)

    def _call() -> requests.Response:
        response = requests.request(method, url, timeout=60, **kwargs)
        if response.status_code in TRANSIENT_HTTP_STATUS:
            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text[:500]}"
            )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text[:1000]}"
            )
        return response

    return _retry_call(operation, _call, **retry_config)


def _request_json_with_retries(
    method: str,
    url: str,
    operation: str,
    config: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    response = _request_with_retries(method, url, operation, config, **kwargs)
    return _response_json(response, operation)


def _dashscope_headers(config: Dict[str, Any], file_url: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    if file_url and file_url.startswith("oss://"):
        headers["X-DashScope-OssResourceResolve"] = "enable"
    return headers


def upload_dashscope_tmp(segment_path: str, config: Dict[str, Any]) -> str:
    url = f"{config['base_url']}/api/v1/uploads"
    policy_payload = _request_json_with_retries(
        "GET",
        url,
        "DashScope upload policy",
        config,
        headers=_dashscope_headers(config),
        params={"action": "getPolicy", "model": config["model"]},
    )
    policy_data = policy_payload.get("data") or {}
    required = [
        "upload_dir",
        "upload_host",
        "oss_access_key_id",
        "signature",
        "policy",
        "x_oss_object_acl",
        "x_oss_forbid_overwrite",
    ]
    missing = [key for key in required if not policy_data.get(key)]
    if missing:
        raise RuntimeError(f"DashScope upload policy missing fields: {', '.join(missing)}")

    filename = Path(segment_path).name
    key = f"{policy_data['upload_dir'].rstrip('/')}/{filename}"
    with open(segment_path, "rb") as audio_file:
        files = {
            "OSSAccessKeyId": (None, policy_data["oss_access_key_id"]),
            "Signature": (None, policy_data["signature"]),
            "policy": (None, policy_data["policy"]),
            "x-oss-object-acl": (None, policy_data["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy_data["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (filename, audio_file, "audio/wav"),
        }
        _request_with_retries(
            "POST",
            policy_data["upload_host"],
            "DashScope temporary file upload",
            config,
            files=files,
        )
    return f"oss://{key}"


def public_url_for_segment(
    segment_path: str,
    config: Dict[str, Any],
    cache_key: str,
    start: Optional[float],
    end: Optional[float],
) -> str:
    filename = Path(segment_path).name
    template = str(config.get("public_url_template") or "").strip()
    if template:
        try:
            url = template.format(
                filename=filename,
                basename=Path(filename).stem,
                cache_key=cache_key,
                start=_safe_number(start),
                end=_safe_number(end),
            )
        except KeyError as exc:
            raise ValueError(f"Unknown public_url.url_template field: {exc}") from exc
    else:
        url = f"{str(config.get('public_url_base')).rstrip('/')}/{filename}"

    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("oss://")):
        raise ValueError(
            "fun_asr_file public_url provider must produce an http://, https://, or oss:// URL."
        )
    return url


def submit_transcription_job(file_url: str, config: Dict[str, Any]) -> str:
    headers = _dashscope_headers(config, file_url)
    headers["X-DashScope-Async"] = "enable"
    parameters = {
        "channel_id": [0],
        "diarization_enabled": False,
        "language_hints": [config["language_hint"]],
    }
    if not config.get("enable_itn", True):
        parameters["inverse_text_normalization_enabled"] = False

    payload = {
        "model": config["model"],
        "input": {"file_urls": [file_url]},
        "parameters": parameters,
    }
    response_json = _request_json_with_retries(
        "POST",
        f"{config['base_url']}/api/v1/services/audio/asr/transcription",
        "DashScope Fun-ASR job submission",
        config,
        headers=headers,
        data=json.dumps(payload),
    )
    output = response_json.get("output") or {}
    task_id = output.get("task_id")
    if not task_id:
        raise RuntimeError(f"DashScope submission did not return a task_id: {response_json}")
    return task_id


def poll_transcription_job(task_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{config['base_url']}/api/v1/tasks/{task_id}"
    headers = _dashscope_headers(config)
    deadline = time.time() + float(config.get("poll_timeout_seconds", 1800))
    interval = max(0.5, float(config.get("poll_interval_seconds", 2)))

    while True:
        response_json = _request_json_with_retries(
            "POST",
            url,
            "DashScope Fun-ASR job polling",
            config,
            headers=headers,
        )
        output = response_json.get("output") or response_json
        task_status = output.get("task_status")

        if task_status == "SUCCEEDED":
            return response_json
        if task_status in FAILED_TASK_STATUS:
            raise RuntimeError(f"DashScope Fun-ASR task {task_id} failed: {response_json}")
        if task_status not in PENDING_TASK_STATUS:
            raise RuntimeError(f"DashScope Fun-ASR task {task_id} returned unknown status: {response_json}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for DashScope Fun-ASR task {task_id}.")
        time.sleep(interval)


def _select_transcription_result(poll_response: Dict[str, Any]) -> Dict[str, Any]:
    output = poll_response.get("output") or poll_response
    results = output.get("results") or []
    if not results:
        raise RuntimeError(f"DashScope Fun-ASR task succeeded without result URLs: {poll_response}")
    result = results[0]
    if result.get("subtask_status") != "SUCCEEDED":
        raise RuntimeError(f"DashScope Fun-ASR subtask failed: {result}")
    if not result.get("transcription_url"):
        raise RuntimeError(f"DashScope Fun-ASR result missing transcription_url: {result}")
    return result


def download_transcription_result(transcription_url: str, config: Dict[str, Any]) -> Dict[str, Any]:
    response = _request_with_retries(
        "GET",
        transcription_url,
        "DashScope Fun-ASR result download",
        config,
    )
    return _response_json(response, "DashScope Fun-ASR result download")


def _to_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def _is_punctuation_only(text: str) -> bool:
    return bool(text and PUNCTUATION_RE.match(text))


def _iter_sentences(dashscope_json: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for transcript in dashscope_json.get("transcripts") or []:
        for sentence in transcript.get("sentences") or []:
            yield sentence


def dashscope_result_to_whisper(
    dashscope_json: Dict[str, Any],
    segment_start_offset: float = 0.0,
) -> Dict[str, Any]:
    segments = []
    usable_word_count = 0
    saw_word_items = False

    for sentence in _iter_sentences(dashscope_json):
        sentence_words = sentence.get("words")
        if not sentence_words:
            continue
        words = []

        for item in sentence_words:
            saw_word_items = True
            begin = _to_seconds(item.get("begin_time"))
            end = _to_seconds(item.get("end_time"))
            if begin is None or end is None:
                raise ValueError(
                    "DashScope Fun-ASR output contains a word item without usable "
                    f"begin_time/end_time: {item}"
                )

            text = str(item.get("text") or "")
            punctuation = str(item.get("punctuation", item.get("punc", "")) or "")
            punct_only = _is_punctuation_only(text) or (not text.strip() and bool(punctuation))

            if punct_only:
                if not words:
                    continue
                words[-1]["word"] += text + punctuation
                words[-1]["end"] = segment_start_offset + end
                continue

            word_text = text + punctuation
            if not word_text.strip():
                continue
            words.append(
                {
                    "word": word_text,
                    "start": segment_start_offset + begin,
                    "end": segment_start_offset + end,
                }
            )
            usable_word_count += 1

        if words:
            sentence_begin = _to_seconds(sentence.get("begin_time"))
            sentence_end = _to_seconds(sentence.get("end_time"))
            segment = {
                "text": "".join(word["word"] for word in words).strip(),
                "start": segment_start_offset + sentence_begin
                if sentence_begin is not None
                else words[0]["start"],
                "end": segment_start_offset + sentence_end
                if sentence_end is not None
                else words[-1]["end"],
                "words": words,
            }
            if "speaker_id" in sentence:
                segment["speaker_id"] = sentence["speaker_id"]
            segments.append(segment)

    if not saw_word_items or usable_word_count == 0:
        raise ValueError(
            "DashScope Fun-ASR output did not contain usable word timestamps. "
            "Word-level timestamps are required for VideoLingo subtitle alignment."
        )
    return {"segments": segments}


def _error_log_path(cache_key: Optional[str]) -> Path:
    suffix = cache_key[:12] if cache_key else datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return OUTPUT_LOG_DIR / f"fun_asr_file_error_{suffix}.json"


def _write_error_log(cache_key: Optional[str], error: Exception, context: Dict[str, Any]) -> None:
    payload = {
        "error": str(error),
        "error_type": error.__class__.__name__,
        "context": context,
    }
    _write_json(_error_log_path(cache_key), payload)


def transcribe_audio_fun_asr_file(
    raw_audio_path: str,
    vocal_audio_path: str,
    start: Optional[float] = None,
    end: Optional[float] = None,
) -> Dict[str, Any]:
    config = validate_fun_asr_file_config()
    OUTPUT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    start_offset = float(start or 0.0)
    public_provider = config["upload_provider"] == "public_url"
    temp_output_dir = (
        config["public_local_output_dir"]
        if public_provider
        else os.path.join(_AUDIO_TMP_DIR, RUNTIME_NAME)
    )
    segment_path = None
    cache_key = None

    try:
        segment_path = slice_audio_to_pcm_wav(
            vocal_audio_path,
            start,
            end,
            output_dir=temp_output_dir,
            filename_prefix=f"fun_asr_{_safe_number(start)}_{_safe_number(end)}",
        )
        cache_key = build_fun_asr_cache_key(
            segment_path,
            runtime=RUNTIME_NAME,
            model=config["model"],
            language_hint=config["language_hint"],
            enable_itn=config["enable_itn"],
        )
        if public_provider:
            public_segment_path = Path(temp_output_dir) / f"fun_asr_{cache_key[:16]}.wav"
            if Path(segment_path) != public_segment_path:
                Path(segment_path).replace(public_segment_path)
                segment_path = str(public_segment_path)

        raw_cache_path = OUTPUT_LOG_DIR / f"fun_asr_file_raw_{cache_key}.json"
        job_log_path = OUTPUT_LOG_DIR / f"fun_asr_file_job_{cache_key}.json"

        if config["cache_enabled"] and raw_cache_path.exists():
            rprint(f"[cyan]Fun-ASR cache hit for segment {start_offset:.2f}s[/cyan]")
            raw_result = _read_json(raw_cache_path)
        else:
            if public_provider:
                file_url = public_url_for_segment(segment_path, config, cache_key, start, end)
            else:
                file_url = upload_dashscope_tmp(segment_path, config)

            task_id = submit_transcription_job(file_url, config)
            poll_response = poll_transcription_job(task_id, config)
            result_record = _select_transcription_result(poll_response)
            raw_result = download_transcription_result(result_record["transcription_url"], config)

            _write_json(job_log_path, {"file_url": file_url, "task_id": task_id, "poll": poll_response})
            _write_json(raw_cache_path, raw_result)

        update_key("whisper.detected_language", config["language_hint"])
        return dashscope_result_to_whisper(raw_result, segment_start_offset=start_offset)
    except Exception as exc:
        _write_error_log(
            cache_key,
            exc,
            {
                "start": start,
                "end": end,
                "raw_audio_path": raw_audio_path,
                "vocal_audio_path": vocal_audio_path,
                "segment_path": segment_path,
                "provider": config.get("upload_provider"),
                "model": config.get("model"),
                "language_hint": config.get("language_hint"),
            },
        )
        raise
    finally:
        if segment_path and not public_provider:
            try:
                Path(segment_path).unlink(missing_ok=True)
            except Exception:
                pass
