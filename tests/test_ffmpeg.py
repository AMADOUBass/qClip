import json
import shutil
from pathlib import Path

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


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_scene_cuts_around_bounds_match_full_scan(tmp_path: Path) -> None:
    """M7 : chercher les coupes seulement autour des bornes donne les mêmes coupes que l'analyse de toute la plage."""
    from qclip.signals import scene_cuts
    from qclip.utils.ffmpeg import run

    video = tmp_path / "plage.mp4"
    # 8 s : gris foncé jusqu'à 2,93 s, puis blanc (coupe franche), puis rouge à 6,47 s
    result = run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:r=30:d=2.93",
                  "-f", "lavfi", "-i", "color=c=white:s=320x180:r=30:d=3.54", "-f", "lavfi", "-i",
                  "color=c=red:s=320x180:r=30:d=1.53", "-filter_complex", "[0][1][2]concat=n=3:v=1[v]",
                  "-map", "[v]", "-c:v", "libx264", "-g", "60", video])  # fmt: skip
    assert result.returncode == 0, result.stderr
    full = scene_cuts(video, 1000.0)
    assert len(full) == 2
    assert scene_cuts(video, 1000.0, around=[1003.2, 1006.0]) == full
    assert scene_cuts(video, 1000.0, around=[1004.7]) == []  # extrait 3,2-6,2 s : aucune coupe dedans
