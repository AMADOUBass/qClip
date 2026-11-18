import json

import pytest

from qclip.utils.ffmpeg import parse_ffprobe, parse_fps

# Sortie réduite de `ffprobe -v error -print_format json -show_format -show_streams` sur une VOD Twitch.
FFPROBE_JSON = """
{
  "streams": [
    {"index": 0, "codec_name": "h264", "codec_type": "video", "width": 1920, "height": 1080,
     "r_frame_rate": "60/1", "avg_frame_rate": "60/1", "duration": "300.016667"},
    {"index": 1, "codec_name": "aac", "codec_type": "audio", "sample_rate": "48000", "channels": 2},
    {"index": 2, "codec_name": "aac", "codec_type": "audio", "sample_rate": "48000", "channels": 2}
  ],
  "format": {"filename": "sample.mp4", "nb_streams": 3, "duration": "300.021333", "size": "313354203"}
}
"""


def test_parse_ffprobe() -> None:
    info = parse_ffprobe(json.loads(FFPROBE_JSON))
    assert info.duration == pytest.approx(300.021333)
    assert (info.width, info.height) == (1920, 1080)
    assert info.fps == 60
    assert info.video_codec == "h264"
    assert info.audio_streams == 2


def test_parse_ffprobe_without_format_duration() -> None:
    data = json.loads(FFPROBE_JSON)
    del data["format"]["duration"]
    assert parse_ffprobe(data).duration == pytest.approx(300.016667)


def test_parse_ffprobe_audio_only() -> None:
    with pytest.raises(ValueError, match="aucune piste vidéo"):
        parse_ffprobe({"streams": [{"codec_type": "audio"}], "format": {}})


@pytest.mark.parametrize(
    ("rate", "expected"), [("30000/1001", 29.97), ("60/1", 60.0), ("0/0", 0.0), ("", 0.0), ("25", 25.0)]
)
def test_parse_fps(rate: str, expected: float) -> None:
    assert parse_fps(rate) == pytest.approx(expected, abs=0.01)
