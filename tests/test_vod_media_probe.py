from core.vod_analyzer.media_probe import parse_fps, parse_probe_payload


def test_parse_ffprobe_payload() -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "width": 1280, "height": 720, "avg_frame_rate": "30000/1001"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "612.5"},
    }
    result = parse_probe_payload(payload)
    assert result["codec"] == "hevc"
    assert result["duration_seconds"] == 612.5
    assert result["has_audio"] is True
    assert round(result["fps"], 2) == 29.97


def test_invalid_fps_is_zero() -> None:
    assert parse_fps("0/0") == 0
    assert parse_fps("broken") == 0
