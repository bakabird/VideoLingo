import json

import pytest

from core.asr_backend.fun_asr_file import (
    build_fun_asr_cache_key,
    dashscope_result_to_whisper,
    submit_transcription_job,
    validate_fun_asr_file_config,
)


def test_dashscope_conversion_merges_punctuation_and_converts_ms():
    dashscope_json = {
        "transcripts": [
            {
                "sentences": [
                    {
                        "begin_time": 100,
                        "end_time": 900,
                        "words": [
                            {
                                "begin_time": 100,
                                "end_time": 400,
                                "text": "こん",
                                "punctuation": "",
                            },
                            {
                                "begin_time": 400,
                                "end_time": 800,
                                "text": "にちは",
                                "punctuation": "。",
                            },
                            {
                                "begin_time": 800,
                                "end_time": 900,
                                "text": "！",
                                "punctuation": "",
                            },
                        ],
                    }
                ]
            }
        ]
    }

    result = dashscope_result_to_whisper(dashscope_json, segment_start_offset=1.0)

    words = result["segments"][0]["words"]
    assert words == [
        {"word": "こん", "start": 1.1, "end": 1.4},
        {"word": "にちは。！", "start": 1.4, "end": 1.9},
    ]
    assert result["segments"][0]["start"] == 1.1
    assert result["segments"][0]["end"] == 1.9


def test_segment_offset_applies_to_segment_and_words():
    dashscope_json = {
        "transcripts": [
            {
                "sentences": [
                    {
                        "begin_time": 1000,
                        "end_time": 2000,
                        "words": [
                            {
                                "begin_time": 1000,
                                "end_time": 1500,
                                "text": "hello",
                                "punctuation": "",
                            }
                        ],
                    }
                ]
            }
        ]
    }

    result = dashscope_result_to_whisper(dashscope_json, segment_start_offset=3.5)

    assert result["segments"][0]["start"] == 4.5
    assert result["segments"][0]["end"] == 5.5
    assert result["segments"][0]["words"][0]["start"] == 4.5
    assert result["segments"][0]["words"][0]["end"] == 5.0


def test_missing_word_timestamps_raises_actionable_error():
    dashscope_json = {"transcripts": [{"sentences": [{"text": "sentence only"}]}]}

    with pytest.raises(ValueError, match="word timestamps"):
        dashscope_result_to_whisper(dashscope_json)


def test_cache_key_changes_with_transcription_settings(tmp_path):
    audio = tmp_path / "segment.wav"
    audio.write_bytes(b"same segment bytes")

    base = build_fun_asr_cache_key(str(audio), model="fun-asr", language_hint="ja", enable_itn=True)
    variants = {
        build_fun_asr_cache_key(str(audio), model="fun-asr-mtl", language_hint="ja", enable_itn=True),
        build_fun_asr_cache_key(str(audio), model="fun-asr", language_hint="zh", enable_itn=True),
        build_fun_asr_cache_key(str(audio), model="fun-asr", language_hint="ja", enable_itn=False),
        build_fun_asr_cache_key(
            str(audio),
            model="fun-asr",
            language_hint="ja",
            enable_itn=True,
            request_parameter_version="request-v2",
        ),
        build_fun_asr_cache_key(
            str(audio),
            model="fun-asr",
            language_hint="ja",
            enable_itn=True,
            language_mapping_version="mapping-v2",
        ),
        build_fun_asr_cache_key(
            str(audio),
            model="fun-asr",
            language_hint="ja",
            enable_itn=True,
            converter_version="converter-v2",
        ),
    }

    assert base not in variants
    assert len(variants) == 6


def test_validation_reports_missing_upload_settings():
    with pytest.raises(ValueError, match="API key"):
        validate_fun_asr_file_config(
            {
                "model": "fun-asr",
                "api_key": "",
                "language_hint": "ja",
                "upload_provider": "dashscope_tmp",
                "base_url": "https://dashscope.aliyuncs.com",
            }
        )

    with pytest.raises(ValueError, match="public_url"):
        validate_fun_asr_file_config(
            {
                "model": "fun-asr",
                "api_key": "sk-test",
                "language_hint": "ja",
                "upload_provider": "public_url",
                "public_url_base": "",
                "public_url_template": "",
            }
        )

    with pytest.raises(ValueError, match="source language hints"):
        validate_fun_asr_file_config(
            {
                "model": "fun-asr",
                "api_key": "sk-test",
                "language_hint": "es",
                "upload_provider": "dashscope_tmp",
                "base_url": "https://dashscope.aliyuncs.com",
            }
        )


def test_submit_uses_oss_resolve_header_and_language_hint(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"output": {"task_id": "task-1"}}

    def fake_request(method, url, timeout=60, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["payload"] = json.loads(kwargs["data"])
        return Response()

    monkeypatch.setattr("core.asr_backend.fun_asr_file.requests.request", fake_request)
    config = {
        "api_key": "sk-test",
        "base_url": "https://dashscope.aliyuncs.com",
        "model": "fun-asr",
        "language_hint": "ja",
        "enable_itn": True,
        "max_retries": 1,
        "retry_backoff_seconds": 0.01,
    }

    task_id = submit_transcription_job("oss://dashscope-instant/example.wav", config)

    assert task_id == "task-1"
    assert captured["headers"]["X-DashScope-OssResourceResolve"] == "enable"
    assert captured["headers"]["X-DashScope-Async"] == "enable"
    assert captured["payload"]["parameters"]["language_hints"] == ["ja"]
    assert captured["payload"]["model"] == "fun-asr"
